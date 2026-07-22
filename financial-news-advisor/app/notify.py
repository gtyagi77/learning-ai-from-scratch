"""Proactive push channels for the daily digest.

Two independent, best-effort channels -- a broken/unconfigured one never
blocks the other, same convention as the rest of this codebase (e.g.
yahoo_session's crumb handshake, instruments.load_map):

  - Telegram: a direct bot message via the Bot API.
  - Hermes Agent (github.com/NousResearch/hermes-agent): a self-hosted
    agent that can relay a plain message to your configured home channel
    (WhatsApp/Telegram/etc.) through a deliver_only webhook route. This
    module only POSTs to that route -- the route itself is configured on
    your own Hermes instance (see README).
"""

import hashlib
import hmac
import json
import logging
import time
from typing import List

import requests

from . import config

log = logging.getLogger("notify")

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(text: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    try:
        resp = requests.post(
            _TELEGRAM_URL.format(token=config.TELEGRAM_BOT_TOKEN),
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning("telegram send failed: %s", exc)
        return False


def send_hermes(text: str) -> bool:
    if not (config.HERMES_WEBHOOK_URL and config.HERMES_WEBHOOK_SECRET):
        return False
    body = json.dumps({"text": text}, separators=(",", ":"))
    ts = str(int(time.time()))
    signature = hmac.new(
        config.HERMES_WEBHOOK_SECRET.encode(),
        f"{ts}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        resp = requests.post(
            config.HERMES_WEBHOOK_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature-V2": f"sha256={signature}",
                "X-Webhook-Timestamp": ts,
            },
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning("hermes send failed: %s", exc)
        return False


def send_digest(text: str) -> List[str]:
    """Fire every configured channel independently; return the names of
    the ones that succeeded (empty list if none configured/all failed)."""
    sent = []
    if send_telegram(text):
        sent.append("telegram")
    if send_hermes(text):
        sent.append("hermes")
    return sent
