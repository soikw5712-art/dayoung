"""HTML → PNG 캡처 (Playwright/Chromium). 카드뉴스와 영상 프레임이 공통으로 사용."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from core.config import env

BRAND = {
    "bg": "#FFF8F0",
    "ink": "#1F1A17",
    "accent": "#FF6B3D",
    "muted": "#7A6E66",
    "font": "'Pretendard', 'Noto Sans KR', 'Apple SD Gothic Neo', 'WenQuanYi Zen Hei', sans-serif",
}


def image_src(src: str | None) -> str | None:
    """내 PC 사진(file://)은 렌더링 페이지에서 막히므로 data URI로 넣는다. 웹 URL은 그대로."""
    if not src or not src.startswith("file://"):
        return src
    path = Path(unquote(urlparse(src).path))
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def render_pages(pages: list[str], out_paths: list[Path], width: int, height: int) -> list[Path]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # CHROMIUM_PATH: 이미 설치된 크롬/크로미움을 쓰고 싶을 때 (기본은 `playwright install chromium`)
        executable = env("CHROMIUM_PATH")
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        for html, path in zip(pages, out_paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            page.set_content(html, wait_until="networkidle")
            page.screenshot(path=str(path), full_page=False)
        browser.close()
    return out_paths
