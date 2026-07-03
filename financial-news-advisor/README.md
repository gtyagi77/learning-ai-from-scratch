# Financial News Portfolio Advisor

A self-hosted site that crawls financial news in (near) real time and turns it
into portfolio recommendations — an action (STRONG BUY → STRONG SELL), a
**degree of recommendation** (confidence %), and a **news-implied target
price** for every holding.

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

1. **Crawler** (`app/crawler.py`) polls ~8 general market RSS feeds plus one
   Yahoo Finance per-ticker feed for every portfolio holding, every 2 minutes.
   The RSS/Atom parser (`app/rss.py`) is written from scratch on the standard
   library.
2. **Sentiment** (`app/sentiment.py`) is a dependency-free, Loughran-McDonald
   style financial lexicon with negation handling and intensifiers. Each
   article gets a score in [-1, 1], headline weighted over summary.
3. **Ticker extraction** (`app/tickers.py`) attributes articles to symbols via
   cashtags (`$AAPL`), exchange notation (`(NASDAQ: AAPL)`), a company-name
   map (~100 large caps), and portfolio symbols.
4. **Recommender** (`app/recommender.py`) combines the last 48 h of articles
   per ticker with exponential recency decay (12 h half-life) into one signal,
   then:
   - **Action**: signal ≥ 0.35 → STRONG BUY, ≥ 0.12 → BUY, ≤ -0.12 → SELL,
     ≤ -0.35 → STRONG SELL, otherwise HOLD.
   - **Degree of recommendation**: confidence in [0, 1] blending news volume,
     agreement between articles, and signal conviction (shown as
     low / moderate / high).
   - **Target price**: `current × (1 + signal × 10% × (0.4 + 0.6 × confidence))`
     — i.e. maximally positive, high-confidence news implies ≈ +10% over the
     short horizon. Live quotes come from Yahoo Finance's public chart API.

## Run it

```bash
pip install -r requirements.txt
python run.py            # serves http://127.0.0.1:8000
```

The dashboard seeds a demo portfolio (AAPL, MSFT, NVDA, TSLA) on first run —
add/remove your own tickers from the UI. Data persists in `advisor.db`.

## API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard |
| `GET /api/recommendations` | Action + confidence + target price per holding |
| `GET /api/recommendations/{ticker}` | Same for any single ticker |
| `GET /api/news?ticker=&limit=` | Crawled articles with sentiment |
| `GET /api/portfolio` / `POST /api/portfolio` / `DELETE /api/portfolio/{t}` | Manage holdings |
| `POST /api/crawl` | Force an immediate crawl cycle |
| `GET /api/status` | Crawler health/stats |

Configuration is via environment variables (see `app/config.py`):
`CRAWL_INTERVAL_SECONDS`, `LOOKBACK_HOURS`, `RECENCY_HALF_LIFE_HOURS`,
`MAX_IMPLIED_MOVE`, `DB_PATH`.

## Tests

```bash
python -m pytest tests/ -q
```
