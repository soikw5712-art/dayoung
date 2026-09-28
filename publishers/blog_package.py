"""네이버 블로그 원고 패키지 생성 (반자동).

네이버 블로그 글쓰기 API는 종료됐고 매크로 게시는 약관 위반이라,
원고 패키지를 만들어 알림 → 스마트에디터에 붙여넣고 네이버 예약발행으로 직접 등록한다.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import output_dir
from publishers.base import PublishResult


def build_body(content: dict, image_names: list[str]) -> str:
    blog = content["blog"]
    parts = [blog["disclosure"], ""]
    images = iter(image_names)
    first = next(images, None)
    if first:
        parts += [f"[이미지: {first}]", ""]
    for section in blog["sections"]:
        parts += [f"■ {section['heading']}", "", section["text"].strip(), ""]
        img = next(images, None)
        if img:
            parts += [f"[이미지: {img}]", ""]
    parts += ["▶ 상품 보러가기", blog["link"], "", "※ 가격은 게시 시점 기준이며 변동될 수 있습니다."]
    return "\n".join(parts)


def make_package(post_id: int, content_path: Path, content: dict, base: Path | None = None) -> Path:
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    folder = (base or output_dir()) / "blog" / today / f"{post_id}_{content['product']['product_id']}"
    image_dir = folder / "이미지"
    image_dir.mkdir(parents=True, exist_ok=True)

    names = []
    for i, src in enumerate(sorted((Path(content_path).parent / "images").glob("*.png")), start=1):
        name = f"{i:02d}.png"
        shutil.copy(src, image_dir / name)
        names.append(name)

    (folder / "제목.txt").write_text(content["blog"]["title"], encoding="utf-8")
    (folder / "본문.txt").write_text(build_body(content, names), encoding="utf-8")
    (folder / "태그.txt").write_text(" ".join(f"#{t.lstrip('#')}" for t in content["blog"]["tags"]), encoding="utf-8")
    return folder


def publish(conn: sqlite3.Connection, post: sqlite3.Row, content: dict) -> PublishResult:
    folder = make_package(post["id"], Path(post["content_path"]), content)
    return PublishResult(status="package_ready", url=str(folder))
