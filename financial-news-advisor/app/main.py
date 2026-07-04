"""FastAPI application: JSON API + single-page dashboard, with accounts.

Security posture: every data endpoint requires a session (HttpOnly cookie);
login is rate-limited per IP; state-changing requests must come from the
same origin; responses carry restrictive security headers; passwords are
scrypt-hashed; sessions are server-side and revocable.
"""

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from . import (auth, config, crawler, database, financials, fundamentals,
               holdings, macro, prices, recommender, taxes, tickers, universe)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Accepts NSE/BSE Yahoo symbols (RELIANCE.NS, M&M.NS, BAJAJ-AUTO.NS,
# 500325.BO) as well as plain US symbols (AAPL, BRK-B).
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9&.\-]{0,19}$")

MAX_UPLOAD_BYTES = 1_000_000


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init()
    crawler.start()
    yield
    crawler.stop()


app = FastAPI(title="Financial News Portfolio Advisor", lifespan=lifespan)


# --------------------------------------------------------------------------
# middleware: security headers + same-origin check on state changes
# --------------------------------------------------------------------------

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin:  # browsers send it; curl/scripts don't
            host = urlparse(origin).netloc
            if host and host != request.headers.get("host"):
                return PlainTextResponse("cross-origin request rejected",
                                         status_code=403)
    response = await call_next(request)
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# --------------------------------------------------------------------------
# auth plumbing
# --------------------------------------------------------------------------

def _cookie_secure(request: Request) -> bool:
    if config.COOKIE_SECURE in ("1", "true", "yes"):
        return True
    if config.COOKIE_SECURE in ("0", "false", "no"):
        return False
    # auto: secure when served over https (directly or via proxy)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=int(config.SESSION_TTL_DAYS * 86400),
        httponly=True, samesite="lax", secure=_cookie_secure(request), path="/")


def get_current_user(request: Request) -> Dict:
    user = auth.user_from_token(request.cookies.get(auth.SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return user


class RegisterIn(BaseModel):
    email: str
    password: str
    username: Optional[str] = None


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    risk_profile: str


@app.post("/api/auth/register")
def register(body: RegisterIn, request: Request, response: Response):
    if auth.rate_limited(request.client.host if request.client else "?"):
        raise HTTPException(status_code=429, detail="too many attempts — try later")
    user, err = auth.register(body.email, body.password, body.username)
    if err:
        raise HTTPException(status_code=400, detail=err)
    _set_session_cookie(response, request, auth.start_session(user["id"]))
    return {"ok": True, "email": user["email"], "is_admin": bool(user["is_admin"])}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    if auth.rate_limited(request.client.host if request.client else "?"):
        raise HTTPException(status_code=429, detail="too many attempts — try later")
    user, err = auth.login(body.email, body.password)
    if err:
        raise HTTPException(status_code=401, detail=err)
    _set_session_cookie(response, request, auth.start_session(user["id"]))
    return {"ok": True, "email": user["email"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    user = auth.user_from_token(request.cookies.get(auth.SESSION_COOKIE))
    base = {"google_enabled": auth.google_enabled(),
            "signup_allowed": config.ALLOW_SIGNUP or database.count_users() == 0}
    if not user:
        return {"authenticated": False, **base}
    return {"authenticated": True, "email": user["email"],
            "username": user.get("username"), "is_admin": bool(user["is_admin"]),
            "risk_profile": user.get("risk_profile", "balanced"), **base}


@app.post("/api/auth/profile")
def set_profile(body: ProfileIn, user: Dict = Depends(get_current_user)):
    if body.risk_profile not in recommender.RISK_PROFILES:
        raise HTTPException(status_code=400, detail="unknown risk profile")
    database.set_risk_profile(user["id"], body.risk_profile)
    return {"ok": True, "risk_profile": body.risk_profile}


@app.get("/api/auth/google")
def google_start():
    if not auth.google_enabled():
        raise HTTPException(status_code=404, detail="Google sign-in not configured")
    return RedirectResponse(auth.google_auth_url(), status_code=302)


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = ""):
    if not auth.google_enabled():
        raise HTTPException(status_code=404, detail="Google sign-in not configured")
    user, err = auth.google_callback(code, state)
    if err:
        return RedirectResponse(f"/?auth_error={err}", status_code=302)
    response = RedirectResponse("/", status_code=302)
    _set_session_cookie(response, request, auth.start_session(user["id"]))
    return response


# --------------------------------------------------------------------------
# pages & public status
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# data endpoints (login required)
# --------------------------------------------------------------------------

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
        return tickers.resolve_symbol(v)


class LotDateIn(BaseModel):
    buy_date: str


def _profile_for(user: Dict, override: Optional[str]) -> str:
    if override in recommender.RISK_PROFILES:
        return override
    stored = user.get("risk_profile", "balanced")
    return stored if stored in recommender.RISK_PROFILES else "balanced"


@app.get("/api/news")
def news(ticker: Optional[str] = None, limit: int = 40,
         user: Dict = Depends(get_current_user)):
    limit = max(1, min(limit, 200))
    return {"articles": database.recent_articles(limit=limit, ticker=ticker)}


@app.get("/api/portfolio")
def portfolio(user: Dict = Depends(get_current_user)):
    return {"holdings": database.get_portfolio(user["id"])}


@app.post("/api/portfolio")
def add_holding(holding: HoldingIn, user: Dict = Depends(get_current_user)):
    database.upsert_holding(holding.ticker, holding.name, holding.shares,
                            holding.cost_basis, user_id=user["id"])
    return {"ok": True, "ticker": holding.ticker}


@app.delete("/api/portfolio/{ticker}")
def delete_holding(ticker: str, user: Dict = Depends(get_current_user)):
    if not database.remove_holding(ticker, user_id=user["id"]):
        raise HTTPException(status_code=404, detail="ticker not in portfolio")
    return {"ok": True}


def _positions_for(user_id: int) -> Dict[str, Dict]:
    """Tax-analyzed positions per ticker for a user's lots."""
    out: Dict[str, Dict] = {}
    lots = database.get_lots(user_id)
    by_ticker: Dict[str, List[Dict]] = {}
    for lot in lots:
        by_ticker.setdefault(lot["ticker"], []).append(lot)
    for tkr, tlots in by_ticker.items():
        quote = prices.get_quote(tkr)
        out[tkr] = taxes.analyze_position(tkr, tlots,
                                          quote["price"] if quote else None)
    return out


@app.get("/api/recommendations")
def recommendations(profile: Optional[str] = None,
                    user: Dict = Depends(get_current_user)):
    prof = _profile_for(user, profile)
    recs = recommender.recommend_portfolio_for_user(user["id"], prof)
    positions = _positions_for(user["id"])
    for rec in recs:
        pos = positions.get(rec["ticker"])
        if pos:
            action, note = taxes.tax_adjust_action(
                rec["action"], rec.get("implied_move_pct"), pos)
            rec["action"] = action
            rec["tax_note"] = note
            rec["position"] = {k: pos[k] for k in (
                "quantity", "avg_cost", "invested", "current_value",
                "unrealized_gain", "unrealized_gain_pct", "st_quantity",
                "lt_quantity", "tax_if_sold_today", "after_tax_value",
                "next_lt_date", "next_lt_days", "tax_saved_by_waiting")}
            if note:
                rec["rationale"] += " " + note
    return {
        "generated_at": time.time(),
        "disclaimer": (
            "Automatically generated from news, valuation, quality and macro "
            "signals for educational purposes only. Not investment or tax advice."
        ),
        "risk_profile": prof,
        "recommendations": recs,
    }


@app.get("/api/holdings")
def holdings_view(user: Dict = Depends(get_current_user)):
    positions = list(_positions_for(user["id"]).values())
    positions.sort(key=lambda p: -(p["current_value"] or p["invested"] or 0))
    return {"positions": positions, "summary": taxes.portfolio_summary(positions)}


@app.post("/api/holdings/upload")
async def holdings_upload(request: Request,
                          user: Dict = Depends(get_current_user)):
    """Accepts the CSV as the raw request body (text/csv) — the dashboard
    sends the picked file directly, no multipart needed."""
    raw = await request.body()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (1 MB max)")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="file is not UTF-8 text/CSV")
    lots, fmt, errors = holdings.parse_csv(content)
    if not lots and errors:
        raise HTTPException(status_code=400, detail="; ".join(errors[:5]))
    result = holdings.import_lots(user["id"], lots, source=fmt)
    return {"ok": True, "format": fmt, **result, "warnings": errors}


@app.get("/api/holdings/template")
def holdings_template():
    return PlainTextResponse(holdings.GENERIC_TEMPLATE, media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=holdings_template.csv"})


@app.delete("/api/holdings/{lot_id}")
def delete_lot(lot_id: int, user: Dict = Depends(get_current_user)):
    if not database.delete_lot(lot_id, user["id"]):
        raise HTTPException(status_code=404, detail="lot not found")
    return {"ok": True}


@app.post("/api/holdings/{lot_id}/date")
def set_lot_date(lot_id: int, body: LotDateIn,
                 user: Dict = Depends(get_current_user)):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.buy_date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if not database.update_lot_date(lot_id, user["id"], body.buy_date):
        raise HTTPException(status_code=404, detail="lot not found")
    return {"ok": True}


@app.get("/api/macro")
def macro_view(user: Dict = Depends(get_current_user)):
    return {
        "generated_at": time.time(),
        "indicators": macro.get_indicators(),
        "sector_tilts": macro.sector_tilts(),
    }


@app.get("/api/stock/{ticker}")
def stock_detail(ticker: str, profile: Optional[str] = None,
                 user: Dict = Depends(get_current_user)):
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="invalid ticker symbol")
    ticker = tickers.resolve_symbol(ticker)
    rec = recommender.recommend_for_ticker(ticker, universe.WATCHLIST.get(ticker),
                                           risk_profile=_profile_for(user, profile))
    fin = financials.get_financials(ticker) or {}
    history = fundamentals.get_history(ticker) or {}
    return {
        "recommendation": rec,
        "financials": {k: fin.get(k) for k in (
            "source", "annual", "quarterly", "roe_pct", "roce_pct",
            "debt_to_equity", "stock_pe", "book_value", "rev_cagr_3y_pct",
            "profit_cagr_3y_pct", "pros", "cons")},
        "history": history,
    }


@app.get("/api/scan")
def scan(max_per_sector: int = 10, profile: Optional[str] = None,
         user: Dict = Depends(get_current_user)):
    return {
        "generated_at": time.time(),
        "disclaimer": (
            "Automatically generated from news, valuation, quality and macro "
            "signals for educational purposes only. Not investment advice."
        ),
        "sectors": recommender.scan_universe(max(1, min(max_per_sector, 25)),
                                             _profile_for(user, profile)),
    }


@app.get("/api/recommendations/{ticker}")
def recommendation(ticker: str, user: Dict = Depends(get_current_user)):
    if not _TICKER_RE.match(ticker.strip()):
        raise HTTPException(status_code=400, detail="invalid ticker symbol")
    return recommender.recommend_for_ticker(
        tickers.resolve_symbol(ticker.strip()),
        risk_profile=_profile_for(user, None))


@app.post("/api/crawl")
def trigger_crawl(user: Dict = Depends(get_current_user)):
    added = crawler.crawl_once()
    return {"ok": True, "new_articles": added}
