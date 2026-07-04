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
   against the full Nifty 50 plus thematic baskets (AI & IT, data centers &
   digital infrastructure, energy & power, defence), ~100 stocks in all.
   The **market scan** ranks whichever of them have news in the window by
   signal strength, per sector, and any of them can be added to the
   portfolio with one click. Index membership changes over time — the lists
   are plain data in `universe.py`, edit them there.
5. **Recommender** (`app/recommender.py`) — ratings are **valuation-led**,
   not momentum-led; "the stock surged" alone never produces a STRONG BUY.
   - **Valuation score** (60% weight, `app/fundamentals.py`): trailing/
     forward P/E vs a sector baseline (editable in `universe.SECTOR_PE`),
     analyst mean target vs price, gap to the 200-day average (stretched =
     negative), and position in the 52-week range. Components that can't be
     fetched simply drop out.
   - **News signal** (40% weight): recency-decayed (12 h half-life) average
     sentiment of *specific* coverage — headline mentions count fully,
     passing mentions 0.35×, multi-stock roundups 0.3×.
   - **Action**: combined signal ≥ 0.35 → STRONG BUY, ≥ 0.12 → BUY,
     ≤ -0.12 → SELL, ≤ -0.35 → STRONG SELL, else HOLD. When no valuation
     data resolves, the rating is news-only and **capped at BUY/SELL**.
   - **Target price**: valuation-anchored when possible — a blend of the
     analyst mean target (60%) and a sector-P/E fair value (40%), nudged
     ±3% max by news sentiment. Falls back to a signal-implied move off the
     live quote only when neither exists.
   - **Degree of recommendation**: confidence in [0, 1] blending news volume,
     agreement between articles, conviction, and whether valuation data was
     available (low / moderate / high).

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
stored in SQLite on the instance's local disk, which resets on redeploy — the
crawler simply re-populates it. For real-time NSE quotes instead of delayed
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
