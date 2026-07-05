from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os
from typing import Any

import requests


def _get_env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def telegram_enabled() -> bool:
    enabled_raw = _get_env("TELEGRAM_ALERTS_ENABLED", "1").lower()
    enabled = enabled_raw not in {"0", "false", "no", "off", ""}
    token = _get_env("TELEGRAM_BOT_TOKEN")
    chat_id = _get_env("TELEGRAM_CHAT_ID")
    return enabled and bool(token) and bool(chat_id)


def send_telegram_message(message: str, parse_mode: str | None = None, disable_notification: bool = False) -> bool:
    token = _get_env("TELEGRAM_BOT_TOKEN")
    chat_id = _get_env("TELEGRAM_CHAT_ID")

    enabled_raw = _get_env("TELEGRAM_ALERTS_ENABLED", "1").lower()
    enabled = enabled_raw not in {"0", "false", "no", "off", ""}

    if not enabled or not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": str(message),
        "disable_notification": bool(disable_notification),
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


