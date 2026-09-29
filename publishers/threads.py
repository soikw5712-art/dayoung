"""Threads API 게시: 본문 + 사진(1장=이미지, 2장 이상=캐러셀) + 토픽 태그 → 첫 답글로 파트너스 링크.

사진은 Threads 서버가 가져갈 수 있는 공개 URL이어야 한다.
PUBLIC_MEDIA_BASE_URL 에 output 폴더가 공개된 주소(R2/S3 등)를 넣으면
output/<폴더>/photos/photo_01.jpg → {PUBLIC_MEDIA_BASE_URL}/<폴더>/photos/photo_01.jpg 로 올린다.
설정이 없으면 사진 없이 글만 올리고 알림으로 알려준다.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import timedelta
from pathlib import Path

import requests

from core.config import env, output_dir
from core.db import utcnow
from core.tokens import get_credentials, save_token
from notifier import notify
from publishers.base import PublishError, PublishResult

GRAPH = "https://graph.threads.net/v1.0"
STATUS_POLL_SECONDS = 5
STATUS_POLL_TRIES = 12


def _post(path: str, params: dict) -> dict:
    resp = requests.post(f"{GRAPH}/{path}", data=params, timeout=30)
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or "error" in data:
        raise PublishError(f"Threads API 오류 ({resp.status_code}): {data.get('error', data)}")
    return data


def _wait_ready(container_id: str, token: str) -> None:
    """사진 컨테이너는 서버 처리 후(FINISHED) 게시해야 한다."""
    for _ in range(STATUS_POLL_TRIES):
        resp = requests.get(f"{GRAPH}/{container_id}",
                            params={"fields": "status,error_message", "access_token": token}, timeout=15)
        data = resp.json() if resp.content else {}
        status = data.get("status")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"Threads 미디어 처리 실패: {data.get('error_message', status)}")
        time.sleep(STATUS_POLL_SECONDS)
    raise PublishError("Threads 미디어 처리 대기 시간 초과")


def public_photo_urls(content_path: str, photos: list[str]) -> list[str]:
    base = (env("PUBLIC_MEDIA_BASE_URL") or "").rstrip("/")
    if not base or not photos:
        return []
    folder = Path(content_path).resolve().parent
    root = output_dir().resolve()
    return [f"{base}/{(folder / p).relative_to(root).as_posix()}" for p in photos]


def _create_container(user_id: str, token: str, text: str, image_urls: list[str],
                      topic_tag: str | None, reply_to: str | None) -> str:
    params = {"text": text, "access_token": token}
    if topic_tag:
        params["topic_tag"] = topic_tag
    if reply_to:
        params["reply_to_id"] = reply_to

    if not image_urls:
        params["media_type"] = "TEXT"
        return _post(f"{user_id}/threads", params)["id"]
    if len(image_urls) == 1:
        params.update(media_type="IMAGE", image_url=image_urls[0])
        container = _post(f"{user_id}/threads", params)["id"]
        _wait_ready(container, token)
        return container

    children = []
    for url in image_urls[:10]:
        item = _post(f"{user_id}/threads", {"media_type": "IMAGE", "image_url": url,
                                            "is_carousel_item": "true", "access_token": token})["id"]
        children.append(item)
    for item in children:
        _wait_ready(item, token)
    params.update(media_type="CAROUSEL", children=",".join(children))
    container = _post(f"{user_id}/threads", params)["id"]
    _wait_ready(container, token)
    return container


def _publish(user_id: str, token: str, container: str) -> str:
    return _post(f"{user_id}/threads_publish", {"creation_id": container, "access_token": token})["id"]


def publish(conn: sqlite3.Connection, post: sqlite3.Row, content: dict) -> PublishResult:
    user_id, token = get_credentials(conn, "threads")
    threads = content["threads"]
    photos = threads.get("photos") or []
    image_urls = public_photo_urls(post["content_path"], photos)
    if photos and not image_urls:
        notify(f"⚠️ 스레드 #{post['id']}: PUBLIC_MEDIA_BASE_URL 설정이 없어 사진 없이 글만 올립니다.")

    container = _create_container(user_id, token, threads["body"], image_urls, threads.get("topic_tag"), None)
    media_id = _publish(user_id, token, container)
    if threads.get("reply"):
        reply = _create_container(user_id, token, threads["reply"], [], None, media_id)
        _publish(user_id, token, reply)

    permalink = None
    resp = requests.get(f"{GRAPH}/{media_id}", params={"fields": "permalink", "access_token": token}, timeout=15)
    if resp.ok:
        permalink = resp.json().get("permalink")
    return PublishResult(status="posted", url=permalink or media_id)


def refresh_token(conn: sqlite3.Connection) -> None:
    """장기 토큰(60일) 갱신. 만료 전 주기적으로 호출."""
    user_id, token = get_credentials(conn, "threads")
    resp = requests.get(
        "https://graph.threads.net/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code != 200 or "access_token" not in data:
        raise PublishError(f"Threads 토큰 갱신 실패: {data}")
    expires = utcnow() + timedelta(seconds=int(data.get("expires_in", 0)))
    save_token(conn, "threads", user_id, data["access_token"], expires)
