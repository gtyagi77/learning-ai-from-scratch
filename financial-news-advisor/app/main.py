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
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from . import (auth, config, crawler, database, digest, financials,
               fundamentals, holdings, macro, prices, recommender, taxes,
               tickers, universe, yahoo_session)

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
    recommender.start_cache_refresh()
    digest.start(config.DIGEST_HOUR_IST)
    yield
    crawler.stop()
    recommender.stop_cache_refresh()
    digest.stop()


app = FastAPI(title="Financial News Portfolio Advisor", lifespan=lifespan)


# --------------------------------------------------------------------------
# middleware: security headers + same-origin check on state changes
# --------------------------------------------------------------------------

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin:  # browsers send it; curl/scripts don't
            origin_host = urlparse(origin).netloc
            # Accept a match against either the Host header uvicorn sees or
            # X-Forwarded-Host (the original hostname a reverse proxy — e.g.
            # Render — sets when it forwards under a different internal
            # Host), so a same-origin browser request is never wrongly
            # rejected just because of the proxy hop.
            candidates = {h for h in (request.headers.get("host"),
                                      request.headers.get("x-forwarded-host")) if h}
            if origin_host and candidates and origin_host not in candidates:
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

def _request_base(request: Request) -> str:
    """Public base URL for OAuth redirects. Only falls back to deriving it
    from the live request when OAUTH_REDIRECT_BASE was left at its localhost
    default — an explicit env var always wins (needed behind unusual
    proxies)."""
    if config.OAUTH_REDIRECT_BASE != config.OAUTH_REDIRECT_BASE_DEFAULT:
        return config.OAUTH_REDIRECT_BASE
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"


def _cookie_secure(request: Request) -> bool:
    if config.COOKIE_SECURE in ("1", "true", "yes"):
        return True
    if config.COOKIE_SECURE in ("0", "false", "no"):
        return False
    # auto: secure when served over https (directly or via proxy)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


SEEN_COOKIE = "advisor_seen"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    max_age = int(config.SESSION_TTL_DAYS * 86400)
    secure = _cookie_secure(request)
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=max_age,
                        httponly=True, samesite="lax", secure=secure, path="/")
    # Non-secret marker, readable by JS (unlike the HttpOnly session cookie)
    # so the frontend can tell "had a session, server forgot it" (e.g. a
    # free-tier restart wiped the database) apart from "never logged in".
    response.set_cookie(SEEN_COOKIE, "1", max_age=max_age,
                        httponly=False, samesite="lax", secure=secure, path="/")


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    response.delete_cookie(SEEN_COOKIE, path="/")


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


class HiddenSectorsIn(BaseModel):
    hidden: List[str]


class CreateSectorIn(BaseModel):
    name: str


class SectorMemberIn(BaseModel):
    sector: str
    ticker: str
    name: Optional[str] = None

    @field_validator("ticker")
    @classmethod
    def _valid_ticker(cls, v: str) -> str:
        return _normalize_ticker(v)


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
    _clear_session_cookies(response)
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
            "risk_profile": user.get("risk_profile", "balanced"),
            "hidden_sectors": database.get_hidden_sectors(user["id"]),
            "available_sectors": universe.sector_names(),
            "custom_sectors": database.get_custom_sectors(user["id"]), **base}


@app.post("/api/auth/profile")
def set_profile(body: ProfileIn, user: Dict = Depends(get_current_user)):
    if body.risk_profile not in recommender.RISK_PROFILES:
        raise HTTPException(status_code=400, detail="unknown risk profile")
    database.set_risk_profile(user["id"], body.risk_profile)
    return {"ok": True, "risk_profile": body.risk_profile}


@app.post("/api/sectors/hidden")
def set_hidden_sectors(body: HiddenSectorsIn, user: Dict = Depends(get_current_user)):
    known = set(universe.sector_names()) | set(database.get_custom_sectors(user["id"]))
    unknown = sorted(set(body.hidden) - known)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown sector(s): {unknown}")
    database.set_hidden_sectors(user["id"], body.hidden)
    return {"ok": True, "hidden_sectors": body.hidden}


@app.post("/api/sectors")
def create_sector(body: CreateSectorIn, user: Dict = Depends(get_current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="sector name cannot be blank")
    existing = {s.lower() for s in universe.sector_names()} | \
        {s.lower() for s in database.get_custom_sectors(user["id"])}
    if name.lower() in existing:
        raise HTTPException(status_code=400, detail=f"sector '{name}' already exists")
    database.create_custom_sector(user["id"], name)
    return {"ok": True, "name": name}


@app.delete("/api/sectors/{name}")
def delete_sector(name: str, user: Dict = Depends(get_current_user)):
    if not database.delete_custom_sector(user["id"], name):
        raise HTTPException(status_code=404, detail="not a custom sector you created")
    return {"ok": True}


@app.post("/api/sectors/members")
def add_sector_member(body: SectorMemberIn, user: Dict = Depends(get_current_user)):
    known = set(universe.sector_names()) | set(database.get_custom_sectors(user["id"]))
    if body.sector not in known:
        raise HTTPException(status_code=400,
                            detail="unknown sector — create it first")
    database.add_sector_member(user["id"], body.sector, body.ticker, body.name)
    return {"ok": True}


@app.delete("/api/sectors/members/{sector}/{ticker}")
def remove_sector_member(sector: str, ticker: str, user: Dict = Depends(get_current_user)):
    if not database.remove_sector_member(user["id"], sector, ticker):
        raise HTTPException(status_code=404, detail="not a company you added to this sector")
    return {"ok": True}


@app.get("/api/auth/google")
def google_start(request: Request):
    if not auth.google_enabled():
        raise HTTPException(status_code=404, detail="Google sign-in not configured")
    return RedirectResponse(auth.google_auth_url(_request_base(request)), status_code=302)


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not auth.google_enabled():
        raise HTTPException(status_code=404, detail="Google sign-in not configured")
    if error:  # user declined consent, or Google-side error
        return RedirectResponse(f"/?auth_error={quote(error)}", status_code=302)
    user, err = auth.google_callback(code, state, _request_base(request))
    if err:
        return RedirectResponse(f"/?auth_error={quote(err)}", status_code=302)
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
        # Whether Yahoo's crumb handshake succeeded from this host — a false
        # here (with quote_provider still "yahoo") means Yahoo is blocking
        # or challenging this host outright, not just a per-symbol miss.
        "yahoo_session_ok": yahoo_session.session_ok(),
    }


# --------------------------------------------------------------------------
# data endpoints (login required)
# --------------------------------------------------------------------------

def _normalize_ticker(v: str) -> str:
    v = v.strip().upper()
    if not _TICKER_RE.match(v):
        raise ValueError("invalid ticker symbol")
    return tickers.resolve_symbol(v)


class HoldingIn(BaseModel):
    ticker: str
    name: Optional[str] = None
    shares: Optional[float] = None
    cost_basis: Optional[float] = None

    @field_validator("ticker")
    @classmethod
    def _valid_ticker(cls, v: str) -> str:
        return _normalize_ticker(v)


class LotDateIn(BaseModel):
    buy_date: str


def _profile_for(user: Dict, override: Optional[str]) -> str:
    if override in recommender.RISK_PROFILES:
        return override
    stored = user.get("risk_profile", "balanced")
    return stored if stored in recommender.RISK_PROFILES else "balanced"


def _sectors_for_user(user_id: int):
    """Merge a user's hidden/added/custom sector preferences over the
    curated universe.SECTORS. Returns (sectors, custom_symbols, custom_names)
    for recommender.scan_universe and the /api/scan response."""
    hidden = set(database.get_hidden_sectors(user_id))
    extra = database.get_sector_members(user_id)
    custom_names = set(database.get_custom_sectors(user_id))
    sectors: Dict[str, List] = {}
    custom_symbols: Dict[str, set] = {}
    for name, members in universe.SECTORS.items():
        if name in hidden:
            continue
        added = extra.get(name, [])
        sectors[name] = members + added
        if added:
            custom_symbols[name] = {t for t, _ in added}
    for name in custom_names:
        if name not in hidden:
            sectors[name] = extra.get(name, [])
    return sectors, custom_symbols, custom_names


@app.get("/api/news")
def news(ticker: Optional[str] = None, limit: int = 40,
         relevant_only: bool = True, user: Dict = Depends(get_current_user)):
    """relevant_only (default True) drops articles that don't mention any
    tracked stock — general feeds pull in plenty of macro/economy pieces
    that name no company at all, which read as noise in a per-stock feed."""
    limit = max(1, min(limit, 200))
    fetch_limit = limit * 3 if relevant_only else limit  # over-fetch to filter
    articles = database.recent_articles(limit=fetch_limit, ticker=ticker)
    if relevant_only:
        articles = [a for a in articles if a.get("tickers")][:limit]
    return {"articles": articles}


@app.get("/api/companies/search")
def search_companies(q: str = "", user: Dict = Depends(get_current_user)):
    return {"results": tickers.search_companies(q)}


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
    """Tax-analyzed positions per ticker for a user's lots. Quotes are
    fetched concurrently -- a portfolio with dozens of tickers would
    otherwise pay each network round-trip sequentially."""
    lots = database.get_lots(user_id)
    by_ticker: Dict[str, List[Dict]] = {}
    for lot in lots:
        by_ticker.setdefault(lot["ticker"], []).append(lot)
    if not by_ticker:
        return {}
    tkrs = list(by_ticker.keys())
    with ThreadPoolExecutor(max_workers=min(10, len(tkrs))) as pool:
        quotes = list(pool.map(prices.get_quote, tkrs))
    return {
        tkr: taxes.analyze_position(tkr, by_ticker[tkr], q["price"] if q else None)
        for tkr, q in zip(tkrs, quotes)
    }


@app.get("/api/recommendations")
def recommendations(profile: Optional[str] = None,
                    user: Dict = Depends(get_current_user)):
    prof = _profile_for(user, profile)
    cached = recommender.cached_recommendations(user["id"], prof)
    recs = [dict(r) for r in cached] if cached is not None else \
        recommender.recommend_portfolio_for_user(user["id"], prof)
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
        # None means this response was computed live (no warm cache hit yet
        # for this user/profile) rather than served from the background refresh.
        "cache_age_s": recommender.cache_age_seconds(user["id"]) if cached is not None else None,
    }


@app.get("/api/holdings")
def holdings_view(user: Dict = Depends(get_current_user)):
    positions = list(_positions_for(user["id"]).values())
    positions.sort(key=lambda p: -(p["current_value"] or p["invested"] or 0))
    return {"positions": positions, "summary": taxes.portfolio_summary(positions)}


@app.post("/api/holdings/upload")
async def holdings_upload(request: Request,
                          user: Dict = Depends(get_current_user)):
    """Accepts the CSV or .xlsx as the raw request body — the dashboard
    sends the picked file directly, no multipart needed. .xlsx vs CSV is
    detected from the bytes themselves (Zerodha's Console exports default
    to .xlsx)."""
    raw = await request.body()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (1 MB max)")
    lots, fmt, errors = holdings.parse_holdings_file(raw)
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
    sectors, custom_symbols, custom_names = _sectors_for_user(user["id"])
    results = recommender.scan_universe(
        max(1, min(max_per_sector, 25)), _profile_for(user, profile),
        sectors=sectors, custom_symbols=custom_symbols)
    for s in results:
        s["is_custom"] = s["sector"] in custom_names
    return {
        "generated_at": time.time(),
        "disclaimer": (
            "Automatically generated from news, valuation, quality and macro "
            "signals for educational purposes only. Not investment advice."
        ),
        "sectors": results,
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
