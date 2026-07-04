"""Central configuration for the financial news advisor."""

import os

# How often the crawler polls all feeds (seconds).
CRAWL_INTERVAL_SECONDS = int(os.environ.get("CRAWL_INTERVAL_SECONDS", "120"))

# How far back news is considered when scoring a ticker (hours).
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS", "48"))

# Half-life used to decay the weight of older articles (hours).
RECENCY_HALF_LIFE_HOURS = float(os.environ.get("RECENCY_HALF_LIFE_HOURS", "12"))

# Maximum short-horizon move implied by a maximally positive/negative
# news signal, used when deriving a target price from the sentiment score.
MAX_IMPLIED_MOVE = float(os.environ.get("MAX_IMPLIED_MOVE", "0.10"))

# Quote cache TTL (seconds).
PRICE_CACHE_TTL_SECONDS = int(os.environ.get("PRICE_CACHE_TTL_SECONDS", "300"))

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "advisor.db"),
)

# ---- accounts & security ----
# Signup open by default (first registered user becomes admin); set
# ALLOW_SIGNUP=0 after creating your account to close registration.
ALLOW_SIGNUP = os.environ.get("ALLOW_SIGNUP", "1") not in ("0", "false", "no")
SESSION_TTL_DAYS = float(os.environ.get("SESSION_TTL_DAYS", "30"))
# Google sign-in (optional): create an OAuth client in Google Cloud Console
# with redirect URI {OAUTH_REDIRECT_BASE}/api/auth/google/callback.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
OAUTH_REDIRECT_BASE = os.environ.get("OAUTH_REDIRECT_BASE", "http://127.0.0.1:8000")
# Cookies marked Secure only when served over https (Render terminates TLS).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto")

# ---- Indian capital gains tax (listed equity, STT paid) ----
TAX_STCG_RATE = float(os.environ.get("TAX_STCG_RATE", "0.20"))     # <= 12 months
TAX_LTCG_RATE = float(os.environ.get("TAX_LTCG_RATE", "0.125"))    # > 12 months
TAX_LTCG_EXEMPTION = float(os.environ.get("TAX_LTCG_EXEMPTION", "125000"))  # per FY
TAX_LT_DAYS = int(os.environ.get("TAX_LT_DAYS", "365"))

HTTP_TIMEOUT_SECONDS = 15
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 FinancialNewsAdvisor/1.0"
)

# General market feeds polled on every cycle, focused on Indian markets.
# A few US/global feeds are kept because Indian retail investors can hold
# US stocks through the RBI's Liberalised Remittance Scheme (LRS).
# Feeds that fail are skipped gracefully, so it is safe to list sources
# that occasionally go dark.
NEWS_FEEDS = [
    # --- India ---
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol Buzzing", "https://www.moneycontrol.com/rss/buzzingstocks.xml"),
    ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml"),
    ("LiveMint Markets", "https://www.livemint.com/rss/markets"),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss"),
    ("BusinessLine Markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    ("Financial Express Markets", "https://www.financialexpress.com/market/feed/"),
    ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
    ("Yahoo Nifty 50", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5ENSEI&region=IN&lang=en-IN"),
    # Sector feeds for the thematic scan (AI/tech, energy, defence).
    ("ET Tech", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"),
    ("ET Energy", "https://economictimes.indiatimes.com/industry/energy/rssfeeds/13358361.cms"),
    ("ET Defence", "https://economictimes.indiatimes.com/news/defence/rssfeeds/44580387.cms"),
    # --- US / global (accessible to Indian retail via LRS) ---
    ("Yahoo S&P 500", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US"),
    ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch Top", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
]

# Per-holding news provider. Each portfolio holding gets its own feed so it
# always has coverage even when it misses the general feeds.
#   "google" (default) — Google News RSS search by company name; far deeper
#                        Indian coverage than Yahoo's per-ticker feed, still
#                        keyless. Queried by name, falling back to symbol.
#   "yahoo"            — Yahoo Finance per-ticker headline feed (by symbol).
#   "none"            — rely only on the general + sector feeds above.
TICKER_NEWS_PROVIDER = os.environ.get("TICKER_NEWS_PROVIDER", "google").lower()

# Google News RSS search. {query} is URL-encoded at call time; hl/gl/ceid
# pin results to the India/English edition.
GOOGLE_NEWS_TEMPLATE = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)

# Yahoo per-ticker feed (used when TICKER_NEWS_PROVIDER == "yahoo").
YAHOO_TICKER_FEED_TEMPLATE = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=IN&lang=en-IN"
)

# Quote provider for live prices (used to derive target prices).
#   "yahoo" (default) — Yahoo Finance chart endpoint; keyless, covers
#                       NSE/BSE/US in one API, delayed ~15 min, unofficial.
#   "upstox"          — Upstox market-quote API (free, real-time NSE/BSE);
#                       needs UPSTOX_ACCESS_TOKEN.
#   "angelone"        — Angel One SmartAPI (free, real-time); needs
#                       ANGELONE_API_KEY / ANGELONE_ACCESS_TOKEN.
# Providers that need credentials fall back to Yahoo when unconfigured.
QUOTE_PROVIDER = os.environ.get("QUOTE_PROVIDER", "yahoo").lower()
UPSTOX_ACCESS_TOKEN = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
ANGELONE_API_KEY = os.environ.get("ANGELONE_API_KEY", "")
ANGELONE_ACCESS_TOKEN = os.environ.get("ANGELONE_ACCESS_TOKEN", "")

# Tickers seeded into the portfolio on first run so the dashboard has
# something to show; the user can remove them freely. All-Indian defaults —
# NSE symbols carry the ".NS" suffix used by market-data APIs (".BO" = BSE).
# US stocks (e.g. AAPL, held via LRS) are still supported when added manually.
DEFAULT_PORTFOLIO = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("TCS.NS", "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("INFY.NS", "Infosys"),
    ("TATAMOTORS.NS", "Tata Motors"),
    ("HAL.NS", "Hindustan Aeronautics"),
]
