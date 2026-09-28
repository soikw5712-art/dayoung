"""Threads API 게시: 본문(텍스트) 게시 → 첫 답글로 파트너스 링크."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import requests

from core.db import utcnow
from core.tokens import get_credentials, save_token
from publishers.base import PublishError, PublishResult

GRAPH = "https://graph.threads.net/v1.0"


def _post(path: str, params: dict) -> dict:
    resp = requests.post(f"{GRAPH}/{path}", data=params, timeout=30)
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or "error" in data:
        raise PublishError(f"Threads API 오류 ({resp.status_code}): {data.get('error', data)}")
    return data


def _publish_text(user_id: str, token: str, text: str, reply_to: str | None = None) -> str:
    params = {"media_type": "TEXT", "text": text, "access_token": token}
    if reply_to:
        params["reply_to_id"] = reply_to
    container = _post(f"{user_id}/threads", params)["id"]
    return _post(f"{user_id}/threads_publish", {"creation_id": container, "access_token": token})["id"]


def publish(conn: sqlite3.Connection, post: sqlite3.Row, content: dict) -> PublishResult:
    user_id, token = get_credentials(conn, "threads")
    threads = content["threads"]
    media_id = _publish_text(user_id, token, threads["body"])
    if threads.get("reply"):
        _publish_text(user_id, token, threads["reply"], reply_to=media_id)

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
