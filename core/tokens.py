"""채널 액세스 토큰 저장/조회. 갱신된 토큰은 DB에 Fernet 암호화로 저장한다."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from cryptography.fernet import Fernet

from core.config import env
from core.db import iso, utcnow

ENV_KEYS = {
    "threads": ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN"),
    "instagram": ("INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN"),
}


def _fernet() -> Fernet:
    key = env("TOKEN_ENCRYPTION_KEY", required=True)
    return Fernet(key.encode())


def save_token(conn: sqlite3.Connection, channel: str, user_id: str, token: str,
               expires_at: datetime | None) -> None:
    encrypted = _fernet().encrypt(token.encode()).decode()
    conn.execute(
        "INSERT INTO accounts(channel, user_id, token_encrypted, token_expires_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?) ON CONFLICT(channel) DO UPDATE SET "
        "user_id = excluded.user_id, token_encrypted = excluded.token_encrypted, "
        "token_expires_at = excluded.token_expires_at, updated_at = excluded.updated_at",
        (channel, user_id, encrypted, iso(expires_at) if expires_at else None, iso(utcnow())),
    )
    conn.commit()


def get_credentials(conn: sqlite3.Connection, channel: str) -> tuple[str, str]:
    """(user_id, access_token). DB에 갱신된 토큰이 있으면 우선, 없으면 .env 값."""
    row = conn.execute(
        "SELECT user_id, token_encrypted FROM accounts WHERE channel = ?", (channel,)
    ).fetchone()
    if row and row["token_encrypted"] and env("TOKEN_ENCRYPTION_KEY"):
        return row["user_id"], _fernet().decrypt(row["token_encrypted"].encode()).decode()
    user_key, token_key = ENV_KEYS[channel]
    return env(user_key, required=True), env(token_key, required=True)
