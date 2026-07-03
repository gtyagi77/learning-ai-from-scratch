"""Background crawler: polls news feeds, scores articles, stores them."""

import logging
import threading
import time
from typing import Dict, List, Tuple

import requests

from . import config, database, rss, sentiment, tickers

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


def _feed_list() -> List[Tuple[str, str]]:
    feeds = list(config.NEWS_FEEDS)
    for holding in database.get_portfolio():
        symbol = holding["ticker"]
        feeds.append(
            (f"Yahoo:{symbol}", config.TICKER_FEED_TEMPLATE.format(ticker=symbol))
        )
    return feeds


def crawl_once() -> int:
    """Poll every feed once; returns the number of newly stored articles."""
    started = time.time()
    portfolio = database.get_portfolio()
    universe = [h["ticker"] for h in portfolio]
    extra_names = {
        h["name"].lower(): h["ticker"] for h in portfolio if h.get("name")
    }

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
            mentioned = tickers.extract_tickers(text, universe, extra_names)
            # Per-ticker feeds are implicitly about that ticker.
            if source.startswith("Yahoo:"):
                symbol = source.split(":", 1)[1]
                if symbol not in mentioned:
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
