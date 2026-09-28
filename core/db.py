"""SQLite 저장소: 게시 대기열(posts), 설정(settings), 계정 토큰(accounts)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    TEXT NOT NULL,
    channel       TEXT NOT NULL,               -- threads | instagram | blog
    content_path  TEXT NOT NULL,               -- output/.../content.json
    slot_at       TEXT,                        -- 배정된 슬롯 (UTC ISO)
    scheduled_at  TEXT,                        -- 랜덤 지연 반영된 실제 실행 시각 (UTC ISO)
    status        TEXT NOT NULL DEFAULT 'approved',
    retry_count   INTEGER NOT NULL DEFAULT 0,
    posted_at     TEXT,
    posted_url    TEXT,
    error         TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status, scheduled_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    channel          TEXT PRIMARY KEY,
    user_id          TEXT,
    token_encrypted  TEXT,
    token_expires_at TEXT,
    updated_at       TEXT
);
"""

# 게시 상태 흐름:
# approved → scheduled → posting → posted
#                               └→ failed (재시도 초과) / held (하루 한도 초과)
# blog 는 posting → package_ready → (직접 예약발행 후 mark-posted) → posted
STATUSES = ("approved", "scheduled", "posting", "posted", "failed", "held", "package_ready")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def is_emergency_stopped(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "emergency_stop", "0") == "1"


def add_post(conn: sqlite3.Connection, product_id: str, channel: str, content_path: str,
             scheduled_at: datetime | None = None) -> int:
    """승인된 게시물을 대기열에 추가. scheduled_at을 주면 슬롯 배정 없이 그 시각으로 예약."""
    status = "scheduled" if scheduled_at else "approved"
    at = iso(scheduled_at) if scheduled_at else None
    cur = conn.execute(
        "INSERT INTO posts(product_id, channel, content_path, slot_at, scheduled_at, status, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (product_id, channel, content_path, at, at, status, iso(utcnow())),
    )
    conn.commit()
    return cur.lastrowid


def update_post(conn: sqlite3.Connection, post_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE posts SET {cols} WHERE id = ?", (*fields.values(), post_id))
    conn.commit()
