"""Symbol -> broker instrument-id maps for the quote providers.

Upstox and Angel One address instruments by internal ids, not "RELIANCE.NS".
Both publish their full instrument lists publicly, so the map can be built
without credentials. Breeze is different: its per-symbol lookup
(get_names()) needs a live authenticated session (ICICI validates the
session token server-side), so its map can only be built with real
BREEZE_* credentials, one symbol at a time, scoped to the app's watch
universe rather than a bulk anonymous download. Resolution order used by
app/prices.py:

  1. INSTRUMENT_MAP_PATH env var -> a JSON file you generated with
     scripts/build_instrument_map.py (fast, offline).
  2. instruments.json next to the project root, if present.
  3. Auto-download from the broker's public list on first use (needs
     outbound network; cached in memory for the process lifetime). Not
     available for breeze -- see build_breeze_map's docstring.

Failure at every level is fine — the quote layer falls back to Yahoo.
"""

import gzip
import io
import json
import logging
import os
from typing import Dict, List

import requests

from . import config

log = logging.getLogger("instruments")

UPSTOX_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
ANGELONE_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MAP_PATH = os.path.join(_PROJECT_ROOT, "instruments.json")


def build_upstox_map(instruments: List[dict]) -> Dict[str, str]:
    """NSE equities from Upstox's instrument dump -> {SYMBOL.NS: instrument_key}."""
    out: Dict[str, str] = {}
    for row in instruments:
        segment = row.get("segment") or row.get("exchange", "")
        if segment != "NSE_EQ":
            continue
        # Upstox has used both spellings across versions of the dump.
        tradingsymbol = row.get("trading_symbol") or row.get("tradingsymbol")
        key = row.get("instrument_key")
        if tradingsymbol and key:
            out[f"{tradingsymbol.upper()}.NS"] = key
    return out


def build_angelone_map(instruments: List[dict]) -> Dict[str, str]:
    """NSE cash equities from Angel One's scrip master -> {SYMBOL.NS: token}."""
    out: Dict[str, str] = {}
    for row in instruments:
        if row.get("exch_seg") != "NSE":
            continue
        symbol = row.get("symbol", "")
        token = row.get("token")
        # Cash equities carry the "-EQ" series suffix.
        if symbol.endswith("-EQ") and token:
            out[f"{symbol[:-3].upper()}.NS"] = str(token)
    return out


def build_breeze_map(client, symbols: List[str]) -> Dict[str, str]:
    """{SYMBOL.NS: isec_stock_code} via Breeze's get_names(), one authenticated
    call per symbol -- unlike Upstox/Angel One there is no anonymous bulk
    list, so this is scoped to the given symbols (the app's watch universe)
    rather than every NSE equity."""
    out: Dict[str, str] = {}
    for sym in symbols:
        bare = sym.split(".")[0]
        try:
            result = client.get_names(exchange_code="NSE", stock_code=bare)
            code = (result or {}).get("isec_stock_code")
        except Exception as exc:
            log.debug("breeze get_names(%s) failed: %s", bare, exc)
            continue
        if code:
            out[f"{bare.upper()}.NS"] = code
    return out


def download_map(provider: str) -> Dict[str, str]:
    """Fetch the broker's public instrument list and build the symbol map."""
    if provider == "breeze":
        # No anonymous bulk list -- needs a live authenticated session.
        if not (config.BREEZE_API_KEY and config.BREEZE_API_SECRET
                and config.BREEZE_SESSION_TOKEN):
            return {}
        from breeze_connect import BreezeConnect
        from . import universe
        client = BreezeConnect(api_key=config.BREEZE_API_KEY)
        client.generate_session(api_secret=config.BREEZE_API_SECRET,
                                session_token=config.BREEZE_SESSION_TOKEN)
        symbols = {s for s in universe.watch_symbols() if s.endswith(".NS")}
        return build_breeze_map(client, sorted(symbols))
    url = UPSTOX_URL if provider == "upstox" else ANGELONE_URL
    resp = requests.get(url, timeout=120, headers={"User-Agent": config.USER_AGENT})
    resp.raise_for_status()
    raw = resp.content
    if url.endswith(".gz"):
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    instruments = json.loads(raw)
    builder = build_upstox_map if provider == "upstox" else build_angelone_map
    return builder(instruments)


def load_map(provider: str) -> Dict[str, str]:
    """Resolve the instrument map: env-var file, default file, else download."""
    path = os.environ.get("INSTRUMENT_MAP_PATH", "")
    if not path and os.path.exists(DEFAULT_MAP_PATH):
        path = DEFAULT_MAP_PATH
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return {k.upper(): str(v) for k, v in json.load(fh).items()}
        except Exception as exc:
            log.warning("could not read instrument map %s: %s", path, exc)
    try:
        mapping = download_map(provider)
        log.info("auto-built %s instrument map: %d symbols", provider, len(mapping))
        return mapping
    except Exception as exc:
        log.warning("could not auto-build %s instrument map: %s "
                    "(quotes will fall back to Yahoo)", provider, exc)
        return {}
