"""Live quote lookup with a pluggable provider.

Providers (selected by config.QUOTE_PROVIDER):
  - "yahoo"    : Yahoo Finance chart endpoint. Keyless, covers NSE/BSE/US in
                 one API, ~15 min delayed, unofficial. The zero-config default.
  - "upstox"   : Upstox market-quote API. Free, real-time NSE/BSE, official —
                 needs UPSTOX_ACCESS_TOKEN and an instrument-key map.
  - "angelone" : Angel One SmartAPI. Free, real-time, official — needs an API
                 key + access token and a symbol-token map.

Every provider returns the same shape — {price, previous_close, currency,
change_pct} or None — so the rest of the app is provider-agnostic. A broker
provider that is unconfigured or errors falls back to Yahoo, so the app keeps
working out of the box and only gets better when credentials are supplied.

Quotes are best-effort: when nothing resolves, the advisor still produces
recommendations, just without price targets.
"""

import logging
import threading
import time
from typing import Callable, Dict, Optional

import requests

from . import config, yahoo_session

log = logging.getLogger("prices")

Quote = Dict[str, object]

_cache: Dict[str, tuple] = {}  # symbol -> (fetched_at, quote-or-None)
_lock = threading.Lock()


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def get_quote(symbol: str) -> Optional[Quote]:
    """Return {price, previous_close, currency, change_pct} or None, cached."""
    symbol = symbol.upper()
    now = time.time()
    with _lock:
        cached = _cache.get(symbol)
        if cached and now - cached[0] < config.PRICE_CACHE_TTL_SECONDS:
            return cached[1]

    quote = _dispatch(symbol)
    with _lock:
        _cache[symbol] = (now, quote)
    return quote


def active_provider() -> str:
    """The provider actually in effect (a broker downgrades to 'yahoo' when
    it has no usable credentials)."""
    provider = config.QUOTE_PROVIDER
    if provider == "upstox" and not config.UPSTOX_ACCESS_TOKEN:
        return "yahoo"
    if provider == "angelone" and not (config.ANGELONE_API_KEY and config.ANGELONE_ACCESS_TOKEN):
        return "yahoo"
    return provider if provider in _PROVIDERS else "yahoo"


def _dispatch(symbol: str) -> Optional[Quote]:
    provider = active_provider()
    quote = _PROVIDERS[provider](symbol)
    # Broker providers fall back to Yahoo per-symbol on any miss (e.g. a US
    # ticker a broker can't price, or a symbol missing from the key map).
    if quote is None and provider != "yahoo":
        quote = _yahoo_quote(symbol)
    return quote


def _mk_quote(price, prev, currency) -> Optional[Quote]:
    if price is None:
        return None
    price = float(price)
    prev = float(prev) if prev else None
    change_pct = round((price - prev) / prev * 100, 2) if prev else None
    return {
        "price": round(price, 2),
        "previous_close": round(prev, 2) if prev else None,
        "currency": currency,
        "change_pct": change_pct,
    }


# --------------------------------------------------------------------------
# Yahoo Finance (default, keyless)
# --------------------------------------------------------------------------

_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _yahoo_quote(symbol: str) -> Optional[Quote]:
    try:
        resp = yahoo_session.get(
            _YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": "1d", "interval": "5m"},
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
    except Exception as exc:
        log.warning("yahoo quote %s failed: %s", symbol, exc)
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return _mk_quote(meta.get("regularMarketPrice"), prev, meta.get("currency", "USD"))


# --------------------------------------------------------------------------
# instrument-key / symbol-token maps for broker providers
# --------------------------------------------------------------------------
# Broker APIs address instruments by their own identifiers, not "RELIANCE.NS"
# (Upstox: instrument_key like "NSE_EQ|INE002A01018"; Angel One: a numeric
# symboltoken). app/instruments.py resolves the map from INSTRUMENT_MAP_PATH,
# a local instruments.json, or an automatic download of the broker's public
# list — see that module. Loaded lazily, once per process.

_instrument_map: Optional[Dict[str, str]] = None


def _load_instrument_map() -> Dict[str, str]:
    global _instrument_map
    if _instrument_map is None:
        from . import instruments
        _instrument_map = instruments.load_map(config.QUOTE_PROVIDER)
    return _instrument_map


# --------------------------------------------------------------------------
# Upstox (free, real-time NSE/BSE)
# --------------------------------------------------------------------------

_UPSTOX_URL = "https://api.upstox.com/v2/market-quote/quotes"


def _upstox_quote(symbol: str) -> Optional[Quote]:
    key = _load_instrument_map().get(symbol)
    if not key or not config.UPSTOX_ACCESS_TOKEN:
        return None  # -> caller falls back to Yahoo
    try:
        resp = requests.get(
            _UPSTOX_URL,
            params={"instrument_key": key},
            headers={
                "Authorization": f"Bearer {config.UPSTOX_ACCESS_TOKEN}",
                "Accept": "application/json",
            },
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # Response is keyed like "NSE_EQ:RELIANCE"; take the single entry.
        entry = next(iter(data.values()))
    except Exception as exc:
        log.debug("upstox quote %s failed: %s", symbol, exc)
        return None
    ohlc = entry.get("ohlc") or {}
    return _mk_quote(entry.get("last_price"), ohlc.get("close"), "INR")


# --------------------------------------------------------------------------
# Angel One SmartAPI (free, real-time)
# --------------------------------------------------------------------------

_ANGELONE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData"


def _angelone_quote(symbol: str) -> Optional[Quote]:
    token = _load_instrument_map().get(symbol)
    if not token or not (config.ANGELONE_API_KEY and config.ANGELONE_ACCESS_TOKEN):
        return None  # -> caller falls back to Yahoo
    trading_symbol = symbol.split(".")[0] + "-EQ"
    try:
        resp = requests.post(
            _ANGELONE_URL,
            json={"exchange": "NSE", "tradingsymbol": trading_symbol, "symboltoken": token},
            headers={
                "Authorization": f"Bearer {config.ANGELONE_ACCESS_TOKEN}",
                "X-PrivateKey": config.ANGELONE_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-SourceID": "WEB",
                "X-UserType": "USER",
            },
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        d = resp.json()["data"]
    except Exception as exc:
        log.debug("angelone quote %s failed: %s", symbol, exc)
        return None
    return _mk_quote(d.get("ltp"), d.get("close"), "INR")


_PROVIDERS: Dict[str, Callable[[str], Optional[Quote]]] = {
    "yahoo": _yahoo_quote,
    "upstox": _upstox_quote,
    "angelone": _angelone_quote,
}
