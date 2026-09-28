"""카드뉴스 3~5장 (1080×1350) 자동 생성.

상품 사진은 파트너스 API가 준 실제 대표 이미지를 그대로 쓴다 (AI로 상품을 새로 그리지 않음).
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from generators.render import BRAND, render_pages

WIDTH, HEIGHT = 1080, 1350

BASE_CSS = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: {WIDTH}px; height: {HEIGHT}px; background: {BRAND['bg']}; color: {BRAND['ink']};
       font-family: {BRAND['font']}; overflow: hidden; }}
.card {{ width: 100%; height: 100%; padding: 96px 88px; display: flex; flex-direction: column; }}
.tag {{ color: {BRAND['accent']}; font-size: 34px; font-weight: 700; letter-spacing: 2px; }}
.title {{ font-size: 76px; font-weight: 800; line-height: 1.25; margin-top: 28px; word-break: keep-all; }}
.body {{ font-size: 58px; font-weight: 700; line-height: 1.45; word-break: keep-all; white-space: pre-line; }}
.photo {{ flex: 1; margin-top: 48px; border-radius: 36px; background: #fff center / contain no-repeat; }}
.center {{ justify-content: center; }}
.num {{ color: {BRAND['accent']}; font-size: 120px; font-weight: 900; margin-bottom: 36px; }}
.price {{ font-size: 110px; font-weight: 900; color: {BRAND['accent']}; margin: 24px 0; }}
.note {{ font-size: 32px; color: {BRAND['muted']}; margin-top: auto; line-height: 1.5; }}
.footer {{ font-size: 30px; color: {BRAND['muted']}; margin-top: auto; }}
"""


def _page(inner: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{BASE_CSS}</style></head><body>{inner}</body></html>"


def _lines(text: str) -> str:
    return escape(text).replace("\n", "<br>")


def build_cards(data: dict) -> list[str]:
    product = data["product"]
    texts: list[str] = data["card_texts"]
    image = product.get("image_url")
    cards = []

    # 1. 표지: 후킹 문구 + 실제 상품 이미지
    photo = f"<div class='photo' style=\"background-image:url('{escape(image)}')\"></div>" if image else ""
    cards.append(_page(f"<div class='card'><div class='tag'>오늘의 살림템</div>"
                       f"<div class='title'>{_lines(texts[0])}</div>{photo}</div>"))

    # 2~(n-1). 특징
    middle = texts[1:-1] if len(texts) > 2 else texts[1:]
    for i, text in enumerate(middle, start=1):
        cards.append(_page(f"<div class='card center'><div class='num'>0{i}</div>"
                           f"<div class='body'>{_lines(text)}</div></div>"))

    # 가격 카드 (가격 정보가 있을 때만)
    if product.get("price"):
        cards.append(_page(
            "<div class='card center'><div class='tag'>가격</div>"
            f"<div class='price'>{product['price']:,}원</div>"
            f"<div class='body' style='font-size:44px'>{_lines(product['name'])}</div>"
            "<div class='note'>* 게시 시점 기준 가격이며 변동될 수 있어요</div></div>"))

    # 마지막: 추천 대상 / 마무리 + 고지
    if len(texts) > 2:
        cards.append(_page(f"<div class='card center'><div class='body'>{_lines(texts[-1])}</div>"
                           "<div class='footer'>이 포스팅은 쿠팡 파트너스 활동의 일환으로,<br>"
                           "이에 따른 일정액의 수수료를 제공받습니다.</div></div>"))
    return cards


def generate_cards(content_path: Path) -> list[Path]:
    data = json.loads(Path(content_path).read_text(encoding="utf-8"))
    pages = build_cards(data)
    folder = Path(content_path).parent / "images"
    paths = [folder / f"card_{i:02d}.png" for i in range(1, len(pages) + 1)]
    return render_pages(pages, paths, WIDTH, HEIGHT)
