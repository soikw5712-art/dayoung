"""쿠팡 파트너스 SNS 자동화 CLI.

  # 수동 모드 (쿠팡 API 키 없을 때): 파트너스 사이트에서 만든 링크 + 상품 정보 직접 입력
  python main.py generate https://link.coupang.com/a/xxxx --name "상품명" --price 8900 --image 사진.jpg
  # API 모드 (.env에 쿠팡 키 있을 때)
  python main.py generate <쿠팡상품링크> --keyword "검색어"   # 원고 + 카드뉴스 (+ --video)
  python main.py show output/20260928_123/content.json       # 원고 미리보기(검수)
  python main.py approve output/.../content.json --channels threads,blog [--at "2026-10-01 08:30"]
  python main.py list                                         # 게시 대기열
  python main.py run                                          # 스케줄러 상시 실행
  python main.py tick                                         # 슬롯 배정 + 게시 1회
  python main.py mark-posted <id> [--url 블로그주소]           # 블로그 직접 발행 후 완료 처리
  python main.py retry <id> / cancel <id>
  python main.py stop / resume                                # 긴급 정지 / 해제
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import load_json
from core.db import connect, add_post, is_emergency_stopped, iso, parse_iso, set_setting, update_post, utcnow

CHANNELS = ("threads", "instagram", "blog")


def cmd_generate(args) -> None:
    from collectors.coupang import api_enabled, fetch_product
    from generators.copy import CopyGenerator, save_content

    manual = {"name": args.name, "price": args.price, "image_url": args.image,
              "discount_rate": args.discount, "category": args.category}
    print("● 쿠팡 API 모드" if api_enabled() else "● 수동 모드 (쿠팡 API 키 없음)")
    product = fetch_product(args.url, keyword=args.keyword, manual=manual,
                            affiliate_url=args.affiliate_url, product_id=args.product_id)
    print(f"✔ 상품: {product.name} ({product.price or '가격 미상'}원)\n  추적 링크: {product.affiliate_url}")

    gen = CopyGenerator()
    content, problems = gen.generate(product)
    path = save_content(product, content, problems, gen.model)
    print(f"✔ 원고 저장: {path}")
    for p in problems:
        print(f"  ⚠ 검수 필요: {p}")

    if not args.no_images:
        from generators.image import generate_cards
        cards = generate_cards(path)
        print(f"✔ 카드뉴스 {len(cards)}장: {cards[0].parent}")
    if args.video:
        from generators.video import generate_video
        print(f"✔ 영상: {generate_video(path)}")
    print(f"\n다음: python main.py show {path}  →  python main.py approve {path} --channels threads,blog")


def cmd_show(args) -> None:
    data = json.loads(Path(args.content).read_text(encoding="utf-8"))
    print("━━ 스레드 ━━\n" + data["threads"]["body"] + "\n  └ 답글: " + data["threads"]["reply"])
    print("\n━━ 인스타그램 ━━\n" + data["instagram"]["caption"])
    blog = data["blog"]
    print(f"\n━━ 블로그 ━━\n제목: {blog['title']}\n" + "\n".join(f"■ {s['heading']}" for s in blog["sections"]))
    print("\n━━ 카드뉴스 ━━\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(data["card_texts"], 1)))
    print("\n━━ 영상 대본 ━━\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(data["video_script"], 1)))
    for w in data["meta"].get("lint_warnings", []):
        print(f"⚠ {w}")


def cmd_approve(args) -> None:
    content_path = str(Path(args.content).resolve())
    data = json.loads(Path(content_path).read_text(encoding="utf-8"))
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    bad = [c for c in channels if c not in CHANNELS]
    if bad:
        sys.exit(f"알 수 없는 채널: {bad} (가능: {', '.join(CHANNELS)})")
    at = None
    if args.at:
        tz = ZoneInfo(load_json("schedule.json")["timezone"])
        at = datetime.strptime(args.at, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    conn = connect()
    for ch in channels:
        post_id = add_post(conn, data["product"]["product_id"], ch, content_path, scheduled_at=at)
        print(f"✔ #{post_id} {ch} {'예약 ' + args.at if at else '승인 → 다음 빈 슬롯에 자동 배정'}")
    if not at:
        from scheduler import assign_slots
        assign_slots(conn)
        cmd_list(argparse.Namespace(all=False), conn)


def cmd_list(args, conn=None) -> None:
    conn = conn or connect()
    tz = ZoneInfo(load_json("schedule.json")["timezone"])
    where = "" if args.all else "WHERE status NOT IN ('posted')"
    rows = conn.execute(f"SELECT * FROM posts {where} ORDER BY COALESCE(scheduled_at, created_at)").fetchall()
    if is_emergency_stopped(conn):
        print("🛑 긴급 정지 중 (python main.py resume 으로 해제)")
    print(f"{'ID':>4}  {'채널':<9} {'상태':<13} {'예약 시각':<16} 상품ID / 결과")
    for r in rows:
        when = parse_iso(r["scheduled_at"]).astimezone(tz).strftime("%m-%d %H:%M") if r["scheduled_at"] else "-"
        extra = r["posted_url"] or r["error"] or ""
        print(f"{r['id']:>4}  {r['channel']:<9} {r['status']:<13} {when:<16} {r['product_id']} {extra}")


def cmd_mark_posted(args) -> None:
    conn = connect()
    update_post(conn, args.id, status="posted", posted_url=args.url, posted_at=iso(utcnow()), error=None)
    print(f"✔ #{args.id} 게시 완료로 기록")


def cmd_retry(args) -> None:
    conn = connect()
    update_post(conn, args.id, status="approved", retry_count=0, error=None, slot_at=None, scheduled_at=None)
    from scheduler import assign_slots
    assign_slots(conn)
    print(f"✔ #{args.id} 재배정")


def cmd_cancel(args) -> None:
    conn = connect()
    conn.execute("DELETE FROM posts WHERE id = ? AND status NOT IN ('posted', 'posting')", (args.id,))
    conn.commit()
    print(f"✔ #{args.id} 취소")


def cmd_stop(args) -> None:
    set_setting(connect(), "emergency_stop", "1")
    print("🛑 긴급 정지: 모든 예약 게시가 중단됩니다.")


def cmd_resume(args) -> None:
    set_setting(connect(), "emergency_stop", "0")
    print("▶ 예약 게시 재개")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="쿠팡 파트너스 SNS 자동화")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="쿠팡 링크 → 원고·카드뉴스(·영상) 생성")
    g.add_argument("url", help="파트너스 추적 링크(link.coupang.com/a/...) 또는 쿠팡 상품 링크")
    g.add_argument("--affiliate-url", help="파트너스 사이트에서 만든 추적 링크 (url에 상품 링크를 넣었을 때)")
    g.add_argument("--product-id", help="상품 ID 직접 지정 (선택)")
    g.add_argument("--keyword", help="[API 모드] 검색 API로 상품 정보를 찾을 검색어 (상품명 일부)")
    g.add_argument("--name", help="상품명 (수동 모드 필수)")
    g.add_argument("--price", type=int, help="가격(원)")
    g.add_argument("--image", help="상품 사진 URL 또는 내 PC의 이미지 파일 경로")
    g.add_argument("--discount", type=int); g.add_argument("--category")
    g.add_argument("--no-images", action="store_true"); g.add_argument("--video", action="store_true")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("show", help="원고 미리보기"); s.add_argument("content"); s.set_defaults(func=cmd_show)

    a = sub.add_parser("approve", help="검수 완료 → 게시 대기열 등록")
    a.add_argument("content"); a.add_argument("--channels", default="threads,blog")
    a.add_argument("--at", help='직접 예약 시각 "YYYY-MM-DD HH:MM" (생략하면 자동 슬롯)')
    a.set_defaults(func=cmd_approve)

    l = sub.add_parser("list", help="게시 대기열"); l.add_argument("--all", action="store_true"); l.set_defaults(func=cmd_list)

    for name, func in (("mark-posted", cmd_mark_posted), ("retry", cmd_retry), ("cancel", cmd_cancel)):
        c = sub.add_parser(name); c.add_argument("id", type=int)
        if name == "mark-posted":
            c.add_argument("--url")
        c.set_defaults(func=func)

    sub.add_parser("stop", help="긴급 정지").set_defaults(func=cmd_stop)
    sub.add_parser("resume", help="긴급 정지 해제").set_defaults(func=cmd_resume)

    def _run(_): from scheduler import run_forever; run_forever()
    def _tick(_): from scheduler import tick; tick()
    sub.add_parser("run", help="스케줄러 상시 실행").set_defaults(func=_run)
    sub.add_parser("tick", help="슬롯 배정 + 게시 1회 실행").set_defaults(func=_tick)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
