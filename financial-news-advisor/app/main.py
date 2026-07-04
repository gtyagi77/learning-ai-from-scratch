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

from . import (config, crawler, database, financials, fundamentals, macro,
               prices, recommender, tickers, universe)

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
        "universe_size": len(universe.WATCHLIST),
        "news_provider": config.TICKER_NEWS_PROVIDER,
        "quote_provider": prices.active_provider(),
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


def _profile(profile: Optional[str]) -> str:
    return profile if profile in recommender.RISK_PROFILES else "balanced"


@app.get("/api/recommendations")
def recommendations(profile: Optional[str] = None):
    return {
        "generated_at": time.time(),
        "disclaimer": (
            "Automatically generated from news, valuation, quality and macro "
            "signals for educational purposes only. Not investment or tax advice."
        ),
        "risk_profile": _profile(profile),
        "recommendations": recommender.recommend_portfolio(_profile(profile)),
    }


@app.get("/api/macro")
def macro_view():
    return {
        "generated_at": time.time(),
        "indicators": macro.get_indicators(),
        "sector_tilts": macro.sector_tilts(),
    }


@app.get("/api/stock/{ticker}")
def stock_detail(ticker: str, profile: Optional[str] = None):
    """Everything for the detail view: recommendation, financial history,
    price history with moving averages."""
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="invalid ticker symbol")
    ticker = tickers.resolve_symbol(ticker)
    rec = recommender.recommend_for_ticker(ticker, universe.WATCHLIST.get(ticker),
                                           risk_profile=_profile(profile))
    fin = financials.get_financials(ticker) or {}
    history = fundamentals.get_history(ticker) or {}
    return {
        "recommendation": rec,
        "financials": {
            "source": fin.get("source"),
            "annual": fin.get("annual"),
            "quarterly": fin.get("quarterly"),
            "roe_pct": fin.get("roe_pct"),
            "roce_pct": fin.get("roce_pct"),
            "debt_to_equity": fin.get("debt_to_equity"),
            "stock_pe": fin.get("stock_pe"),
            "book_value": fin.get("book_value"),
            "rev_cagr_3y_pct": fin.get("rev_cagr_3y_pct"),
            "profit_cagr_3y_pct": fin.get("profit_cagr_3y_pct"),
            "pros": fin.get("pros"),
            "cons": fin.get("cons"),
        },
        "history": history,
    }


@app.get("/api/scan")
def scan(max_per_sector: int = 10, profile: Optional[str] = None):
    """News-driven signals across the whole watch universe (Nifty 50 plus
    the AI/IT, data center, energy and defence baskets), grouped by sector."""
    return {
        "generated_at": time.time(),
        "disclaimer": (
            "Automatically generated from news, valuation, quality and macro "
            "signals for educational purposes only. Not investment advice."
        ),
        "sectors": recommender.scan_universe(max(1, min(max_per_sector, 25)),
                                             _profile(profile)),
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
