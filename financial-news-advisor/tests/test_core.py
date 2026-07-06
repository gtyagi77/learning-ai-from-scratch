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


def test_acronym_tickers_match_uppercase_only():
    # "HAL" all-caps is the company; "Hal" titlecase (a person) is not.
    assert "HAL.NS" in tickers.extract_tickers(
        "HAL wins fighter jet order", ["HAL.NS"], {})
    assert tickers.extract_tickers(
        "Director Hal Smith joins the board", ["HAL.NS"], {}) == []


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


def test_breeze_provider_selection_and_quote_shape(monkeypatch):
    from app import config, prices

    # Missing any of the three creds -> effective provider is Yahoo.
    monkeypatch.setattr(config, "QUOTE_PROVIDER", "breeze")
    monkeypatch.setattr(config, "BREEZE_API_KEY", "")
    monkeypatch.setattr(config, "BREEZE_API_SECRET", "")
    monkeypatch.setattr(config, "BREEZE_SESSION_TOKEN", "")
    assert prices.active_provider() == "yahoo"

    monkeypatch.setattr(config, "BREEZE_API_KEY", "k")
    monkeypatch.setattr(config, "BREEZE_API_SECRET", "s")
    monkeypatch.setattr(config, "BREEZE_SESSION_TOKEN", "t")
    assert prices.active_provider() == "breeze"

    class FakeClient:
        def get_quotes(self, **kwargs):
            assert kwargs["stock_code"] == "RELIND"
            assert kwargs["exchange_code"] == "NSE"
            return {"Success": [{"ltp": 1357.08, "previous_close": 1340.0}]}

    monkeypatch.setattr(prices, "_breeze_session", lambda: FakeClient())
    monkeypatch.setattr(prices, "_load_instrument_map", lambda: {"RELIANCE.NS": "RELIND"})
    prices._cache.clear()
    quote = prices.get_quote("RELIANCE.NS")
    assert quote == {"price": 1357.08, "previous_close": 1340.0,
                     "currency": "INR", "change_pct": 1.27}


def test_breeze_quote_falls_back_to_yahoo_when_symbol_unmapped(monkeypatch):
    from app import config, prices

    monkeypatch.setattr(config, "QUOTE_PROVIDER", "breeze")
    monkeypatch.setattr(config, "BREEZE_API_KEY", "k")
    monkeypatch.setattr(config, "BREEZE_API_SECRET", "s")
    monkeypatch.setattr(config, "BREEZE_SESSION_TOKEN", "t")
    monkeypatch.setattr(prices, "_load_instrument_map", lambda: {})  # no mapping
    sentinel = {"price": 100.0, "previous_close": 98.0, "currency": "INR", "change_pct": 2.04}
    monkeypatch.setattr(prices, "_yahoo_quote", lambda s: sentinel)
    prices._cache.clear()
    assert prices.get_quote("RELIANCE.NS") == sentinel


def test_build_breeze_map_skips_unresolvable_symbols():
    from app import instruments

    class FakeClient:
        def get_names(self, exchange_code, stock_code):
            if stock_code == "RELIANCE":
                return {"isec_stock_code": "RELIND"}
            raise Exception("ISEC_NSE_STOCK_MAP_EXCEPTION")

    mapping = instruments.build_breeze_map(FakeClient(), ["RELIANCE.NS", "UNKNOWNCO.NS"])
    assert mapping == {"RELIANCE.NS": "RELIND"}


def test_quote_shape_and_change_pct(monkeypatch):
    from app import config, prices, yahoo_session

    monkeypatch.setattr(config, "QUOTE_PROVIDER", "yahoo")

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"chart": {"result": [{"meta": {
                "regularMarketPrice": 110.0, "chartPreviousClose": 100.0,
                "currency": "INR"}}]}}

    monkeypatch.setattr(yahoo_session, "get", lambda *a, **k: _Resp())
    prices._cache.clear()
    q = prices.get_quote("RELIANCE.NS")
    assert q == {"price": 110.0, "previous_close": 100.0, "currency": "INR", "change_pct": 10.0}


def test_brokerage_name_does_not_tag_parent_bank():
    # "HDFC Securities" is a brokerage, not HDFC Bank — an Apple analyst
    # note quoting it must not be attributed to HDFCBANK.NS.
    text = "Apple gets a target price hike from HDFC Securities after strong results"
    found = tickers.extract_tickers(text, [], {})
    assert "AAPL" in found
    assert "HDFCBANK.NS" not in found
    # Kotak Securities likewise must not tag Kotak Mahindra Bank.
    found2 = tickers.extract_tickers("Kotak Securities upgrades Infosys", [], {})
    assert "INFY.NS" in found2 and "KOTAKBANK.NS" not in found2


def test_real_bank_mention_still_tags():
    found = tickers.extract_tickers("HDFC Bank Q1 profit beats estimates", [], {})
    assert "HDFCBANK.NS" in found
    # Both entities in one article: brokerage span blocked, bank still tagged.
    both = tickers.extract_tickers(
        "HDFC Bank rallies; HDFC Securities sees more upside for Apple", [], {})
    assert "HDFCBANK.NS" in both and "AAPL" in both


def test_holding_feed_only_tags_real_mentions():
    from app import crawler

    assert crawler._holding_mentioned(
        "HDFC Bank slips as NPAs rise", "HDFCBANK.NS", "HDFC Bank")
    assert crawler._holding_mentioned(
        "TATAMOTORS hits 52-week high", "TATAMOTORS.NS", "Tata Motors")
    # An off-topic article from the holding's Google News feed is NOT
    # force-attributed to the holding.
    assert not crawler._holding_mentioned(
        "Apple surges on record iPhone sales", "HDFCBANK.NS", "HDFC Bank")
    # Substrings don't count as symbol mentions ("watches" contains "tcs"? no,
    # but guard word boundaries generally).
    assert not crawler._holding_mentioned(
        "Investors watch IT stocks closely", "TCS.NS", None)


def test_implied_move_without_quote(monkeypatch):
    from app import prices, recommender

    now = time.time()
    database.insert_article(
        "Test", "Bharat Corp surges on record defence order win",
        "https://example.com/bc1", "Strong quarter.", now - 600, 0.8, ["BHARATC"],
    )
    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    rec = recommender.recommend_for_ticker("BHARATC")
    assert rec["current_price"] is None and rec["target_price"] is None
    # Upside/downside is still stated even without a live quote.
    assert rec["implied_move_pct"] is not None and rec["implied_move_pct"] > 0
    assert "STRONG BUY" in rec["rationale"] or "BUY" in rec["rationale"]
    assert "+0." in rec["rationale"]  # the signal value is shown


RICH_FUNDA = {
    "price": 100.0, "currency": "INR", "high52": 120.0, "low52": 70.0,
    "pos52": 0.6, "dma200": 95.0, "dma_gap_pct": 5.26,
    "trailing_pe": 15.0, "forward_pe": None, "target_mean": 115.0,
}

EXPENSIVE_FUNDA = {
    "price": 100.0, "currency": "INR", "high52": 102.0, "low52": 55.0,
    "pos52": 0.96, "dma200": 78.0, "dma_gap_pct": 28.0,
    "trailing_pe": 44.0, "forward_pe": None, "target_mean": None,
}


def test_valuation_score_components():
    from app import recommender

    score, notes, fair = recommender.valuation_score(RICH_FUNDA, sector_pe=22.0)
    # P/E 15 vs 22 is cheap and analyst target +15%, partly offset by the
    # mildly stretched price components — modestly positive overall.
    assert score is not None and 0.1 < score < 0.5
    assert any("P/E 15.0" in n for n in notes)
    assert any("analyst mean target" in n for n in notes)
    assert fair is not None and 100.0 < fair <= 140.0

    score2, notes2, _ = recommender.valuation_score(EXPENSIVE_FUNDA, sector_pe=22.0)
    # P/E double the sector, 28% above 200-DMA, at 52w high — negative.
    assert score2 is not None and score2 < -0.4

    assert recommender.valuation_score(None, 22.0) == (None, [], None)


def test_overvalued_stock_with_positive_news_is_not_a_buy(monkeypatch):
    """The user's core complaint: 'stock surged' news alone must not produce
    a buy when the valuation says expensive."""
    from app import fundamentals, prices, recommender

    now = time.time()
    database.insert_article(
        "Test", "Vertex Corp surges to record high on blowout earnings",
        "https://example.com/vx1", "Stellar quarter.", now - 600, 0.85,
        ["VERTEX"], ["VERTEX"],
    )
    monkeypatch.setattr(fundamentals, "get_fundamentals",
                        lambda s: dict(EXPENSIVE_FUNDA))
    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    rec = recommender.recommend_for_ticker("VERTEX")
    assert rec["news_signal"] > 0.5          # the news is glowing...
    assert rec["valuation_score"] < -0.4     # ...but the stock is expensive
    assert rec["action"] in ("HOLD", "SELL", "STRONG SELL")
    assert "Value" in rec["rationale"]


def test_undervalued_stock_gets_valuation_anchored_target(monkeypatch):
    from app import fundamentals, prices, recommender

    now = time.time()
    database.insert_article(
        "Test", "Basalt Ltd wins record contract, upgraded by analysts",
        "https://example.com/bs1", "Strong order book.", now - 600, 0.7,
        ["BASALT"], ["BASALT"],
    )
    monkeypatch.setattr(fundamentals, "get_fundamentals",
                        lambda s: dict(RICH_FUNDA))
    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    rec = recommender.recommend_for_ticker("BASALT")
    assert rec["action"] in ("BUY", "STRONG BUY")
    assert rec["target_basis"] == "valuation-anchored"
    # Fair value blends analyst target (115) and P/E fair value — above price.
    assert rec["target_price"] > 100.0
    assert rec["fair_value"] is not None


def test_rating_never_contradicts_its_own_target(monkeypatch):
    """Glowing news + expensive stock whose analyst target sits BELOW the
    price: must not say BUY while the target implies a loss."""
    from app import fundamentals, prices, recommender

    funda = dict(EXPENSIVE_FUNDA, target_mean=94.0)  # target below price=100
    now = time.time()
    database.insert_article(
        "Test", "Peak Ltd soars to record on stellar blowout results",
        "https://example.com/pk1", "Impressive quarter.", now - 600, 0.9,
        ["PEAK"], ["PEAK"],
    )
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda s: funda)
    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    rec = recommender.recommend_for_ticker("PEAK")
    assert rec["implied_move_pct"] < 0
    assert "BUY" not in rec["action"]


def test_news_only_rating_is_capped(monkeypatch):
    from app import prices, recommender

    now = time.time()
    for i in range(3):
        database.insert_article(
            "Test", f"Cinder Ltd surges on blowout record earnings beat {i}",
            f"https://example.com/cd{i}", "Stellar.", now - 600 - i, 0.9,
            ["CINDER"], ["CINDER"],
        )
    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    rec = recommender.recommend_for_ticker("CINDER")  # fundamentals stubbed None
    assert rec["signal"] >= 0.35                      # would be STRONG BUY...
    assert rec["action"] == "BUY"                     # ...but capped news-only
    assert "capped" in rec["rationale"]


def test_specific_news_outweighs_passing_mentions():
    from app import recommender

    now = time.time()
    # Headline-specific positive article.
    database.insert_article(
        "Test", "Quartz Ltd surges on record profit", "https://example.com/qz1",
        "", now - 600, 0.8, ["QUARTZ"], ["QUARTZ"],
    )
    # Negative multi-stock roundup that only mentions it in passing.
    database.insert_article(
        "Test", "Markets slump: five stocks that plunged this week",
        "https://example.com/qz2", "Quartz among decliners.", now - 600, -0.8,
        ["QUARTZ", "AAA", "BBB", "CCC", "DDD"], [],
    )
    rec = recommender.recommend_for_ticker("QUARTZ")
    # Equal magnitudes, but the specific headline dominates the roundup.
    assert rec["news_signal"] > 0.5


def test_instrument_map_builders():
    from app import instruments

    upstox_dump = [
        {"segment": "NSE_EQ", "trading_symbol": "RELIANCE",
         "instrument_key": "NSE_EQ|INE002A01018"},
        {"segment": "NSE_FO", "trading_symbol": "RELIANCE24JULFUT",
         "instrument_key": "NSE_FO|12345"},          # derivatives skipped
        {"segment": "NSE_EQ", "tradingsymbol": "TCS",  # legacy key spelling
         "instrument_key": "NSE_EQ|INE467B01029"},
    ]
    m = instruments.build_upstox_map(upstox_dump)
    assert m == {"RELIANCE.NS": "NSE_EQ|INE002A01018", "TCS.NS": "NSE_EQ|INE467B01029"}

    angel_dump = [
        {"exch_seg": "NSE", "symbol": "RELIANCE-EQ", "token": "2885"},
        {"exch_seg": "NSE", "symbol": "NIFTY24JULFUT", "token": "9999"},  # not -EQ
        {"exch_seg": "BSE", "symbol": "RELIANCE-EQ", "token": "500325"},  # wrong exch
    ]
    m2 = instruments.build_angelone_map(angel_dump)
    assert m2 == {"RELIANCE.NS": "2885"}


def test_instrument_map_prefers_env_file(monkeypatch, tmp_path):
    from app import instruments

    path = tmp_path / "instruments.json"
    path.write_text('{"reliance.ns": "NSE_EQ|X"}')
    monkeypatch.setenv("INSTRUMENT_MAP_PATH", str(path))
    # Keys are normalised to upper case; no network download is attempted.
    monkeypatch.setattr(instruments, "download_map",
                        lambda p: (_ for _ in ()).throw(AssertionError("no download")))
    assert instruments.load_map("upstox") == {"RELIANCE.NS": "NSE_EQ|X"}


def test_instrument_map_download_failure_is_graceful(monkeypatch):
    from app import instruments

    monkeypatch.delenv("INSTRUMENT_MAP_PATH", raising=False)
    monkeypatch.setattr(instruments, "DEFAULT_MAP_PATH", "/nonexistent/instruments.json")
    monkeypatch.setattr(instruments, "download_map",
                        lambda p: (_ for _ in ()).throw(OSError("offline")))
    assert instruments.load_map("upstox") == {}  # quotes fall back to Yahoo


def test_default_portfolio_is_all_indian():
    from app import config

    assert all(t.endswith(".NS") for t, _ in config.DEFAULT_PORTFOLIO)


def test_universe_is_well_formed():
    import re as _re
    from app import universe

    assert len(universe.NIFTY_50) == 50
    assert {"AI & Emerging Tech", "IT Services", "Data Centers & Digital Infra",
            "Energy & Power", "Defence", "Nifty 50"} == set(universe.SECTORS)
    # TCS/Infosys-style staffing majors must not be in the AI basket.
    ai_symbols = {sym for sym, _ in universe.AI_AND_EMERGING_TECH}
    assert not ({"TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS"} & ai_symbols)
    sym_re = _re.compile(r"^[A-Z0-9][A-Z0-9&\-]*\.NS$")
    for members in universe.SECTORS.values():
        for symbol, name in members:
            assert sym_re.match(symbol), symbol
            assert name
    # Shared tickers dedupe into one watchlist entry.
    assert len(universe.WATCHLIST) < sum(len(m) for m in universe.SECTORS.values())
    assert universe.WATCHLIST["RELIANCE.NS"] == "Reliance Industries"


def test_search_companies_prefix_beats_substring():
    results = tickers.search_companies("tata")
    names = [r["name"] for r in results]
    # Prefix matches ("Tata Motors", "Tata Elxsi"...) all come before any
    # substring-only match (e.g. a name that merely contains "tata").
    assert all(n.lower().startswith("tata") for n in names[:3])
    tickers_seen = [r["ticker"] for r in results]
    assert len(tickers_seen) == len(set(tickers_seen))  # deduped


def test_search_companies_empty_and_unknown_query():
    assert tickers.search_companies("") == []
    assert tickers.search_companies("   ") == []
    assert tickers.search_companies("zzzznotarealcompany") == []


def test_search_companies_matches_ticker_prefix():
    results = tickers.search_companies("reliance")
    assert results and results[0]["ticker"] == "RELIANCE.NS"


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
    # Default (no hidden_sectors) includes every sector.
    assert {"AI & Emerging Tech", "IT Services", "Data Centers & Digital Infra",
            "Energy & Power", "Defence", "Nifty 50"} == set(sectors)


def test_scan_universe_respects_hidden_sectors():
    from app import recommender, universe

    filtered = {name: members for name, members in universe.SECTORS.items()
                if name != "IT Services"}
    hidden = {s["sector"] for s in recommender.scan_universe(sectors=filtered)}
    assert "IT Services" not in hidden
    shown = {s["sector"] for s in recommender.scan_universe()}
    assert "IT Services" in shown


def test_scan_universe_flags_extra_members_as_custom(monkeypatch):
    from app import prices, recommender, universe

    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    now = time.time()
    database.insert_article(
        "Test", "HAL wins record fighter jet order, shares surge",
        "https://example.com/hal-custom", "Strong order book.", now - 900,
        0.8, ["HAL.NS"],
    )
    database.insert_article(
        "Test", "Widget Corp swings to profit, shares rally",
        "https://example.com/widget-custom", "Strong quarter.", now - 900,
        0.6, ["WIDGETCO"],
    )
    sectors = dict(universe.SECTORS)
    sectors["Defence"] = sectors["Defence"] + [("WIDGETCO", "Widget Corp")]
    results = {s["sector"]: s for s in recommender.scan_universe(
        sectors=sectors, custom_symbols={"Defence": {"WIDGETCO"}})}
    by_ticker = {r["ticker"]: r for r in results["Defence"]["results"]}
    assert by_ticker["HAL.NS"]["custom"] is False
    assert by_ticker["WIDGETCO"]["custom"] is True


def test_scan_universe_supports_a_wholly_custom_sector(monkeypatch):
    from app import prices, recommender

    monkeypatch.setattr(prices, "get_quote", lambda s: None)
    now = time.time()
    database.insert_article(
        "Test", "Widget Corp swings to profit, shares rally",
        "https://example.com/widget-custom2", "Strong quarter.", now - 900,
        0.6, ["WIDGETCO"],
    )
    results = {s["sector"]: s for s in recommender.scan_universe(
        sectors={"My Watchlist": [("WIDGETCO", "Widget Corp")]})}
    assert results["My Watchlist"]["watched"] == 1
    assert results["My Watchlist"]["results"][0]["ticker"] == "WIDGETCO"


def test_sector_pe_for_it_services_is_not_default():
    from app import universe

    # Hiding a sector from Market Scan must never affect per-holding
    # valuation: a stock in that sector still gets its real P/E baseline.
    assert universe.sector_pe_for("TCS.NS") == universe.SECTOR_PE["IT Services"]


def test_portfolio_crud():
    database.upsert_holding("ACME", "Acme Corp")
    assert any(h["ticker"] == "ACME" for h in database.get_portfolio())
    assert database.remove_holding("ACME")
    assert not database.remove_holding("ACME")
