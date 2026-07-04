import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database, macro, recommender  # noqa: E402

REAL_MACRO_TILT = macro.macro_tilt
REAL_GET_INDICATORS = macro.get_indicators


def setup_module():
    database.init(":memory:")


RICH_FIN = {
    "source": "screener", "roe_pct": 18.5, "debt_to_equity": 0.3,
    "rev_cagr_3y_pct": 14.0, "profit_cagr_3y_pct": 18.0,
    "opm_trend_pp": 1.5, "q_sales_yoy_pct": 12.0, "stock_pe": 21.0,
    "annual": {"sales": [100, 115, 130, 150], "net_profit": [10, 12, 14, 17]},
}

WEAK_FIN = {
    "source": "screener", "roe_pct": 4.0, "debt_to_equity": 2.4,
    "rev_cagr_3y_pct": -3.0, "profit_cagr_3y_pct": -10.0,
    "opm_trend_pp": -2.0, "q_sales_yoy_pct": -8.0,
}


# ---------- quality ----------

def test_quality_score_signs():
    good, notes = recommender.quality_score(RICH_FIN, is_financial=False)
    bad, _ = recommender.quality_score(WEAK_FIN, is_financial=False)
    assert good > 0.3
    assert bad < -0.3
    assert any("ROE" in n for n in notes)
    assert any("revenue growth" in n for n in notes)


def test_quality_skips_de_for_banks():
    fin = {"roe_pct": 17.0, "debt_to_equity": 8.0, "rev_cagr_3y_pct": 15.0}
    bank, bank_notes = recommender.quality_score(fin, is_financial=True)
    nonbank, _ = recommender.quality_score(fin, is_financial=False)
    # Leverage is a bank's business model: skipping D/E must help the score.
    assert bank > nonbank
    assert not any("debt/equity" in n for n in bank_notes)


def test_quality_needs_two_components():
    assert recommender.quality_score({"roe_pct": 20.0}, False) == (None, [])
    assert recommender.quality_score(None, False) == (None, [])


# ---------- macro ----------

FAKE_INDICATORS = {
    "nifty": {"name": "Nifty 50", "state": 0.5, "label": "up 4% in 3m", "level": 26000, "chg_3m_pct": 4.0},
    "usdinr": {"name": "USD/INR", "state": 0.75, "label": "rupee weakened 3.0% in 3m", "level": 90.1, "chg_3m_pct": 3.0},
    "brent": {"name": "Brent crude", "state": 0.8, "label": "crude up 16% in 3m", "level": 92.0, "chg_3m_pct": 16.0},
    "vix": {"name": "India VIX", "state": -0.2, "label": "India VIX at 13.0", "level": 13.0, "chg_3m_pct": 0.0},
}


def test_macro_tilt_sector_and_overrides(monkeypatch):
    monkeypatch.setattr(macro, "get_indicators", lambda: FAKE_INDICATORS)
    monkeypatch.setattr(macro, "macro_tilt", REAL_MACRO_TILT)

    it_tilt, it_notes = macro.macro_tilt("INFY.NS")
    # Weak rupee is good for IT exporters.
    assert it_tilt > 0
    assert any("USD/INR" in n for n in it_notes)

    # Rising crude: upstream ONGC gains, refiner BPCL loses.
    ongc_tilt, _ = macro.macro_tilt("ONGC.NS")
    bpcl_tilt, _ = macro.macro_tilt("BPCL.NS")
    assert ongc_tilt > bpcl_tilt
    assert ongc_tilt > 0


def test_macro_tilt_none_without_data(monkeypatch):
    monkeypatch.setattr(macro, "get_indicators", lambda: {})
    monkeypatch.setattr(macro, "macro_tilt", REAL_MACRO_TILT)
    tilt, notes = macro.macro_tilt("INFY.NS")
    assert tilt is None and notes == []


# ---------- blending & profiles ----------

def test_blend_renormalizes_and_caps_macro():
    combined, w = recommender._blend(
        {"value": 0.5, "quality": None, "news": None, "macro": 1.0}, "balanced")
    # Only value+macro available; macro share must be capped at 0.25.
    assert w["macro"] == 0.25 and abs(w["value"] - 0.75) < 1e-9
    assert combined == round(0.75 * 0.5 + 0.25 * 1.0, 3)


def test_macro_alone_gives_no_signal():
    combined, w = recommender._blend(
        {"value": None, "quality": None, "news": None, "macro": 0.9}, "balanced")
    assert combined is None and w == {}


def test_risk_profile_shifts_weights():
    comps = {"value": 0.2, "quality": 0.2, "news": 0.8, "macro": 0.0}
    aggressive, wa = recommender._blend(comps, "aggressive")
    conservative, wc = recommender._blend(comps, "conservative")
    # Aggressive leans on news, so the same inputs score higher.
    assert wa["news"] > wc["news"]
    assert aggressive > conservative


# ---------- horizons & strategy ----------

def test_horizons_have_dates_and_targets(monkeypatch):
    from app import financials, fundamentals, prices

    now = time.time()
    database.insert_article(
        "Test", "Granite Ltd wins record order, upgraded by analysts",
        "https://example.com/gr1", "Strong outlook.", now - 600, 0.7,
        ["GRANITE"], ["GRANITE"],
    )
    funda = {"price": 100.0, "currency": "INR", "dma200": 95.0,
             "dma_gap_pct": 5.26, "pos52": 0.5, "trailing_pe": 15.0,
             "target_mean": 118.0, "target_low": 100.0, "target_high": 130.0,
             "analyst_rating": 2.0, "analyst_count": 20}
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda s: dict(funda))
    monkeypatch.setattr(financials, "get_financials",
                        lambda s, allow_fetch=True: dict(RICH_FIN))
    monkeypatch.setattr(prices, "get_quote", lambda s: None)

    rec = recommender.recommend_for_ticker("GRANITE")
    hz = rec["horizons"]
    assert [h["label"] for h in hz] == ["Short (1m)", "Medium (3m)", "Long (12m)"]
    today = date.today()
    assert hz[0]["date"] == (today + timedelta(days=28)).isoformat()
    assert hz[1]["date"] == (today + timedelta(days=91)).isoformat()
    assert hz[2]["date"] == (today + timedelta(days=365)).isoformat()
    # Positive setup: every horizon has a target; long = analyst mean.
    assert all(h["target_price"] for h in hz)
    assert hz[2]["target_price"] == 118.0 and hz[2]["basis"] == "analyst mean target"
    assert hz[2]["expected_return_pct"] == 18.0

    # STRONG allowed here because both value and quality resolved.
    assert rec["action"] in ("BUY", "STRONG BUY")
    assert rec["quality_score"] is not None
    assert "street consensus" in " ".join(rec["valuation_notes"])

    strat = rec["strategy"]
    assert strat["stop_loss"] == max(95.0, 92.0)
    assert strat["position_size_hint_pct"] > 0
    assert any("results" in r for r in strat["review"])


def test_macro_and_stock_endpoints():
    from tests.conftest import make_authed_client

    client = make_authed_client()
    # Unauthenticated requests are rejected.
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    assert anon.get("/api/macro").status_code == 401
    assert anon.get("/api/recommendations").status_code == 401

    m = client.get("/api/macro").json()
    assert "indicators" in m and "sector_tilts" in m

    s = client.get("/api/stock/RELIANCE.NS").json()
    assert s["recommendation"]["ticker"] == "RELIANCE.NS"
    assert "financials" in s and "history" in s
    assert s["recommendation"]["horizons"]  # dated horizons always present

    assert client.get("/api/stock/BAD TICKER!").status_code == 400

    # profile query param is accepted and echoed.
    r = client.get("/api/recommendations?profile=aggressive").json()
    assert r["risk_profile"] == "aggressive"
    r2 = client.get("/api/recommendations?profile=nonsense").json()
    assert r2["risk_profile"] == "balanced"


def test_position_hint_scales_with_profile(monkeypatch):
    from app import financials, fundamentals, prices

    now = time.time()
    database.insert_article(
        "Test", "Slate Ltd posts solid growth", "https://example.com/sl1",
        "", now - 600, 0.5, ["SLATE"], ["SLATE"],
    )
    funda = {"price": 50.0, "currency": "INR", "dma200": 48.0,
             "dma_gap_pct": 4.2, "pos52": 0.5, "trailing_pe": 18.0}
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda s: dict(funda))
    monkeypatch.setattr(financials, "get_financials",
                        lambda s, allow_fetch=True: dict(RICH_FIN))
    monkeypatch.setattr(prices, "get_quote", lambda s: None)

    agg = recommender.recommend_for_ticker("SLATE", risk_profile="aggressive")
    con = recommender.recommend_for_ticker("SLATE", risk_profile="conservative")
    assert (agg["strategy"]["position_size_hint_pct"]
            > con["strategy"]["position_size_hint_pct"])
    assert agg["risk_profile"] == "aggressive"
