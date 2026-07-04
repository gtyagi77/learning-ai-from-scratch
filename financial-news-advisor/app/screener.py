"""Fetch and parse company fundamentals from screener.in public pages.

screener.in has no official API; this reads the logged-out public company
page (https://www.screener.in/company/{slug}/consolidated/). Scraping is a
grey area under their terms — the user chose this source knowingly, so the
client is deliberately gentle:

  - robots.txt is checked once per process; if /company/ is disallowed the
    module refuses to fetch and callers fall back to Yahoo.
  - Requests are paced >= REQUEST_SPACING_SECONDS apart (process-wide lock).
  - Results are cached for 24h in SQLite (app/financials.py owns the cache),
    so each ticker is fetched at most ~once per day.
  - 404s are negative-cached so unknown symbols aren't re-tried.

Parsing uses only the standard library (html.parser): the page is structured
as <section id="top-ratios|quarters|profit-loss|balance-sheet"> blocks with
<table class="data-table"> inside, plus pros/cons <ul> lists.
"""

import logging
import re
import threading
import time
import urllib.parse
import urllib.robotparser
from html.parser import HTMLParser
from typing import Dict, List, Optional

import requests

from . import config

log = logging.getLogger("screener")

BASE_URL = "https://www.screener.in"
REQUEST_SPACING_SECONDS = 1.5

# Yahoo base symbol -> screener slug, where they differ.
SLUG_OVERRIDES: Dict[str, str] = {
    "M&M": "M%26M",
    "BAJAJ-AUTO": "BAJAJ-AUTO",
    "ETERNAL": "ETERNAL",
}

_pace_lock = threading.Lock()
_last_request_ts = 0.0

_robots_checked = False
_robots_allowed = True


def _robots_ok() -> bool:
    """Check robots.txt once per process; disallow -> never fetch."""
    global _robots_checked, _robots_allowed
    if _robots_checked:
        return _robots_allowed
    try:
        rp = urllib.robotparser.RobotFileParser()
        resp = requests.get(f"{BASE_URL}/robots.txt",
                            headers={"User-Agent": config.USER_AGENT},
                            timeout=config.HTTP_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
            _robots_allowed = rp.can_fetch(config.USER_AGENT, f"{BASE_URL}/company/X/")
        else:
            _robots_allowed = True  # no robots.txt served
    except Exception as exc:
        log.debug("robots.txt check failed (%s); allowing cautiously", exc)
        _robots_allowed = True
    _robots_checked = True
    if not _robots_allowed:
        log.warning("screener.in robots.txt disallows /company/ — falling back to Yahoo")
    return _robots_allowed


def slug_for(symbol: str) -> Optional[str]:
    """Screener slug for a Yahoo symbol; None for non-Indian symbols."""
    symbol = symbol.upper()
    if not (symbol.endswith(".NS") or symbol.endswith(".BO")):
        return None
    base = symbol.rsplit(".", 1)[0]
    return SLUG_OVERRIDES.get(base, urllib.parse.quote(base, safe=""))


def fetch_page(symbol: str) -> Optional[str]:
    """Fetch the company page HTML (consolidated, falling back to
    standalone). None on any failure or when robots disallow."""
    slug = slug_for(symbol)
    if not slug or not _robots_ok():
        return None

    global _last_request_ts
    for variant in ("consolidated/", ""):
        with _pace_lock:
            wait = REQUEST_SPACING_SECONDS - (time.time() - _last_request_ts)
            if wait > 0:
                time.sleep(wait)
            _last_request_ts = time.time()
        try:
            resp = requests.get(
                f"{BASE_URL}/company/{slug}/{variant}",
                headers={"User-Agent": config.USER_AGENT,
                         "Accept": "text/html"},
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            html = resp.text
            # Consolidated pages of companies that report only standalone
            # numbers have empty P&L tables — retry the standalone variant.
            parsed = parse_company_page(html)
            if variant == "consolidated/" and not parsed.get("annual", {}).get("sales"):
                continue
            return html
        except Exception as exc:
            log.debug("screener fetch %s/%s failed: %s", slug, variant, exc)
            return None
    return None


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class _PageParser(HTMLParser):
    """Extracts data-tables per section, top ratios, and pros/cons lists."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.section: Optional[str] = None       # current <section id=...>
        self.tables: Dict[str, List[List[str]]] = {}  # section -> rows
        self.ratios_pairs: List[str] = []        # flat text chunks in #top-ratios
        self.pros: List[str] = []
        self.cons: List[str] = []
        self._in_table = False
        self._in_cell = False
        self._row: List[str] = []
        self._cell: List[str] = []
        self._list_kind: Optional[str] = None    # "pros" | "cons"
        self._in_li = False
        self._li_text: List[str] = []
        self._section_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and a.get("id") in (
                "top-ratios", "quarters", "profit-loss", "balance-sheet",
                "analysis", "ratios"):
            self.section = a["id"]
            self._section_depth = 1
        elif self.section and tag == "section":
            self._section_depth += 1
        if tag == "table" and self.section and "data-table" in a.get("class", ""):
            self._in_table = True
            self.tables.setdefault(self.section, [])
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
        elif self.section == "analysis" and tag == "div":
            cls = a.get("class", "")
            if "pros" in cls:
                self._list_kind = "pros"
            elif "cons" in cls:
                self._list_kind = "cons"
        elif tag == "li" and self._list_kind:
            self._in_li = True
            self._li_text = []
        elif tag == "ul" and self.section == "top-ratios":
            pass

    def handle_endtag(self, tag):
        if tag == "section" and self.section:
            self._section_depth -= 1
            if self._section_depth <= 0:
                self.section = None
                self._list_kind = None
        elif tag == "table":
            self._in_table = False
        elif self._in_table and tag == "tr":
            if any(c.strip() for c in self._row):
                self.tables[self.section].append([c.strip() for c in self._row])
            self._row = []
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._row.append(" ".join("".join(self._cell).split()))
        elif tag == "li" and self._in_li:
            self._in_li = False
            text = " ".join("".join(self._li_text).split())
            if text and self._list_kind == "pros":
                self.pros.append(text)
            elif text and self._list_kind == "cons":
                self.cons.append(text)
        elif tag == "div" and self._list_kind and not self._in_li:
            pass

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)
        elif self._in_li:
            self._li_text.append(data)
        elif self.section == "top-ratios":
            text = data.strip()
            if text:
                self.ratios_pairs.append(text)


_NUM_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")


def _num(text: str) -> Optional[float]:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _find_row(rows: List[List[str]], *aliases: str) -> Optional[List[float]]:
    """Find a table row whose first cell matches any alias (case-insensitive
    substring); return the numeric cells that follow."""
    for row in rows:
        if not row:
            continue
        label = row[0].lower()
        if any(alias.lower() in label for alias in aliases):
            vals = [_num(c) for c in row[1:]]
            return [v for v in vals if v is not None]
    return None


def _ratio(pairs: List[str], *names: str) -> Optional[float]:
    """top-ratios renders as alternating name/value text chunks; find the
    value following a matching name."""
    for i, chunk in enumerate(pairs):
        low = chunk.lower()
        if any(n.lower() in low for n in names):
            # value may be embedded in the same chunk or the following ones
            v = _num(chunk.split(":")[-1]) if ":" in chunk else None
            if v is not None and not any(n.lower() == chunk.lower() for n in names):
                return v
            for nxt in pairs[i + 1:i + 4]:
                v = _num(nxt)
                if v is not None:
                    return v
    return None


def parse_company_page(html: str) -> Dict:
    """Parse a screener company page into a normalized dict. Missing parts
    simply come back absent — callers treat everything as optional."""
    parser = _PageParser()
    try:
        parser.feed(html or "")
    except Exception:
        return {}

    out: Dict = {}

    pl = parser.tables.get("profit-loss", [])
    if pl:
        annual = {}
        sales = _find_row(pl, "sales", "revenue")
        profit = _find_row(pl, "net profit", "profit after tax")
        opm = _find_row(pl, "opm", "financing margin")
        eps = _find_row(pl, "eps in rs", "eps")
        if sales:
            annual["sales"] = sales
        if profit:
            annual["net_profit"] = profit
        if opm:
            annual["opm_pct"] = opm
        if eps:
            annual["eps"] = eps
        if annual:
            out["annual"] = annual

    q = parser.tables.get("quarters", [])
    if q:
        quarterly = {}
        sales = _find_row(q, "sales", "revenue")
        profit = _find_row(q, "net profit", "profit after tax")
        if sales:
            quarterly["sales"] = sales
        if profit:
            quarterly["net_profit"] = profit
        if quarterly:
            out["quarterly"] = quarterly

    bs = parser.tables.get("balance-sheet", [])
    if bs:
        borrowings = _find_row(bs, "borrowings")
        equity = _find_row(bs, "equity capital", "share capital")
        reserves = _find_row(bs, "reserves")
        if borrowings and equity and reserves:
            try:
                own_funds = equity[-1] + reserves[-1]
                if own_funds > 0:
                    out["debt_to_equity"] = round(borrowings[-1] / own_funds, 2)
            except (IndexError, ZeroDivisionError):
                pass

    ratios = parser.ratios_pairs
    if ratios:
        out["stock_pe"] = _ratio(ratios, "stock p/e", "p/e")
        out["book_value"] = _ratio(ratios, "book value")
        out["roe_pct"] = _ratio(ratios, "roe")
        out["roce_pct"] = _ratio(ratios, "roce")
        out["dividend_yield_pct"] = _ratio(ratios, "dividend yield")
        out["market_cap_cr"] = _ratio(ratios, "market cap")
        out = {k: v for k, v in out.items() if v is not None}

    if parser.pros:
        out["pros"] = parser.pros[:5]
    if parser.cons:
        out["cons"] = parser.cons[:5]

    return out


def get_company(symbol: str) -> Optional[Dict]:
    """Fetch + parse in one call. None when unavailable."""
    html = fetch_page(symbol)
    if not html:
        return None
    parsed = parse_company_page(html)
    return parsed or None
