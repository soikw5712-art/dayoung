import json
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core.db import add_post, connect, parse_iso, set_setting
from publishers.base import PublishError, PublishResult
from publishers.blog_package import make_package
from scheduler import assign_slots, run_due

KST = ZoneInfo("Asia/Seoul")
CFG = {
    "timezone": "Asia/Seoul",
    "threads": {"slots": ["08:30", "12:30", "21:00"], "daily_max": 2},
    "blog": {"slots": ["07:00"], "daily_max": 1},
    "random_delay_minutes": 5, "same_product_gap_hours": 6, "max_retries": 3, "retry_delay_minutes": 5,
}


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.sqlite")


@pytest.fixture
def content_file(tmp_path):
    path = tmp_path / "content.json"
    path.write_text(json.dumps({"threads": {"body": "b", "reply": "r"}, "product": {"product_id": "p"}}))
    return str(path)


def kst(*args):
    return datetime(*args, tzinfo=KST).astimezone(timezone.utc)


def slots(conn):
    return [parse_iso(r["slot_at"]).astimezone(KST).strftime("%d %H:%M")
            for r in conn.execute("SELECT slot_at FROM posts ORDER BY id")]


def test_slots_respect_daily_max_and_product_gap(conn, content_file):
    now = kst(2026, 10, 1, 8, 0)
    for pid in ["a", "b", "c", "a"]:
        add_post(conn, pid, "threads", content_file)
    assert assign_slots(conn, CFG, now, random.Random(0)) == 4
    # daily_max=2 → 1일 08:30, 12:30 / 2일 08:30, 12:30. 두 번째 'a'는 1일 08:30과 6시간 이상 떨어져야 함
    assert slots(conn) == ["01 08:30", "01 12:30", "02 08:30", "02 12:30"]
    for r in conn.execute("SELECT slot_at, scheduled_at FROM posts"):
        assert abs(parse_iso(r["scheduled_at"]) - parse_iso(r["slot_at"])) <= timedelta(minutes=5)


def test_slot_in_past_is_skipped(conn, content_file):
    add_post(conn, "a", "blog", content_file)
    assign_slots(conn, CFG, kst(2026, 10, 1, 9, 0))
    assert slots(conn) == ["02 07:00"]


def test_run_due_posts_and_retries_then_fails(conn, content_file, monkeypatch):
    monkeypatch.setattr("scheduler.notify", lambda msg: None)
    ok_id = add_post(conn, "a", "threads", content_file, scheduled_at=kst(2026, 10, 1, 8, 30))
    bad_id = add_post(conn, "b", "blog", content_file, scheduled_at=kst(2026, 10, 1, 8, 30))
    pubs = {"threads": lambda c, p, d: PublishResult("posted", "https://threads/1"),
            "blog": lambda c, p, d: (_ for _ in ()).throw(PublishError("boom"))}

    now = kst(2026, 10, 1, 8, 31)
    assert run_due(conn, CFG, now, pubs) == 1
    status = lambda i: conn.execute("SELECT status, retry_count FROM posts WHERE id=?", (i,)).fetchone()
    assert tuple(status(ok_id)) == ("posted", 0)
    assert tuple(status(bad_id)) == ("scheduled", 1)
    run_due(conn, CFG, kst(2026, 10, 1, 9, 0), pubs)   # 2회째 실패
    run_due(conn, CFG, kst(2026, 10, 1, 10, 0), pubs)  # 3회째 실패 → failed
    assert tuple(status(bad_id)) == ("failed", 3)


def test_emergency_stop_and_daily_limit(conn, content_file, monkeypatch):
    monkeypatch.setattr("scheduler.notify", lambda msg: None)
    at = kst(2026, 10, 1, 7, 0)
    ids = [add_post(conn, p, "blog", content_file, scheduled_at=at) for p in ("a", "b")]
    pubs = {"blog": lambda c, p, d: PublishResult("package_ready", "/tmp/x")}

    set_setting(conn, "emergency_stop", "1")
    assert run_due(conn, CFG, at + timedelta(minutes=1), pubs) == 0
    set_setting(conn, "emergency_stop", "0")
    assert run_due(conn, CFG, at + timedelta(minutes=1), pubs) == 1
    statuses = [conn.execute("SELECT status FROM posts WHERE id=?", (i,)).fetchone()[0] for i in ids]
    assert statuses == ["package_ready", "held"]


def test_blog_package(tmp_path):
    src = tmp_path / "src"
    (src / "images").mkdir(parents=True)
    (src / "images" / "card_01.png").write_bytes(b"png")
    content = {"product": {"product_id": "p1"},
               "blog": {"title": "제목", "tags": ["욕실", "#청소"], "disclosure": "고지", "link": "https://l",
                        "sections": [{"heading": "h1", "text": "t1"}]}}
    folder = make_package(7, src / "content.json", content, base=tmp_path)
    body = (folder / "본문.txt").read_text(encoding="utf-8")
    assert body.startswith("고지") and "[이미지: 01.png]" in body and "https://l" in body
    assert (folder / "태그.txt").read_text(encoding="utf-8") == "#욕실 #청소"
    assert (folder / "이미지" / "01.png").exists()


def test_threads_public_photo_urls(tmp_path, monkeypatch):
    from publishers import threads
    monkeypatch.setattr(threads, "output_dir", lambda: tmp_path)
    monkeypatch.setenv("PUBLIC_MEDIA_BASE_URL", "https://cdn.example.com/media/")
    content_path = tmp_path / "20260929_123" / "content.json"
    urls = threads.public_photo_urls(str(content_path), ["photos/photo_01.jpg", "photos/photo_02.jpg"])
    assert urls == ["https://cdn.example.com/media/20260929_123/photos/photo_01.jpg",
                    "https://cdn.example.com/media/20260929_123/photos/photo_02.jpg"]
    monkeypatch.delenv("PUBLIC_MEDIA_BASE_URL")
    assert threads.public_photo_urls(str(content_path), ["photos/photo_01.jpg"]) == []


def test_threads_carousel_request_flow(monkeypatch):
    from publishers import threads
    calls = []

    def fake_post(path, params):
        calls.append((path, dict(params)))
        return {"id": f"id{len(calls)}"}

    monkeypatch.setattr(threads, "_post", fake_post)
    monkeypatch.setattr(threads, "_wait_ready", lambda *a: None)
    cid = threads._create_container("u", "t", "본문", ["https://a/1.jpg", "https://a/2.jpg"], "상품추천", None)
    assert [c[1]["media_type"] for c in calls] == ["IMAGE", "IMAGE", "CAROUSEL"]
    assert calls[0][1]["is_carousel_item"] == "true"
    assert calls[2][1]["children"] == "id1,id2" and calls[2][1]["topic_tag"] == "상품추천"
    assert cid == "id3"
