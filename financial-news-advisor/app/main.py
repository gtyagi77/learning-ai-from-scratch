"""FastAPI application: JSON API + single-page dashboard."""

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from . import config, crawler, database, recommender, tickers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Accepts NSE/BSE Yahoo symbols (RELIANCE.NS, M&M.NS, BAJAJ-AUTO.NS,
# 500325.BO) as well as plain US symbols (AAPL, BRK-B).
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9&.\-]{0,19}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init()
    if not database.get_portfolio():
        for symbol, name in config.DEFAULT_PORTFOLIO:
            database.upsert_holding(symbol, name)
    crawler.start()
    yield
    crawler.stop()


app = FastAPI(title="Financial News Portfolio Advisor", lifespan=lifespan)


class HoldingIn(BaseModel):
    ticker: str
    name: Optional[str] = None
    shares: Optional[float] = None
    cost_basis: Optional[float] = None

    @field_validator("ticker")
    @classmethod
    def _valid_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not _TICKER_RE.match(v):
            raise ValueError("invalid ticker symbol")
        # "RELIANCE" -> "RELIANCE.NS" for known NSE names, so users can
        # type the symbol the way Indian brokers display it.
        return tickers.resolve_symbol(v)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/status")
def status():
    return {
        "crawler": crawler.get_status(),
        "articles_stored": database.article_count(),
        "crawl_interval_s": config.CRAWL_INTERVAL_SECONDS,
        "lookback_hours": config.LOOKBACK_HOURS,
        "server_time": time.time(),
    }


@app.get("/api/news")
def news(ticker: Optional[str] = None, limit: int = 40):
    limit = max(1, min(limit, 200))
    return {"articles": database.recent_articles(limit=limit, ticker=ticker)}


@app.get("/api/portfolio")
def portfolio():
    return {"holdings": database.get_portfolio()}


@app.post("/api/portfolio")
def add_holding(holding: HoldingIn):
    database.upsert_holding(holding.ticker, holding.name, holding.shares, holding.cost_basis)
    return {"ok": True, "ticker": holding.ticker}


@app.delete("/api/portfolio/{ticker}")
def delete_holding(ticker: str):
    if not database.remove_holding(ticker):
        raise HTTPException(status_code=404, detail="ticker not in portfolio")
    return {"ok": True}


@app.get("/api/recommendations")
def recommendations():
    return {
        "generated_at": time.time(),
        "disclaimer": (
            "Automatically generated from news sentiment for educational "
            "purposes only. Not investment advice."
        ),
        "recommendations": recommender.recommend_portfolio(),
    }


@app.get("/api/recommendations/{ticker}")
def recommendation(ticker: str):
    if not _TICKER_RE.match(ticker.strip()):
        raise HTTPException(status_code=400, detail="invalid ticker symbol")
    return recommender.recommend_for_ticker(tickers.resolve_symbol(ticker.strip()))


@app.post("/api/crawl")
def trigger_crawl():
    """Force an immediate crawl cycle (useful right after adding a ticker)."""
    added = crawler.crawl_once()
    return {"ok": True, "new_articles": added}
