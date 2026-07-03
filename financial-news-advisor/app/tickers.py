"""Ticker extraction: figure out which stocks an article is talking about."""

import re
from typing import Dict, Iterable, List, Set

# Common company-name aliases -> ticker for large caps, so articles that
# never print the symbol still get attributed. Portfolio entries add their
# own name on top of this map.
COMPANY_MAP: Dict[str, str] = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "tesla": "TSLA",
    "amazon": "AMZN", "alphabet": "GOOGL", "google": "GOOGL", "meta": "META",
    "facebook": "META", "netflix": "NFLX", "intel": "INTC", "amd": "AMD",
    "advanced micro devices": "AMD", "qualcomm": "QCOM", "broadcom": "AVGO",
    "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE", "ibm": "IBM",
    "cisco": "CSCO", "palantir": "PLTR", "uber": "UBER", "airbnb": "ABNB",
    "paypal": "PYPL", "shopify": "SHOP", "spotify": "SPOT", "zoom": "ZM",
    "snowflake": "SNOW", "coinbase": "COIN", "robinhood": "HOOD",
    "berkshire": "BRK-B", "berkshire hathaway": "BRK-B",
    "jpmorgan": "JPM", "jp morgan": "JPM", "goldman sachs": "GS",
    "goldman": "GS", "morgan stanley": "MS", "bank of america": "BAC",
    "wells fargo": "WFC", "citigroup": "C", "visa": "V", "mastercard": "MA",
    "american express": "AXP", "blackrock": "BLK",
    "exxon": "XOM", "exxonmobil": "XOM", "chevron": "CVX", "shell": "SHEL",
    "boeing": "BA", "lockheed": "LMT", "caterpillar": "CAT", "deere": "DE",
    "general electric": "GE", "general motors": "GM", "ford": "F",
    "toyota": "TM", "rivian": "RIVN", "lucid": "LCID",
    "walmart": "WMT", "target": "TGT", "costco": "COST", "home depot": "HD",
    "mcdonald's": "MCD", "mcdonalds": "MCD", "starbucks": "SBUX",
    "nike": "NKE", "disney": "DIS", "coca-cola": "KO", "coca cola": "KO",
    "pepsico": "PEP", "pepsi": "PEP", "procter & gamble": "PG",
    "johnson & johnson": "JNJ", "pfizer": "PFE", "moderna": "MRNA",
    "merck": "MRK", "eli lilly": "LLY", "lilly": "LLY", "abbvie": "ABBV",
    "unitedhealth": "UNH", "novo nordisk": "NVO",
    "taiwan semiconductor": "TSM", "tsmc": "TSM", "micron": "MU",
    "texas instruments": "TXN", "arm holdings": "ARM", "asml": "ASML",
    "dell": "DELL", "hp": "HPQ", "sony": "SONY", "samsung": "SSNLF",
    "verizon": "VZ", "at&t": "T", "t-mobile": "TMUS", "comcast": "CMCSA",
    "delta air": "DAL", "united airlines": "UAL", "american airlines": "AAL",
    "fedex": "FDX", "ups": "UPS", "marriott": "MAR",
    "openai": "MSFT",  # private; most direct public exposure
}

# Symbols that collide with everyday English words; only matched via
# cashtags ($F) or company names, never as bare uppercase words.
AMBIGUOUS_SYMBOLS: Set[str] = {
    "A", "ALL", "AN", "ANY", "ARE", "AT", "BE", "BIG", "BY", "CAN", "CEO",
    "DAY", "DO", "EPS", "ETF", "EU", "FOR", "GDP", "GO", "HAS", "HE", "IPO",
    "IT", "KEY", "LOW", "MAIN", "NEW", "NEXT", "NOW", "ON", "ONE", "OPEN",
    "OR", "OUT", "PM", "REAL", "SEE", "SHE", "SO", "TECH", "THE", "TOP",
    "TWO", "UK", "UP", "US", "USA", "WELL", "WHO", "YOU", "C", "F", "GS",
    "MA", "MS", "T", "V", "DE", "GE", "GM", "HD", "KO", "PG",
}

_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5}(?:[.\-][A-Z])?)\b")
_SYMBOL_RE = re.compile(r"\(\s*(?:NYSE|NASDAQ|Nasdaq|AMEX)?\s*:?\s*([A-Z]{1,5})\s*\)")


def extract_tickers(text: str, universe: Iterable[str], extra_names: Dict[str, str]) -> List[str]:
    """Return tickers mentioned in text.

    universe: symbols eligible for bare-word matching (e.g. portfolio).
    extra_names: extra lowercase company-name -> ticker aliases.
    """
    found: Set[str] = set()
    lower = (text or "").lower()

    for match in _CASHTAG_RE.findall(text or ""):
        found.add(match)
    for match in _SYMBOL_RE.findall(text or ""):
        found.add(match)

    names = dict(COMPANY_MAP)
    names.update(extra_names)
    for name, symbol in names.items():
        if re.search(r"\b" + re.escape(name) + r"\b", lower):
            found.add(symbol)

    for symbol in universe:
        symbol = symbol.upper()
        if symbol in found or symbol in AMBIGUOUS_SYMBOLS or len(symbol) < 2:
            continue
        if re.search(r"\b" + re.escape(symbol) + r"\b", text or ""):
            found.add(symbol)

    return sorted(found)
