"""텔레그램 알림. 봇 토큰이 없으면 콘솔에만 출력."""
from __future__ import annotations

import logging

import requests

from core.config import env

log = logging.getLogger("notifier")


def notify(message: str) -> None:
    token, chat_id = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    log.info("[알림] %s", message)
    if not (token and chat_id):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        ).raise_for_status()
    except requests.RequestException as e:
        log.warning("텔레그램 전송 실패: %s", e)
