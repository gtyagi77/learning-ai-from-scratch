"""Background crawler: polls news feeds, scores articles, stores them."""

import logging
import re
import threading
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests

from . import config, database, rss, sentiment, tickers, universe

log = logging.getLogger("crawler")

_status = {
    "last_run": None,
    "last_run_duration_s": None,
    "cycles": 0,
    "new_articles_last_run": 0,
    "feeds_ok": 0,
    "feeds_failed": 0,
    "running": False,
}
_status_lock = threading.Lock()
_stop = threading.Event()


def get_status() -> Dict:
    with _status_lock:
        return dict(_status)


def _fetch(url: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.text


def _holding_mentioned(text: str, symbol: str, name: Optional[str]) -> bool:
    """True when the holding's company name or base symbol actually appears
    in the article text. Google News search results are relevance-ranked and
    can drift off-topic, so per-holding feed items are only attributed to the
    holding when it is genuinely mentioned — otherwise the article is stored
    as general market news."""
    lower = (text or "").lower()
    if name and re.search(r"\b" + re.escape(name.lower()) + r"\b", lower):
        return True
    base = symbol.split(".")[0].lower()
    return bool(re.search(r"\b" + re.escape(base) + r"\b", lower))


def _holding_feed(symbol: str, name: Optional[str]) -> Optional[str]:
    """Build the per-holding news feed URL for the configured provider."""
    provider = config.TICKER_NEWS_PROVIDER
    if provider == "none":
        return None
    if provider == "yahoo":
        return config.YAHOO_TICKER_FEED_TEMPLATE.format(ticker=symbol)
    # Default: Google News search. Query by company name when known (Google
    # doesn't understand ".NS" symbols), scoped with "stock" to stay on the
    # equity story and off unrelated same-name news.
    base = name or symbol.split(".")[0]
    query = urllib.parse.quote_plus(f'"{base}" stock')
    return config.GOOGLE_NEWS_TEMPLATE.format(query=query)


def _feed_list() -> List[Tuple[str, str]]:
    # source label is prefixed "Holding:{symbol}" so crawl_once can attribute
    # every article from a per-holding feed to that symbol.
    feeds = list(config.NEWS_FEEDS)
    for holding in database.get_portfolio():
        url = _holding_feed(holding["ticker"], holding.get("name"))
        if url:
            feeds.append((f"Holding:{holding['ticker']}", url))
    return feeds


def crawl_once() -> int:
    """Poll every feed once; returns the number of newly stored articles."""
    started = time.time()
    portfolio = database.get_portfolio()
    holding_names = {h["ticker"]: h.get("name") for h in portfolio}
    # Articles are attributed against the whole watch universe (Nifty 50 +
    # sector baskets), not just the portfolio, so the market scan works.
    symbols = set(universe.watch_symbols())
    symbols.update(h["ticker"] for h in portfolio)
    extra_names = {
        name.lower(): sym for sym, name in universe.WATCHLIST.items()
    }
    extra_names.update(
        {h["name"].lower(): h["ticker"] for h in portfolio if h.get("name")}
    )

    new_count, ok, failed = 0, 0, 0
    for source, url in _feed_list():
        try:
            items = rss.parse_feed(_fetch(url))
            ok += 1
        except Exception as exc:
            failed += 1
            log.debug("feed %s failed: %s", source, exc)
            continue

        for item in items:
            if database.has_article(item.link):
                continue
            text = f"{item.title}. {item.summary}"
            score = sentiment.score_article(item.title, item.summary)
            mentioned = tickers.extract_tickers(text, symbols, extra_names)
            # Per-holding feed items are attributed to the holding only when
            # the article really mentions it (see _holding_mentioned).
            if source.startswith("Holding:"):
                symbol = source.split(":", 1)[1]
                if symbol not in mentioned and _holding_mentioned(
                        text, symbol, holding_names.get(symbol)):
                    mentioned.append(symbol)
            published = item.published.timestamp() if item.published else None
            if database.insert_article(source, item.title, item.link,
                                       item.summary, published, score, mentioned):
                new_count += 1

    database.prune_articles()
    with _status_lock:
        _status.update(
            last_run=time.time(),
            last_run_duration_s=round(time.time() - started, 1),
            cycles=_status["cycles"] + 1,
            new_articles_last_run=new_count,
            feeds_ok=ok,
            feeds_failed=failed,
        )
    return new_count


def _loop() -> None:
    with _status_lock:
        _status["running"] = True
    while not _stop.is_set():
        try:
            added = crawl_once()
            log.info("crawl cycle done: %d new articles", added)
        except Exception:
            log.exception("crawl cycle crashed")
        _stop.wait(config.CRAWL_INTERVAL_SECONDS)
    with _status_lock:
        _status["running"] = False


def start() -> None:
    thread = threading.Thread(target=_loop, name="news-crawler", daemon=True)
    thread.start()


def stop() -> None:
    _stop.set()
