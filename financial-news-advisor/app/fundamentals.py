"""Valuation inputs per ticker: price history stats + fundamental ratios.

Two sources, both best-effort:
  - Yahoo's chart endpoint (1y daily closes, keyless, reliable): 52-week
    range position and the 200-day moving average gap.
  - Yahoo's quoteSummary endpoint (trailing/forward P/E, analyst mean
    target): frequently gated behind cookies/crumbs, so treated as a bonus —
    every field degrades to None and the recommender scores whatever is
    available.

Results are cached for 6 hours; fundamentals move slowly.
"""

import logging
import threading
import time
from typing import Dict, Optional

import requests

from . import config

log = logging.getLogger("fundamentals")

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"

CACHE_TTL_SECONDS = 6 * 3600

_cache: Dict[str, tuple] = {}
_lock = threading.Lock()


def get_fundamentals(symbol: str) -> Optional[Dict]:
    """Return valuation inputs for symbol, or None when nothing resolves.

    Keys (any may be None): price, currency, high52, low52, pos52 (0..1,
    0 = at 52w low), dma200, dma_gap_pct, trailing_pe, forward_pe,
    target_mean.
    """
    symbol = symbol.upper()
    now = time.time()
    with _lock:
        cached = _cache.get(symbol)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    data = _fetch(symbol)
    with _lock:
        _cache[symbol] = (now, data)
    return data


def _fetch(symbol: str) -> Optional[Dict]:
    out: Dict = {}

    try:
        resp = requests.get(
            _CHART_URL.format(symbol=symbol),
            params={"range": "1y", "interval": "1d"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        meta = result["meta"]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        price = meta.get("regularMarketPrice")
        if price and len(closes) >= 60:
            high52, low52 = max(closes), min(closes)
            out["price"] = float(price)
            out["currency"] = meta.get("currency", "INR")
            out["high52"], out["low52"] = round(high52, 2), round(low52, 2)
            out["pos52"] = round((price - low52) / (high52 - low52), 3) if high52 > low52 else None
            window = closes[-200:]
            dma = sum(window) / len(window)
            out["dma200"] = round(dma, 2)
            out["dma_gap_pct"] = round((price - dma) / dma * 100, 2)
    except Exception as exc:
        log.debug("chart fundamentals %s failed: %s", symbol, exc)

    try:
        resp = requests.get(
            _SUMMARY_URL.format(symbol=symbol),
            params={"modules": "summaryDetail,financialData,defaultKeyStatistics"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        modules = resp.json()["quoteSummary"]["result"][0]

        def raw(module: str, field: str):
            try:
                return modules[module][field]["raw"]
            except (KeyError, TypeError):
                return None

        out["trailing_pe"] = raw("summaryDetail", "trailingPE")
        out["forward_pe"] = (raw("summaryDetail", "forwardPE")
                             or raw("defaultKeyStatistics", "forwardPE"))
        out["target_mean"] = raw("financialData", "targetMeanPrice")
    except Exception as exc:
        log.debug("quoteSummary %s failed: %s", symbol, exc)

    return out or None
