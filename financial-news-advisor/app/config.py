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

# Per-ticker feed template; one of these is polled for every portfolio ticker
# so holdings always have coverage even when they miss the general feeds.
# Works for NSE/BSE symbols (RELIANCE.NS, 500325.BO) and US symbols alike.
TICKER_FEED_TEMPLATE = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=IN&lang=en-IN"
)

# Tickers seeded into the portfolio on first run so the dashboard has
# something to show; the user can remove them freely. NSE symbols use the
# Yahoo Finance ".NS" suffix; AAPL is included as a US-via-LRS example.
DEFAULT_PORTFOLIO = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("TCS.NS", "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("INFY.NS", "Infosys"),
    ("TATAMOTORS.NS", "Tata Motors"),
    ("AAPL", "Apple"),
]
