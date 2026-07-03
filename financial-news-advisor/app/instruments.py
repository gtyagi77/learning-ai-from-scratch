"""Symbol -> broker instrument-id maps for the quote providers.

Upstox and Angel One address instruments by internal ids, not "RELIANCE.NS".
Both publish their full instrument lists publicly, so the map can be built
without credentials. Resolution order used by app/prices.py:

  1. INSTRUMENT_MAP_PATH env var -> a JSON file you generated with
     scripts/build_instrument_map.py (fast, offline).
  2. instruments.json next to the project root, if present.
  3. Auto-download from the broker's public list on first use (needs
     outbound network; cached in memory for the process lifetime).

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


def download_map(provider: str) -> Dict[str, str]:
    """Fetch the broker's public instrument list and build the symbol map."""
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
