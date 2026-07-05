# Financial News Portfolio Advisor — India

A self-hosted site that crawls financial news in (near) real time and turns it
into portfolio recommendations — an action (STRONG BUY → STRONG SELL), a
**degree of recommendation** (confidence %), and a **news-implied target
price** for every holding.

Focused on **Indian markets**: NSE/BSE stocks quoted in ₹, Indian financial
news sources (Economic Times, Moneycontrol, LiveMint, Business Standard,
BusinessLine, Financial Express, NDTV Profit) plus Google News per holding,
and US stocks — which Indian retail investors can hold through the RBI's
Liberalised Remittance Scheme (LRS) — covered via CNBC and MarketWatch.

### Data sources are pluggable

Both external dependencies are swappable via environment variables, so you
can trade the zero-config defaults for higher-quality official data:

| | env var | options |
|---|---|---|
| **Per-holding news** | `TICKER_NEWS_PROVIDER` | `google` (default — Google News RSS by company name, deep Indian coverage, keyless), `yahoo` (per-ticker feed), `none` |
| **Live quotes** | `QUOTE_PROVIDER` | `yahoo` (default — keyless, NSE/BSE/US in one API, ~15 min delayed), `upstox` (free, real-time NSE/BSE), `angelone` (free, real-time) |

Yahoo is the default only because it is the one keyless API spanning
NSE+BSE+US; it is unofficial and increasingly rate-limited. Any symbol a
broker can't price (e.g. US holdings) falls back to Yahoo automatically, so
the app always keeps working.

#### Real-time NSE quotes via Upstox (~10 min, free)

1. Open a free Upstox account if you don't have one, then create a developer
   app at <https://account.upstox.com/developer/apps>. Set its **Redirect
   URL** to `https://127.0.0.1` and note the **API Key** and **API Secret**.
2. Get an access token — the helper walks you through the browser login:
   ```bash
   python scripts/get_upstox_token.py
   ```
3. Set the environment variables where the app runs:
   ```
   QUOTE_PROVIDER=upstox
   UPSTOX_ACCESS_TOKEN=<from step 2>
   ```
   On Render: service → **Environment** tab → add both → Save (auto-redeploys).
4. Instrument keys resolve automatically: on first use the app downloads
   Upstox's public instrument list and maps `RELIANCE.NS`-style symbols to
   instrument keys itself. To pin the map instead (offline/faster startup):
   `python scripts/build_instrument_map.py --provider upstox` and set
   `INSTRUMENT_MAP_PATH=instruments.json`.

**Caveat:** Upstox access tokens expire daily (~3:30 AM IST), so re-run step
2 each trading day and update the env var. Angel One works the same way
(`QUOTE_PROVIDER=angelone`, `ANGELONE_API_KEY` + `ANGELONE_ACCESS_TOKEN`,
`--provider angelone` for the map script).

> ⚠ **Educational project only.** The recommendations are derived from a
> hand-rolled sentiment model over public news headlines. They are not
> investment advice.

## How it works

```
RSS feeds ──▶ crawler (poll every 2 min) ──▶ sentiment scoring ──▶ SQLite
 (Yahoo, CNBC,      dedupe by link            from-scratch          articles
  MarketWatch, …)   ticker extraction         finance lexicon
                                                                       │
browser ◀── FastAPI dashboard ◀── recommender (recency-weighted    ◀───┘
            (auto-refresh 60s)     signal + confidence + target)
                                        ▲
                          Yahoo quote API (current price)
```

1. **Crawler** (`app/crawler.py`) polls ~17 market RSS feeds (14 Indian
   incl. ET Tech/Energy/Defence, 3 US/global) plus a per-holding news feed
   (Google News by default) for every portfolio holding, every 2 minutes.
   The RSS/Atom parser (`app/rss.py`) is written from scratch on the standard
   library and tolerates the stray non-XML entities some feeds emit.
2. **Sentiment** (`app/sentiment.py`) is a dependency-free, Loughran-McDonald
   style financial lexicon with negation handling, intensifiers, and
   India-market vocabulary (FII outflows, NPAs, IPO subscription). Each
   article gets a score in [-1, 1], headline weighted over summary.
3. **Ticker extraction** (`app/tickers.py`) attributes articles to symbols via
   exchange notation (`(NSE: RELIANCE)`, `(NASDAQ: AAPL)`), cashtags, and a
   company-name map of ~170 NSE names and ~80 US large caps. Bare NSE symbols
   are resolved to Yahoo's `.NS` form (`RELIANCE` → `RELIANCE.NS`); BSE codes
   use `.BO`.
4. **Watch universe** (`app/universe.py`) — every crawl attributes news
   against the full Nifty 50 plus thematic baskets: **AI & Emerging Tech**
   (product/data-led companies — LatentView, Tata Elxsi, KPIT, Affle, Netweb,
   Zensar, Happiest Minds, Tanla), **IT Services** (the large headcount-billed
   outsourcing majors — TCS, Infosys, Wipro, HCLTech, etc. — kept separate so
   the AI basket isn't dominated by them), data centers & digital
   infrastructure, energy & power, and defence — ~100 stocks in all.
   The **market scan** ranks whichever of them have news in the window by
   signal strength, per sector, and any of them can be added to the
   portfolio with one click. Index membership changes over time — the lists
   are plain data in `universe.py`, edit them there.
5. **Recommender** (`app/recommender.py`) — ratings blend four components,
   weighted by your risk profile (balanced 35/25/25/15, conservative,
   aggressive), renormalized over whatever data resolves:
   - **Value**: trailing/forward P/E vs a sector baseline (editable in
     `universe.SECTOR_PE`; screener's Stock P/E backfills Yahoo's gated
     P/E), analyst mean target & range, street consensus rating, gap to the
     200-day average, 52-week range position.
   - **Quality** (`app/financials.py` + `app/screener.py`): ROE,
     debt-to-equity (computed from the balance sheet; skipped for
     banks/NBFCs), revenue & net-profit 3-year CAGR, operating-margin
     trend, latest-quarter sales YoY. Primary source is **screener.in**
     (public pages, 24h cache, ≥1.5s pacing, robots.txt honored) with Yahoo
     fallback — see the ToS note in `app/screener.py`.
   - **News**: recency-decayed (12h half-life) sentiment of *specific*
     coverage — headline mentions 1.0, passing mentions 0.35×, roundups 0.3×.
   - **Macro** (`app/macro.py`): sector-sensitivity tilt from the Nifty
     trend, USD/INR, Brent crude and India VIX (weak rupee helps IT
     exporters; crude up helps ONGC, hurts OMCs), share capped at 25%.
   - **Guards**: STRONG ratings need both value and quality data; news-only
     ratings are capped at BUY/SELL; a rating that contradicts its own
     valuation-anchored target is moderated to HOLD.
   - **Time frames**: every recommendation carries dated horizons — Short
     (1 month, news momentum), Medium (3 months, valuation mean-reversion +
     macro), Long (12 months, analyst target / growth) — plus a strategy
     block: entry approach, stop-loss, profit-booking level, position-size
     hint, review triggers.
   - Per-stock detail view: 1-year price chart with 50/200-day averages,
     ~10 years of revenue & net profit, quarterly trend, key ratios, and
     screener's pros/cons.

## Accounts, holdings & tax

The site requires a login: register with email + password on first visit
(the first account becomes admin; set `ALLOW_SIGNUP=0` afterwards to close
registration). Each user has their own portfolio, holdings, risk profile and
recommendations. Security: scrypt-hashed passwords, revocable server-side
sessions in HttpOnly/SameSite cookies, per-IP login rate-limiting,
same-origin checks on writes, and restrictive security headers.

**Google sign-in (optional):** create an OAuth client at
console.cloud.google.com → Credentials, set the redirect URI to
`https://<your-host>/api/auth/google/callback`, then set `GOOGLE_CLIENT_ID`
and `GOOGLE_CLIENT_SECRET` env vars. The "Continue with Google" button
appears automatically. The callback URL is derived from the incoming
request's own host/scheme by default, so `OAUTH_REDIRECT_BASE` normally
does **not** need setting — only override it if the app sits behind a proxy
that changes the public hostname (uncommon). Leaving it at its localhost
default while deployed is the #1 cause of `redirect_uri_mismatch` errors
from Google, and is no longer a way you can get bitten by that.

**Dashboard layout:** four tabs — **Portfolio** (add tickers, recommendation
cards, risk profile), **Holdings** (CSV upload, P&L, tax), **Market Scan**
(sector baskets), **News** (defaults to articles that mention a tracked
stock; check "Show all market news" to also see untagged macro/economy
pieces). The macro strip stays visible above all tabs.

**Holdings upload:** upload your broker CSV (Zerodha holdings or tradebook,
Groww, Upstox) or the downloadable generic template
(`symbol,quantity,buy_price,buy_date`). Tradebook uploads net buys/sells
FIFO into surviving lots with accurate dates. The dashboard then shows
per-position P&L and Indian capital-gains analysis: short/long-term split,
tax if sold today (STCG 20% ≤ 1 year, LTCG 12.5% beyond with the ₹1.25 lakh
per-FY exemption applied at portfolio level), days until lots turn
long-term, and tax saved by waiting. **SELL calls are tax-moderated**: if
waiting ≤ 60 days for LTCG saves more than the expected downside, the call
becomes HOLD with a dated explanation. Not tax advice; grandfathering
(pre-2018 purchases) is out of scope.

## Run it

```bash
pip install -r requirements.txt
python run.py            # serves http://127.0.0.1:8000
```

### Or run it in Docker

```bash
docker build -t advisor .
docker run -p 8000:8000 advisor        # serves http://127.0.0.1:8000
```

## Host it (get a public URL)

The app is a live backend (it crawls news continuously), so it needs a host
that runs a process, not static file hosting. It ships with a `Dockerfile`
and a Render Blueprint (`render.yaml` at the repo root) for a free deploy.

**Render (free tier, ~3 min):**

1. Push this repo to GitHub (already done for the working branch).
2. In the [Render dashboard](https://dashboard.render.com/) choose
   **New + → Blueprint**, pick this repo, and select the branch to deploy.
   Render reads `render.yaml`, builds the Docker image, and gives you a
   public `https://…onrender.com` URL.
3. Open the URL. The crawler starts immediately; first recommendations
   appear within a minute.

Once `render.yaml` is on your default branch you can also use a one-click
button — add this to point at your fork:
`https://render.com/deploy?repo=https://github.com/gtyagi77/learning-ai-from-scratch`

**Notes for the free tier:** the instance spins down after ~15 min idle, so
the first hit after a pause takes ~30–60 s to wake (cold start). Data is
stored in SQLite on the instance's local disk, which resets on redeploy —
news re-populates automatically, but **user accounts and uploaded holdings
are wiped too**. For a real multi-user deployment attach a persistent disk
(paid Render feature) and point `DB_PATH` at it, or re-register/re-upload
after each deploy. For real-time NSE quotes instead of delayed
Yahoo data, set `QUOTE_PROVIDER=upstox` (or `angelone`) plus the token env
vars in the Render service settings. The same image runs on Railway, Fly.io,
or Google Cloud Run — anything that runs a container and sets `$PORT`.

The dashboard seeds a demo portfolio (Reliance, TCS, HDFC Bank, Infosys,
Tata Motors, and Apple as a US-via-LRS example) on first run — add/remove
your own tickers from the UI. NSE quotes render in ₹ with Indian digit
grouping. Data persists in `advisor.db`.

## API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard |
| `GET /api/recommendations` | Action + confidence + target price per holding |
| `GET /api/scan` | Same signals across the whole watch universe, grouped by sector |
| `GET /api/macro` | Macro indicators (Nifty, USD/INR, Brent, India VIX) + sector tilts |
| `GET /api/stock/{ticker}` | Detail: recommendation, financial history, price history w/ DMAs |
| `GET /api/recommendations/{ticker}` | Same for any single ticker |
| `GET /api/news?ticker=&limit=` | Crawled articles with sentiment |
| `GET /api/portfolio` / `POST /api/portfolio` / `DELETE /api/portfolio/{t}` | Manage holdings |
| `POST /api/crawl` | Force an immediate crawl cycle |
| `GET /api/status` | Crawler health/stats |

Configuration is via environment variables (see `app/config.py`):
`TICKER_NEWS_PROVIDER`, `QUOTE_PROVIDER` (+ broker creds), `CRAWL_INTERVAL_SECONDS`,
`LOOKBACK_HOURS`, `RECENCY_HALF_LIFE_HOURS`, `MAX_IMPLIED_MOVE`, `DB_PATH`.

## Tests

```bash
python -m pytest tests/ -q
```
