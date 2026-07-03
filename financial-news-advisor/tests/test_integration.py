"""End-to-end test: local RSS server -> crawler -> recommender -> HTTP API."""

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, crawler, database  # noqa: E402
from app.main import app  # noqa: E402

FEED_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Local Test Wire</title>
<item><title>Apple surges on record iPhone demand, beats expectations</title>
<link>http://local.test/apple-1</link>
<description>Shares jumped after a blowout quarter.</description></item>
<item><title>Tesla plunges as regulators open probe into autopilot crashes</title>
<link>http://local.test/tesla-1</link>
<description>The stock tumbled on the disappointing news.</description></item>
<item><title>Fed leaves rates unchanged</title>
<link>http://local.test/macro-1</link>
<description>Policy makers held steady.</description></item>
</channel></rss>"""


class _FeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = FEED_XML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_full_pipeline(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FeedHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    feed_url = f"http://127.0.0.1:{server.server_port}/feed.xml"

    monkeypatch.setattr(config, "NEWS_FEEDS", [("LocalWire", feed_url)])
    monkeypatch.setattr(config, "TICKER_FEED_TEMPLATE", feed_url + "?s={ticker}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    database.init(":memory:")
    database.upsert_holding("AAPL", "Apple")
    database.upsert_holding("TSLA", "Tesla")

    added = crawler.crawl_once()
    assert added == 3

    # Second crawl dedupes everything.
    assert crawler.crawl_once() == 0

    client = TestClient(app, raise_server_exceptions=True)

    news = client.get("/api/news").json()["articles"]
    assert len(news) == 3
    by_link = {a["link"]: a for a in news}
    assert "AAPL" in by_link["http://local.test/apple-1"]["tickers"]
    assert by_link["http://local.test/apple-1"]["sentiment"] > 0.2
    assert "TSLA" in by_link["http://local.test/tesla-1"]["tickers"]
    assert by_link["http://local.test/tesla-1"]["sentiment"] < -0.2

    recs = client.get("/api/recommendations").json()["recommendations"]
    by_ticker = {r["ticker"]: r for r in recs}
    assert by_ticker["AAPL"]["action"] in ("BUY", "STRONG BUY")
    assert by_ticker["TSLA"]["action"] in ("SELL", "STRONG SELL")
    assert by_ticker["AAPL"]["confidence"] > 0
    assert by_ticker["AAPL"]["top_articles"]

    # Portfolio management through the API.
    resp = client.post("/api/portfolio", json={"ticker": "msft", "name": "Microsoft"})
    assert resp.status_code == 200 and resp.json()["ticker"] == "MSFT"
    assert client.post("/api/portfolio", json={"ticker": "BAD TICKER!"}).status_code == 422
    assert client.delete("/api/portfolio/MSFT").status_code == 200
    assert client.delete("/api/portfolio/MSFT").status_code == 404

    # Bare NSE symbols are resolved to their Yahoo .NS form.
    resp = client.post("/api/portfolio", json={"ticker": "reliance"})
    assert resp.status_code == 200 and resp.json()["ticker"] == "RELIANCE.NS"
    assert client.delete("/api/portfolio/RELIANCE.NS").status_code == 200
    resp = client.post("/api/portfolio", json={"ticker": "TATAMOTORS.NS", "name": "Tata Motors"})
    assert resp.status_code == 200 and resp.json()["ticker"] == "TATAMOTORS.NS"
    assert client.delete("/api/portfolio/TATAMOTORS.NS").status_code == 200

    server.shutdown()
