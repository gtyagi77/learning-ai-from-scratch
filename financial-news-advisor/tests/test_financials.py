import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database, financials, screener  # noqa: E402

# Captured at import time, before the conftest autouse stub replaces the
# module attribute — facade tests exercise the real implementation.
REAL_GET_FINANCIALS = financials.get_financials


def setup_module():
    database.init(":memory:")


SCREENER_PAGE = """<!doctype html><html><body>
<section id="top-ratios">
  <ul>
    <li><span class="name">Market Cap</span><span class="value">₹ 20,68,251 Cr.</span></li>
    <li><span class="name">Stock P/E</span><span class="value">24.1</span></li>
    <li><span class="name">Book Value</span><span class="value">₹ 613</span></li>
    <li><span class="name">Dividend Yield</span><span class="value">0.33 %</span></li>
    <li><span class="name">ROCE</span><span class="value">9.61 %</span></li>
    <li><span class="name">ROE</span><span class="value">8.94 %</span></li>
  </ul>
</section>
<section id="quarters">
  <table class="data-table">
    <tr><th></th><th>Mar 2025</th><th>Jun 2025</th><th>Sep 2025</th><th>Dec 2025</th><th>Mar 2026</th></tr>
    <tr><td>Sales</td><td>2,64,834</td><td>2,31,535</td><td>2,40,357</td><td>2,44,200</td><td>2,88,138</td></tr>
    <tr><td>Net Profit</td><td>19,407</td><td>15,138</td><td>16,563</td><td>18,540</td><td>21,930</td></tr>
  </table>
</section>
<section id="profit-loss">
  <table class="data-table">
    <tr><th></th><th>Mar 2022</th><th>Mar 2023</th><th>Mar 2024</th><th>Mar 2025</th></tr>
    <tr><td>Sales</td><td>6,99,962</td><td>8,76,396</td><td>9,01,064</td><td>9,64,693</td></tr>
    <tr><td>OPM %</td><td>17</td><td>16</td><td>18</td><td>17</td></tr>
    <tr><td>Net Profit</td><td>60,705</td><td>66,702</td><td>69,621</td><td>69,648</td></tr>
    <tr><td>EPS in Rs</td><td>44.87</td><td>49.29</td><td>51.45</td><td>51.47</td></tr>
  </table>
</section>
<section id="balance-sheet">
  <table class="data-table">
    <tr><th></th><th>Mar 2024</th><th>Mar 2025</th></tr>
    <tr><td>Equity Capital</td><td>6,766</td><td>6,766</td></tr>
    <tr><td>Reserves</td><td>7,86,715</td><td>8,28,881</td></tr>
    <tr><td>Borrowings</td><td>3,24,622</td><td>3,36,437</td></tr>
  </table>
</section>
<section id="analysis">
  <div class="pros"><ul><li>Company has reduced debt.</li><li>Consistent dividend payout of 9.8%</li></ul></div>
  <div class="cons"><ul><li>Stock is trading at 2.5 times its book value</li></ul></div>
</section>
</body></html>"""

BANK_PAGE = """<html><body>
<section id="top-ratios"><ul>
  <li><span>Stock P/E</span><span>20.6</span></li>
  <li><span>ROE</span><span>17.1 %</span></li>
</ul></section>
<section id="profit-loss">
  <table class="data-table">
    <tr><th></th><th>Mar 2023</th><th>Mar 2024</th><th>Mar 2025</th></tr>
    <tr><td>Revenue</td><td>1,70,754</td><td>2,83,649</td><td>3,36,367</td></tr>
    <tr><td>Financing Margin %</td><td>7</td><td>6</td><td>6</td></tr>
    <tr><td>Net Profit</td><td>46,149</td><td>64,062</td><td>73,440</td></tr>
  </table>
</section>
</body></html>"""


def test_parse_screener_page():
    parsed = screener.parse_company_page(SCREENER_PAGE)
    assert parsed["stock_pe"] == 24.1
    assert parsed["roe_pct"] == 8.94
    assert parsed["roce_pct"] == 9.61
    assert parsed["book_value"] == 613
    assert parsed["annual"]["sales"] == [699962, 876396, 901064, 964693]
    assert parsed["annual"]["net_profit"][-1] == 69648
    assert parsed["annual"]["opm_pct"] == [17, 16, 18, 17]
    assert parsed["quarterly"]["sales"][-1] == 288138
    # D/E from balance sheet: borrowings / (equity + reserves), latest year
    assert parsed["debt_to_equity"] == round(336437 / (6766 + 828881), 2)
    assert parsed["pros"] and "reduced debt" in parsed["pros"][0]
    assert parsed["cons"]


def test_parse_bank_page_uses_aliases():
    parsed = screener.parse_company_page(BANK_PAGE)
    # "Revenue" and "Financing Margin %" aliases must resolve for banks.
    assert parsed["annual"]["sales"] == [170754, 283649, 336367]
    assert parsed["annual"]["opm_pct"] == [7, 6, 6]
    assert "debt_to_equity" not in parsed  # no balance sheet section


def test_parse_garbage_html():
    assert screener.parse_company_page("<p>nothing here") == {}
    assert screener.parse_company_page("") == {}


def test_slug_for():
    assert screener.slug_for("RELIANCE.NS") == "RELIANCE"
    assert screener.slug_for("M&M.NS") == "M%26M"
    assert screener.slug_for("500325.BO") == "500325"
    assert screener.slug_for("AAPL") is None  # not an Indian listing


def test_derived_metrics():
    payload = financials._derive({
        "annual": {"sales": [100, 120, 150, 200], "net_profit": [10, 12, 18, 24],
                   "opm_pct": [15, 16, 17, 20]},
        "quarterly": {"sales": [40, 42, 45, 48, 52]},
    })
    assert payload["rev_cagr_3y_pct"] == round(((200 / 100) ** (1 / 3) - 1) * 100, 1)
    assert payload["profit_cagr_3y_pct"] == round(((24 / 10) ** (1 / 3) - 1) * 100, 1)
    # opm [15,16,17,20]: latest 20 vs mean of the prior three (15,16,17)=16
    assert payload["opm_trend_pp"] == 4.0
    assert payload["q_sales_yoy_pct"] == 30.0


def test_cagr_loss_years_fall_back():
    # Negative start makes CAGR undefined -> YoY fallback (20 -> 40 = +100%).
    assert financials._cagr_pct([-5, 10, 20, 40]) == 100.0
    assert financials._cagr_pct([10, -5]) is None


def test_facade_cache_and_stale_serve(monkeypatch):
    monkeypatch.setattr(financials, "get_financials", REAL_GET_FINANCIALS)
    calls = {"n": 0}

    def fake_fetch(ticker):
        calls["n"] += 1
        return {"roe_pct": 18.0, "source": "screener"}

    monkeypatch.setattr(financials, "_fetch", fake_fetch)
    f1 = financials.get_financials("TESTCO.NS")
    assert f1["roe_pct"] == 18.0 and calls["n"] == 1
    # Second call inside TTL hits the cache.
    f2 = financials.get_financials("TESTCO.NS")
    assert f2["roe_pct"] == 18.0 and calls["n"] == 1
    # allow_fetch=False never fetches, even for unknown tickers.
    assert financials.get_financials("NEVERFETCHED.NS", allow_fetch=False) is None
    assert calls["n"] == 1

    # Expire the cache; make refresh fail -> stale payload is served.
    database.put_cached_financials("TESTCO.NS", "screener", {"roe_pct": 18.0})
    with database._lock:
        database._conn.execute(
            "UPDATE financials_cache SET fetched_ts = ? WHERE ticker = 'TESTCO.NS'",
            (time.time() - 2 * financials.CACHE_TTL_SECONDS,))
        database._conn.commit()
    monkeypatch.setattr(financials, "_fetch", lambda t: None)
    f3 = financials.get_financials("TESTCO.NS")
    assert f3["roe_pct"] == 18.0  # stale-served


def test_negative_cache(monkeypatch):
    monkeypatch.setattr(financials, "get_financials", REAL_GET_FINANCIALS)
    monkeypatch.setattr(financials, "_fetch", lambda t: None)
    assert financials.get_financials("GHOST.NS") is None
    # Negative result is cached: a second call returns None without fetching.
    monkeypatch.setattr(financials, "_fetch",
                        lambda t: (_ for _ in ()).throw(AssertionError("refetched")))
    assert financials.get_financials("GHOST.NS") is None
