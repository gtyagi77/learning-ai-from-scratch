"""Live quote lookup via Yahoo Finance's public chart endpoint, with caching.

Quotes are best-effort: when the endpoint is unreachable the advisor still
works, it just reports recommendations without price targets.
"""

import threading
import time
from typing import Dict, Optional

import requests

from . import config

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

_cache: Dict[str, tuple] = {}  # symbol -> (fetched_at, quote-or-None)
_lock = threading.Lock()


def get_quote(symbol: str) -> Optional[dict]:
    """Return {price, previous_close, currency, change_pct} or None."""
    symbol = symbol.upper()
    now = time.time()
    with _lock:
        cached = _cache.get(symbol)
        if cached and now - cached[0] < config.PRICE_CACHE_TTL_SECONDS:
            return cached[1]

    quote = _fetch_quote(symbol)
    with _lock:
        _cache[symbol] = (now, quote)
    return quote


def _fetch_quote(symbol: str) -> Optional[dict]:
    try:
        resp = requests.get(
            _CHART_URL.format(symbol=symbol),
            params={"range": "1d", "interval": "5m"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
    except Exception:
        return None

    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        return None
    change_pct = None
    if prev:
        change_pct = round((price - prev) / prev * 100, 2)
    return {
        "price": round(float(price), 2),
        "previous_close": round(float(prev), 2) if prev else None,
        "currency": meta.get("currency", "USD"),
        "change_pct": change_pct,
    }
