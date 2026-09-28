"""환경변수(.env)와 config/*.json 로딩."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")

DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name) or default
    if required and not value:
        raise RuntimeError(f".env에 {name} 값이 없습니다. .env.example을 참고하세요.")
    return value


def load_json(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def output_dir() -> Path:
    path = ROOT / env("OUTPUT_DIR", "output")
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return ROOT / env("DB_PATH", "db.sqlite")
