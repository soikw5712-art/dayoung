"""Instagram Graph API 캐러셀 게시 (7주차 구현 예정 — 현재는 틀만).

사전 준비:
- 인스타 계정을 비즈니스/크리에이터로 전환하고 페이스북 페이지·Meta 앱과 연결
- 권한: instagram_basic, instagram_content_publish
- 이미지가 공개 URL이어야 함 → 카드뉴스를 R2/S3 등에 올리고 PUBLIC_MEDIA_BASE_URL 설정

구현 순서:
1. 이미지마다 POST /{ig-user-id}/media  (image_url, is_carousel_item=true) → 아이템 컨테이너 ID
2. POST /{ig-user-id}/media  (media_type=CAROUSEL, children=ID들, caption) → 캐러셀 컨테이너 ID
3. 컨테이너 status_code가 FINISHED 될 때까지 대기
4. POST /{ig-user-id}/media_publish (creation_id) → 게시물 ID
5. 릴스는 media_type=REELS, video_url 로 같은 흐름
"""
from __future__ import annotations

import sqlite3

from publishers.base import PublishResult


def publish(conn: sqlite3.Connection, post: sqlite3.Row, content: dict) -> PublishResult:
    raise NotImplementedError("인스타그램 게시는 아직 구현되지 않았습니다 (7주차).")
