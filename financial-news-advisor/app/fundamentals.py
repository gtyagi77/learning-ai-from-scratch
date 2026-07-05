"""Valuation inputs per ticker: price history stats + fundamental ratios.

Two sources, both best-effort, both fetched through yahoo_session's shared
crumb/cookie session (Yahoo requires a crumb handshake for non-browser
clients on these endpoints; see app/yahoo_session.py):
  - Yahoo's chart endpoint: 1y daily closes, 52-week range position, the
    200-day moving average gap.
  - Yahoo's quoteSummary endpoint (trailing/forward P/E, analyst mean
    target): treated as a bonus even with a crumb — every field degrades
    to None and the recommender scores whatever is available.

Results are cached for 6 hours; fundamentals move slowly.
"""

import logging
import threading
import time
from typing import Dict, Optional

from . import yahoo_session

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


def get_history(symbol: str, range_: str = "1y") -> Optional[Dict]:
    """Daily close history + moving averages, for stats and charting.
    Returns {price, currency, timestamps, closes, dma50, dma200} or None."""
    try:
        resp = yahoo_session.get(
            _CHART_URL.format(symbol=symbol),
            params={"range": range_, "interval": "1d"},
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        meta = result["meta"]
        raw_ts = result.get("timestamp") or []
        raw_closes = result["indicators"]["quote"][0]["close"] or []
        pairs = [(t, c) for t, c in zip(raw_ts, raw_closes) if c is not None]
        if not pairs:
            return None
        timestamps = [p[0] for p in pairs]
        closes = [round(float(p[1]), 2) for p in pairs]
        price = meta.get("regularMarketPrice") or closes[-1]

        def rolling(n: int):
            if len(closes) < n // 2:
                return None
            out = []
            for i in range(len(closes)):
                window = closes[max(0, i - n + 1):i + 1]
                out.append(round(sum(window) / len(window), 2))
            return out

        return {
            "price": round(float(price), 2),
            "currency": meta.get("currency", "INR"),
            "timestamps": timestamps,
            "closes": closes,
            "dma50": rolling(50),
            "dma200": rolling(200),
        }
    except Exception as exc:
        log.warning("history %s failed: %s", symbol, exc)
        return None


def _fetch(symbol: str) -> Optional[Dict]:
    out: Dict = {}

    hist = get_history(symbol)
    if hist and len(hist["closes"]) >= 60:
        closes, price = hist["closes"], hist["price"]
        high52, low52 = max(closes), min(closes)
        out["price"] = price
        out["currency"] = hist["currency"]
        out["high52"], out["low52"] = round(high52, 2), round(low52, 2)
        out["pos52"] = round((price - low52) / (high52 - low52), 3) if high52 > low52 else None
        window = closes[-200:]
        dma = sum(window) / len(window)
        out["dma200"] = round(dma, 2)
        out["dma_gap_pct"] = round((price - dma) / dma * 100, 2)

    try:
        resp = yahoo_session.get(
            _SUMMARY_URL.format(symbol=symbol),
            params={"modules": "summaryDetail,financialData,defaultKeyStatistics"},
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
        out["target_high"] = raw("financialData", "targetHighPrice")
        out["target_low"] = raw("financialData", "targetLowPrice")
        # Street consensus: 1 = strong buy ... 5 = sell.
        out["analyst_rating"] = raw("financialData", "recommendationMean")
        out["analyst_count"] = raw("financialData", "numberOfAnalystOpinions")
    except Exception as exc:
        log.warning("quoteSummary %s failed: %s", symbol, exc)

    return out or None
