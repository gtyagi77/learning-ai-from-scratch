"""Company financials facade: screener.in first, Yahoo fallback, cached.

Normalized schema (every field optional — scorers handle absence):
  source            "screener" | "yahoo"
  annual            {sales: [...], net_profit: [...], opm_pct: [...], eps: [...]}
                    (oldest -> newest, ~10 years, from screener P&L)
  quarterly         {sales: [...], net_profit: [...]}  (~12 quarters)
  roe_pct, roce_pct, debt_to_equity, stock_pe, book_value
  rev_cagr_3y_pct, profit_cagr_3y_pct    (YoY fallback when CAGR undefined)
  opm_trend_pp      latest OPM minus 3y average, percentage points
  q_sales_yoy_pct   latest quarter sales vs same quarter last year
  pros, cons        screener's analysis bullets

Caching: financials_cache SQLite table, 24h TTL, stale-served when a
refresh fails. get_financials(..., allow_fetch=False) is cache-only — the
universe scan uses it so a 100+ symbol sweep never triggers a crawl.
"""

import logging
import math
import time
from typing import Dict, List, Optional

import requests

from . import config, database, screener

log = logging.getLogger("financials")

CACHE_TTL_SECONDS = 24 * 3600

_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"


def _cagr_pct(series: List[float], intervals: int = 3) -> Optional[float]:
    """CAGR over the last `intervals` steps; YoY fallback; None when the
    endpoints are non-positive (CAGR undefined, e.g. loss years)."""
    vals = [v for v in (series or []) if v is not None]
    if len(vals) >= intervals + 1 and vals[-1 - intervals] > 0 and vals[-1] > 0:
        return round((
            (vals[-1] / vals[-1 - intervals]) ** (1.0 / intervals) - 1) * 100, 1)
    if len(vals) >= 2 and vals[-2] > 0 and vals[-1] > 0:
        return round((vals[-1] / vals[-2] - 1) * 100, 1)
    return None


def _derive(payload: Dict) -> Dict:
    annual = payload.get("annual") or {}
    quarterly = payload.get("quarterly") or {}

    rev = _cagr_pct(annual.get("sales") or [])
    if rev is not None:
        payload["rev_cagr_3y_pct"] = rev
    prof = _cagr_pct(annual.get("net_profit") or [])
    if prof is not None:
        payload["profit_cagr_3y_pct"] = prof

    opm = [v for v in (annual.get("opm_pct") or []) if v is not None]
    if len(opm) >= 4:
        payload["opm_trend_pp"] = round(opm[-1] - sum(opm[-4:-1]) / 3, 1)

    q_sales = [v for v in (quarterly.get("sales") or []) if v is not None]
    if len(q_sales) >= 5 and q_sales[-5] > 0:
        payload["q_sales_yoy_pct"] = round((q_sales[-1] / q_sales[-5] - 1) * 100, 1)
    return payload


def _yahoo_financials(symbol: str) -> Optional[Dict]:
    """Fallback: quoteSummary financialData — no history, just ratios."""
    try:
        resp = requests.get(
            _SUMMARY_URL.format(symbol=symbol),
            params={"modules": "financialData,defaultKeyStatistics"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        modules = resp.json()["quoteSummary"]["result"][0]
    except Exception as exc:
        log.debug("yahoo financials %s failed: %s", symbol, exc)
        return None

    def raw(module: str, field: str):
        try:
            return modules[module][field]["raw"]
        except (KeyError, TypeError):
            return None

    out: Dict = {}
    roe = raw("financialData", "returnOnEquity")
    if roe is not None:
        out["roe_pct"] = round(roe * 100, 1)
    dte = raw("financialData", "debtToEquity")  # Yahoo reports percent
    if dte is not None:
        out["debt_to_equity"] = round(dte / 100, 2)
    rev_g = raw("financialData", "revenueGrowth")
    if rev_g is not None:
        out["rev_cagr_3y_pct"] = round(rev_g * 100, 1)  # YoY proxy
    earn_g = raw("financialData", "earningsGrowth")
    if earn_g is not None:
        out["profit_cagr_3y_pct"] = round(earn_g * 100, 1)
    margins = raw("financialData", "profitMargins")
    if margins is not None:
        out["profit_margin_pct"] = round(margins * 100, 1)
    return out or None


def _fetch(ticker: str) -> Optional[Dict]:
    payload = None
    source = None
    if screener.slug_for(ticker):
        payload = screener.get_company(ticker)
        source = "screener" if payload else None
    if payload is None:
        payload = _yahoo_financials(ticker)
        source = "yahoo" if payload else None
    if payload is None:
        return None
    payload = _derive(dict(payload))
    payload["source"] = source
    return payload


def get_financials(ticker: str, allow_fetch: bool = True) -> Optional[Dict]:
    ticker = ticker.upper()
    cached = database.get_cached_financials(ticker)
    now = time.time()

    if cached and now - cached["fetched_ts"] < CACHE_TTL_SECONDS:
        return cached["payload"] or None  # {} = cached negative result

    if not allow_fetch:
        return (cached or {}).get("payload") or None  # stale-serve or None

    payload = _fetch(ticker)
    if payload is None:
        if cached and cached["payload"]:
            return cached["payload"]  # stale-serve on refresh failure
        # negative-cache so unknown symbols aren't hammered
        database.put_cached_financials(ticker, "none", {})
        return None

    database.put_cached_financials(ticker, payload["source"], payload)
    return payload
