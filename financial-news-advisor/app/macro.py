"""Economic macro indicators and per-stock macro tilt.

Indicators (all via Yahoo's chart endpoint, the one dependable keyless API):
  nifty   ^NSEI      Indian market trend: 3-month return + 200-DMA position
  usdinr  INR=X      rupee: 3-month change (+ = rupee weakening)
  brent   BZ=F       crude: 3-month change (India is a net importer)
  vix     ^INDIAVIX  fear gauge: level vs a calm baseline

Each indicator gets a state in [-1, 1]; a stock's macro tilt is the clamped
weighted sum of states using its sector's sensitivity row
(universe.MACRO_SENSITIVITY) plus per-symbol overrides (upstream oil vs
OMCs). 30-minute cache; every failure degrades to "indicator missing".
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from . import config, universe

log = logging.getLogger("macro")

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
CACHE_TTL_SECONDS = 30 * 60

INDICATORS = {
    "nifty": ("^NSEI", "Nifty 50"),
    "usdinr": ("INR=X", "USD/INR"),
    "brent": ("BZ=F", "Brent crude"),
    "vix": ("^INDIAVIX", "India VIX"),
}

_cache: Dict[str, tuple] = {}
_lock = threading.Lock()


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _fetch_series(symbol: str) -> Optional[Dict]:
    try:
        resp = requests.get(
            _CHART_URL.format(symbol=symbol),
            params={"range": "1y", "interval": "1d"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        price = result["meta"].get("regularMarketPrice") or (closes[-1] if closes else None)
        if price is None or len(closes) < 70:
            return None
        return {"price": float(price), "closes": closes}
    except Exception as exc:
        log.debug("macro series %s failed: %s", symbol, exc)
        return None


def _indicator_state(key: str, series: Dict) -> Dict:
    price, closes = series["price"], series["closes"]
    # ~63 trading days = 3 months.
    base_3m = closes[-63] if len(closes) >= 63 else closes[0]
    chg_3m = (price - base_3m) / base_3m * 100 if base_3m else 0.0

    if key == "nifty":
        dma = sum(closes[-200:]) / len(closes[-200:])
        above = (price - dma) / dma * 100
        state = _clamp(0.6 * (chg_3m / 8.0) + 0.4 * (above / 8.0))
        label = (f"{'up' if chg_3m >= 0 else 'down'} {abs(chg_3m):.1f}% in 3m, "
                 f"{abs(above):.1f}% {'above' if above >= 0 else 'below'} 200-DMA")
    elif key == "usdinr":
        state = _clamp(chg_3m / 4.0)  # a 4% rupee move is a big deal
        label = (f"rupee {'weakened' if chg_3m >= 0 else 'strengthened'} "
                 f"{abs(chg_3m):.1f}% in 3m")
    elif key == "brent":
        state = _clamp(chg_3m / 20.0)
        label = f"crude {'up' if chg_3m >= 0 else 'down'} {abs(chg_3m):.1f}% in 3m"
    else:  # vix
        state = _clamp((price - 15.0) / 10.0)  # 15 = calm baseline
        label = f"India VIX at {price:.1f}"

    return {"level": round(price, 2), "chg_3m_pct": round(chg_3m, 2),
            "state": round(state, 3), "label": label}


def get_indicators() -> Dict[str, Dict]:
    """{key: {name, level, chg_3m_pct, state, label}} for available data."""
    now = time.time()
    with _lock:
        cached = _cache.get("indicators")
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    out: Dict[str, Dict] = {}
    for key, (symbol, name) in INDICATORS.items():
        series = _fetch_series(symbol)
        if series:
            state = _indicator_state(key, series)
            state["name"] = name
            state["symbol"] = symbol
            out[key] = state

    with _lock:
        _cache["indicators"] = (now, out)
    return out


def sensitivity_for(symbol: str) -> Dict[str, float]:
    sens = dict(universe.MACRO_SENSITIVITY.get(
        universe.sector_for(symbol), universe.MACRO_SENSITIVITY["Nifty 50"]))
    sens.update(universe.MACRO_SYMBOL_OVERRIDES.get(symbol.upper(), {}))
    return sens


def macro_tilt(symbol: str) -> Tuple[Optional[float], List[str]]:
    """(tilt in [-1,1] or None when no indicators resolve, notes)."""
    indicators = get_indicators()
    if not indicators:
        return None, []
    sens = sensitivity_for(symbol)
    tilt, notes = 0.0, []
    for key, ind in indicators.items():
        w = sens.get(key, 0.0)
        contrib = w * ind["state"]
        tilt += contrib
        if abs(contrib) >= 0.05:
            notes.append(f"{ind['name']}: {ind['label']} "
                         f"({'+' if contrib >= 0 else '−'}{abs(contrib):.2f})")
    return round(_clamp(tilt), 3), notes


def sector_tilts() -> Dict[str, float]:
    """Representative tilt per sector (using the sector's sensitivity row
    without symbol overrides) for the dashboard strip."""
    indicators = get_indicators()
    out = {}
    for sector, sens in universe.MACRO_SENSITIVITY.items():
        tilt = sum(sens.get(k, 0.0) * ind["state"] for k, ind in indicators.items())
        out[sector] = round(_clamp(tilt), 3) if indicators else None
    return out
