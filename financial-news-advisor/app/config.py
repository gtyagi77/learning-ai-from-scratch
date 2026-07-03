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

# General market feeds polled on every cycle. Feeds that fail are skipped
# gracefully, so it is safe to list sources that occasionally go dark.
NEWS_FEEDS = [
    ("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US"),
    ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Markets", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("MarketWatch Top", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("MarketWatch Pulse", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml"),
    ("Investing.com Stocks", "https://www.investing.com/rss/news_25.rss"),
    ("Business Insider Markets", "https://markets.businessinsider.com/rss/news"),
]

# Per-ticker feed template; one of these is polled for every portfolio ticker
# so holdings always have coverage even when they miss the general feeds.
TICKER_FEED_TEMPLATE = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
)

# Tickers seeded into the portfolio on first run so the dashboard has
# something to show; the user can remove them freely.
DEFAULT_PORTFOLIO = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "Nvidia"),
    ("TSLA", "Tesla"),
]
