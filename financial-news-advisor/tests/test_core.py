import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database, rss, sentiment, tickers  # noqa: E402


def setup_module():
    database.init(":memory:")


# ---------- sentiment ----------

def test_positive_headline():
    assert sentiment.score_text("Apple beats earnings expectations, shares surge") > 0.3


def test_negative_headline():
    assert sentiment.score_text("Tesla shares plunge after disappointing deliveries") < -0.3


def test_neutral_headline():
    assert sentiment.score_text("Apple to hold annual shareholder meeting in March") == 0.0


def test_negation_flips_polarity():
    plain = sentiment.score_text("profit growth")
    negated = sentiment.score_text("no profit growth")
    assert plain > 0 > negated


def test_headline_weighted_over_summary():
    score = sentiment.score_article(
        "Nvidia surges to record on blowout earnings",
        "Some analysts remain cautious about risks.",
    )
    assert score > 0.2


# ---------- rss ----------

RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>Apple beats &amp; rallies</title>
<link>https://example.com/a1</link>
<description><![CDATA[<p>Shares <b>jumped</b> 5%.</p>]]></description>
<pubDate>Thu, 02 Jul 2026 14:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Test</title>
<entry><title>Markets fall on tariff fears</title>
<link rel="alternate" href="https://example.com/a2"/>
<updated>2026-07-02T15:30:00Z</updated>
<summary>Stocks declined broadly.</summary></entry>
</feed>"""


def test_parse_rss():
    items = rss.parse_feed(RSS_SAMPLE)
    assert len(items) == 1
    assert items[0].title == "Apple beats & rallies"
    assert items[0].link == "https://example.com/a1"
    assert "jumped 5%" in items[0].summary
    assert items[0].published.year == 2026


def test_parse_atom():
    items = rss.parse_feed(ATOM_SAMPLE)
    assert len(items) == 1
    assert items[0].link == "https://example.com/a2"
    assert items[0].published.hour == 15


def test_parse_garbage_returns_empty():
    assert rss.parse_feed("not xml at all") == []


GOOGLE_NEWS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>"Reliance Industries" stock - Google News</title>
<item>
<title>Reliance Industries hits record high after strong Q3 results - Economic Times</title>
<link>https://news.google.com/rss/articles/CBMiabc123?oc=5</link>
<guid isPermaLink="false">CBMiabc123</guid>
<pubDate>Fri, 03 Jul 2026 06:30:00 GMT</pubDate>
<description>&lt;a href="https://news.google.com/x"&gt;Reliance Industries hits record high&lt;/a&gt;&nbsp;&lt;font&gt;Economic Times&lt;/font&gt;</description>
<source url="https://economictimes.indiatimes.com">Economic Times</source>
</item>
</channel></rss>"""


def test_parse_google_news_rss():
    # Sample contains a bare &nbsp; (a non-XML entity Google News emits);
    # the parser must recover from it rather than dropping the whole feed.
    items = rss.parse_feed(GOOGLE_NEWS_SAMPLE)
    assert len(items) == 1
    assert items[0].title == "Reliance Industries hits record high after strong Q3 results - Economic Times"
    assert items[0].link.startswith("https://news.google.com/rss/articles/")
    assert items[0].published.year == 2026
    # The publisher suffix doesn't stop the headline from scoring bullish.
    assert sentiment.score_article(items[0].title, items[0].summary) > 0.2


# ---------- tickers ----------

def test_extract_by_company_name():
    found = tickers.extract_tickers("Apple unveils new iPhone", ["AAPL"], {})
    assert "AAPL" in found


def test_extract_cashtag():
    assert "NVDA" in tickers.extract_tickers("Traders pile into $NVDA calls", [], {})


def test_extract_exchange_notation():
    assert "AMD" in tickers.extract_tickers("Advanced Micro Devices (NASDAQ: AMD) rallies", [], {})


def test_ambiguous_symbol_not_matched_bare():
    found = tickers.extract_tickers("IT WAS ALL FOR THE BEST", ["ALL", "IT"], {})
    assert found == []


def test_extract_indian_company_names():
    text = "Reliance Industries and Infosys lead Nifty rally; HDFC Bank lags"
    found = tickers.extract_tickers(text, [], {})
    assert {"RELIANCE.NS", "INFY.NS", "HDFCBANK.NS"} <= set(found)


def test_extract_nse_notation_resolves_to_ns():
    found = tickers.extract_tickers("Tata Consultancy Services (NSE: TCS) wins deal", [], {})
    assert "TCS.NS" in found


def test_parenthesised_word_is_not_a_ticker():
    assert tickers.extract_tickers("The company filed for an offering (IPO)", [], {}) == []


def test_universe_bare_match_uses_base_symbol():
    found = tickers.extract_tickers("TATAMOTORS hits 52-week high", ["TATAMOTORS.NS"], {})
    assert "TATAMOTORS.NS" in found


def test_resolve_symbol():
    assert tickers.resolve_symbol("reliance") == "RELIANCE.NS"
    assert tickers.resolve_symbol("TCS") == "TCS.NS"
    assert tickers.resolve_symbol("AAPL") == "AAPL"          # US passes through
    assert tickers.resolve_symbol("RELIANCE.NS") == "RELIANCE.NS"
    assert tickers.resolve_symbol("500325.BO") == "500325.BO"  # BSE code untouched


# ---------- database + recommender ----------

def test_article_roundtrip_and_recommendation():
    from app import recommender

    now = time.time()
    assert database.insert_article(
        "Test", "Acme Corp surges on record profit", "https://example.com/acme1",
        "Blowout quarter.", now - 600, 0.8, ["ACME"],
    )
    # duplicate link rejected
    assert not database.insert_article(
        "Test", "dup", "https://example.com/acme1", "", now, 0.1, [],
    )
    assert database.insert_article(
        "Test", "Acme wins major contract", "https://example.com/acme2",
        "", now - 3600, 0.6, ["ACME"],
    )

    rec = recommender.recommend_for_ticker("ACME")
    assert rec["action"] in ("BUY", "STRONG BUY")
    assert rec["news_count"] == 2
    assert 0 < rec["confidence"] <= 1
    assert rec["degree"] in ("low", "moderate", "high")


def test_target_price_from_quote(monkeypatch):
    from app import prices, recommender

    now = time.time()
    database.insert_article(
        "Test", "Zenith surges on blowout record earnings, beats expectations",
        "https://example.com/zen1", "Shares jumped.", now - 300, 0.9, ["ZEN"],
    )
    monkeypatch.setattr(
        prices, "get_quote",
        lambda s: {"price": 100.0, "previous_close": 98.0, "currency": "USD", "change_pct": 2.04},
    )
    rec = recommender.recommend_for_ticker("ZEN")
    assert rec["current_price"] == 100.0
    # Positive signal must imply a target above the current price, bounded
    # by the configured maximum implied move.
    assert 100.0 < rec["target_price"] <= 110.0
    expected = round(100.0 * (1 + rec["signal"] * 0.10 * (0.4 + 0.6 * rec["confidence"])), 2)
    assert rec["target_price"] == expected
    assert rec["implied_move_pct"] > 0


def test_no_news_means_hold():
    from app import recommender

    rec = recommender.recommend_for_ticker("ZZZQ")
    assert rec["action"] == "HOLD"
    assert rec["confidence"] == 0.0


def test_google_news_feed_query(monkeypatch):
    from app import config, crawler

    monkeypatch.setattr(config, "TICKER_NEWS_PROVIDER", "google")
    url = crawler._holding_feed("RELIANCE.NS", "Reliance Industries")
    assert url.startswith("https://news.google.com/rss/search?q=")
    # Company name is used (not the .NS symbol Google can't parse), quoted
    # and scoped to the equity story.
    assert "Reliance+Industries" in url and "stock" in url
    assert "gl=IN" in url


def test_holding_feed_provider_switch(monkeypatch):
    from app import config, crawler

    monkeypatch.setattr(config, "TICKER_NEWS_PROVIDER", "yahoo")
    assert "finance.yahoo.com" in crawler._holding_feed("TCS.NS", "TCS")
    monkeypatch.setattr(config, "TICKER_NEWS_PROVIDER", "none")
    assert crawler._holding_feed("TCS.NS", "TCS") is None
    # Falls back to the bare symbol when no company name is known.
    monkeypatch.setattr(config, "TICKER_NEWS_PROVIDER", "google")
    assert "TCS" in crawler._holding_feed("TCS.NS", None)


def test_quote_provider_selection_and_fallback(monkeypatch):
    from app import config, prices

    # Broker selected but unconfigured -> effective provider is Yahoo.
    monkeypatch.setattr(config, "QUOTE_PROVIDER", "upstox")
    monkeypatch.setattr(config, "UPSTOX_ACCESS_TOKEN", "")
    assert prices.active_provider() == "yahoo"

    # Broker configured -> it is active, but a per-symbol miss still falls
    # back to Yahoo so quotes keep resolving.
    monkeypatch.setattr(config, "UPSTOX_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(prices, "_load_instrument_map", lambda: {})  # no keys
    assert prices.active_provider() == "upstox"
    sentinel = {"price": 100.0, "previous_close": 98.0, "currency": "INR", "change_pct": 2.04}
    monkeypatch.setattr(prices, "_yahoo_quote", lambda s: sentinel)
    prices._cache.clear()
    assert prices.get_quote("RELIANCE.NS") == sentinel


def test_quote_shape_and_change_pct(monkeypatch):
    from app import config, prices

    monkeypatch.setattr(config, "QUOTE_PROVIDER", "yahoo")

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"chart": {"result": [{"meta": {
                "regularMarketPrice": 110.0, "chartPreviousClose": 100.0,
                "currency": "INR"}}]}}

    monkeypatch.setattr(prices.requests, "get", lambda *a, **k: _Resp())
    prices._cache.clear()
    q = prices.get_quote("RELIANCE.NS")
    assert q == {"price": 110.0, "previous_close": 100.0, "currency": "INR", "change_pct": 10.0}


def test_universe_is_well_formed():
    import re as _re
    from app import universe

    assert len(universe.NIFTY_50) == 50
    assert {"AI & IT", "Data Centers & Digital Infra", "Energy & Power",
            "Defence", "Nifty 50"} == set(universe.SECTORS)
    sym_re = _re.compile(r"^[A-Z0-9][A-Z0-9&\-]*\.NS$")
    for members in universe.SECTORS.values():
        for symbol, name in members:
            assert sym_re.match(symbol), symbol
            assert name
    # Shared tickers dedupe into one watchlist entry.
    assert len(universe.WATCHLIST) < sum(len(m) for m in universe.SECTORS.values())
    assert universe.WATCHLIST["RELIANCE.NS"] == "Reliance Industries"


def test_scan_universe_ranks_newsy_tickers(monkeypatch):
    from app import prices, recommender

    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    now = time.time()
    database.insert_article(
        "Test", "HAL wins record fighter jet order, shares surge",
        "https://example.com/hal1", "Strong order book growth.", now - 900,
        0.8, ["HAL.NS"],
    )
    database.insert_article(
        "Test", "Suzlon Energy plunges as wind orders disappoint",
        "https://example.com/suz1", "Weak quarter.", now - 900,
        -0.7, ["SUZLON.NS"],
    )
    sectors = {s["sector"]: s for s in recommender.scan_universe()}
    defence = sectors["Defence"]
    assert any(r["ticker"] == "HAL.NS" and "BUY" in r["action"]
               for r in defence["results"])
    energy = sectors["Energy & Power"]
    assert any(r["ticker"] == "SUZLON.NS" and "SELL" in r["action"]
               for r in energy["results"])
    # Tickers without news never appear in scan results.
    for s in sectors.values():
        assert all(r["news_count"] > 0 for r in s["results"])


def test_portfolio_crud():
    database.upsert_holding("ACME", "Acme Corp")
    assert any(h["ticker"] == "ACME" for h in database.get_portfolio())
    assert database.remove_holding("ACME")
    assert not database.remove_holding("ACME")
