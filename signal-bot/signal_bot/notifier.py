"""Telegram delivery. The bot token is read from the environment and never logged."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("signal_bot")


class NotifyError(RuntimeError):
    pass


def http_post_json(url: str, payload: dict, timeout: float = 15.0):
    """POST JSON, return (status, decoded body). Tests replace this function."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "algo-signal-bot/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise NotifyError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"  # contains the token: never log it
        self.chat_id = chat_id

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        return cls(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""))

    def send(self, text: str, retries: int = 3) -> None:
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        for attempt in range(retries):
            try:
                status, body = http_post_json(self._url, payload)
            except (urllib.error.URLError, TimeoutError) as e:
                log.warning("telegram network error (%s), attempt %d", type(e).__name__, attempt + 1)
                time.sleep(2 * (attempt + 1))
                continue
            if status == 200 and body.get("ok"):
                return
            if status == 429:
                wait = int(body.get("parameters", {}).get("retry_after", 5))
                log.warning("telegram rate limit, waiting %ds", wait)
                time.sleep(min(wait, 60))
                continue
            raise NotifyError(f"telegram rejected the message: HTTP {status} {body.get('description', '')}")
        raise NotifyError("telegram send failed after retries")


class ConsoleNotifier:
    """Dry-run: print instead of sending."""

    def send(self, text: str, retries: int = 3) -> None:
        print("-" * 40)
        print(text)
