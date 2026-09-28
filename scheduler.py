"""게시 대기열 슬롯 배정 + 예약 실행 (APScheduler, 1분 주기)."""
from __future__ import annotations

import json
import logging
import random
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from core.config import load_json
from core.db import connect, is_emergency_stopped, iso, parse_iso, update_post, utcnow
from notifier import notify
from publishers import blog_package, instagram, threads
from publishers.base import PublishResult

log = logging.getLogger("scheduler")

Publisher = Callable[[sqlite3.Connection, sqlite3.Row, dict], PublishResult]
PUBLISHERS: dict[str, Publisher] = {
    "threads": threads.publish,
    "instagram": instagram.publish,
    "blog": blog_package.publish,
}
CHANNEL_NAMES = {"threads": "스레드", "instagram": "인스타", "blog": "블로그"}
LOOKAHEAD_DAYS = 14


def _day_bounds(day_local: datetime, tz: ZoneInfo) -> tuple[str, str]:
    start = datetime.combine(day_local.date(), time.min, tz)
    return iso(start), iso(start + timedelta(days=1))


def _count_on_day(conn, channel: str, day_local: datetime, tz: ZoneInfo, statuses: tuple[str, ...]) -> int:
    start, end = _day_bounds(day_local, tz)
    marks = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT COUNT(*) FROM posts WHERE channel = ? AND status IN ({marks}) "
        f"AND COALESCE(posted_at, slot_at) >= ? AND COALESCE(posted_at, slot_at) < ?",
        (channel, *statuses, start, end),
    ).fetchone()[0]


ACTIVE = ("scheduled", "posting", "posted", "package_ready")


def find_slot(conn: sqlite3.Connection, channel: str, product_id: str, cfg: dict,
              now: datetime) -> datetime | None:
    """다음 빈 슬롯 (UTC). 하루 한도·슬롯 중복·같은 상품 간격을 모두 지킨다."""
    tz = ZoneInfo(cfg["timezone"])
    ch = cfg[channel]
    gap = timedelta(hours=cfg.get("same_product_gap_hours", 0))
    delay = timedelta(minutes=cfg.get("random_delay_minutes", 0))
    now_local = now.astimezone(tz)

    for d in range(LOOKAHEAD_DAYS):
        day = now_local + timedelta(days=d)
        if _count_on_day(conn, channel, day, tz, ACTIVE) >= ch["daily_max"]:
            continue
        for hhmm in sorted(ch["slots"]):
            h, m = map(int, hhmm.split(":"))
            slot = datetime.combine(day.date(), time(h, m), tz)
            if slot - delay <= now_local:
                continue
            taken = conn.execute(
                "SELECT 1 FROM posts WHERE channel = ? AND slot_at = ? AND status IN ('scheduled','posting','posted','package_ready')",
                (channel, iso(slot)),
            ).fetchone()
            if taken:
                continue
            clash = conn.execute(
                "SELECT 1 FROM posts WHERE product_id = ? AND status IN ('scheduled','posting','posted','package_ready') "
                "AND ABS(strftime('%s', slot_at) - strftime('%s', ?)) < ?",
                (product_id, iso(slot), int(gap.total_seconds())),
            ).fetchone()
            if clash:
                continue
            return slot.astimezone(ZoneInfo("UTC"))
    return None


def assign_slots(conn: sqlite3.Connection, cfg: dict | None = None, now: datetime | None = None,
                 rng: random.Random | None = None) -> int:
    """approved 게시물을 채널별 다음 빈 슬롯에 배정 → scheduled."""
    cfg = cfg or load_json("schedule.json")
    now = now or utcnow()
    rng = rng or random.Random()
    delay = cfg.get("random_delay_minutes", 0)
    assigned = 0
    for post in conn.execute("SELECT * FROM posts WHERE status = 'approved' ORDER BY id").fetchall():
        if post["channel"] not in cfg:
            continue
        slot = find_slot(conn, post["channel"], post["product_id"], cfg, now)
        if slot is None:
            log.warning("게시물 %s: %d일 안에 빈 슬롯 없음", post["id"], LOOKAHEAD_DAYS)
            continue
        jitter = timedelta(minutes=rng.uniform(-delay, delay)) if delay else timedelta()
        run_at = max(slot + jitter, now + timedelta(minutes=1))
        update_post(conn, post["id"], slot_at=iso(slot), scheduled_at=iso(run_at), status="scheduled")
        assigned += 1
    return assigned


def run_due(conn: sqlite3.Connection, cfg: dict | None = None, now: datetime | None = None,
            publishers: dict[str, Publisher] | None = None) -> int:
    """시간이 된 scheduled 게시물을 게시. 긴급 정지면 아무것도 하지 않는다."""
    if is_emergency_stopped(conn):
        return 0
    cfg = cfg or load_json("schedule.json")
    now = now or utcnow()
    publishers = publishers or PUBLISHERS
    tz = ZoneInfo(cfg["timezone"])
    max_retries = cfg.get("max_retries", 3)
    retry_delay = timedelta(minutes=cfg.get("retry_delay_minutes", 5))

    due = conn.execute(
        "SELECT * FROM posts WHERE status = 'scheduled' AND scheduled_at <= ? ORDER BY scheduled_at",
        (iso(now),),
    ).fetchall()
    done = 0
    for post in due:
        if is_emergency_stopped(conn):
            break
        channel = post["channel"]
        name = CHANNEL_NAMES.get(channel, channel)
        daily_max = cfg.get(channel, {}).get("daily_max")
        if daily_max is not None:
            posted_today = _count_on_day(conn, channel, now.astimezone(tz), tz, ("posted", "package_ready"))
            if posted_today >= daily_max:
                update_post(conn, post["id"], status="held", error="하루 게시 한도 초과로 보류")
                notify(f"⏸ {name} 게시물 #{post['id']} 보류: 오늘 한도({daily_max}) 초과")
                continue

        update_post(conn, post["id"], status="posting")
        try:
            content = json.loads(Path(post["content_path"]).read_text(encoding="utf-8"))
            result = publishers[channel](conn, post, content)
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 재시도/알림 흐름으로
            retries = post["retry_count"] + 1
            if retries >= max_retries:
                update_post(conn, post["id"], status="failed", retry_count=retries, error=str(e)[:1000])
                notify(f"❌ {name} 게시 실패 #{post['id']} ({retries}회 시도): {e}")
            else:
                update_post(conn, post["id"], status="scheduled", retry_count=retries, error=str(e)[:1000],
                            scheduled_at=iso(now + retry_delay * retries))
                log.warning("게시물 %s 실패, %d회째 재시도 예정: %s", post["id"], retries, e)
            continue

        update_post(conn, post["id"], status=result.status, posted_url=result.url,
                    posted_at=iso(now), error=None)
        done += 1
        if result.status == "package_ready":
            notify(f"📝 블로그 원고 준비됨 #{post['id']}\n{result.url}\n네이버 예약발행 후 `python main.py mark-posted {post['id']}`")
        else:
            notify(f"✅ {name} 게시 완료 #{post['id']}: {result.url}")
    return done


def tick() -> None:
    conn = connect()
    try:
        assign_slots(conn)
        run_due(conn)
    finally:
        conn.close()


def refresh_tokens() -> None:
    from core.config import env
    if not env("THREADS_ACCESS_TOKEN"):
        return
    conn = connect()
    try:
        threads.refresh_token(conn)
        log.info("Threads 토큰 갱신 완료")
    except Exception as e:  # noqa: BLE001
        notify(f"⚠️ Threads 토큰 갱신 실패 — 확인 필요: {e}")
    finally:
        conn.close()


def run_forever() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone=load_json("schedule.json")["timezone"])
    sched.add_job(tick, "interval", minutes=1, next_run_time=datetime.now(ZoneInfo("UTC")),
                  max_instances=1, coalesce=True)
    # 장기 토큰은 60일 유효 → 주 1회 갱신
    sched.add_job(refresh_tokens, "cron", day_of_week="mon", hour=4, minute=10)
    log.info("스케줄러 시작 (Ctrl+C로 종료)")
    sched.start()
