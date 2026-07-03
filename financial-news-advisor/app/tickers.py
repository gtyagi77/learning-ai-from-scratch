"""Ticker extraction: figure out which stocks an article is talking about.

Focused on Indian markets (NSE symbols carry Yahoo Finance's ".NS" suffix)
plus the US large caps Indian retail investors can hold through the RBI's
Liberalised Remittance Scheme (LRS).
"""

import re
from typing import Dict, Iterable, List, Set

# Indian company-name aliases -> NSE ticker (Yahoo ".NS" form). Articles in
# Indian financial media almost always print the company name, not the symbol.
INDIA_COMPANY_MAP: Dict[str, str] = {
    "reliance": "RELIANCE.NS", "reliance industries": "RELIANCE.NS",
    "jio financial": "JIOFIN.NS",
    "tcs": "TCS.NS", "tata consultancy": "TCS.NS",
    "infosys": "INFY.NS",
    "hdfc bank": "HDFCBANK.NS", "hdfc": "HDFCBANK.NS",
    "hdfc life": "HDFCLIFE.NS",
    "icici bank": "ICICIBANK.NS", "icici": "ICICIBANK.NS",
    "icici prudential": "ICICIPRULI.NS",
    "state bank of india": "SBIN.NS", "sbi": "SBIN.NS",
    "sbi life": "SBILIFE.NS",
    "kotak mahindra": "KOTAKBANK.NS", "kotak": "KOTAKBANK.NS",
    "axis bank": "AXISBANK.NS",
    "indusind": "INDUSINDBK.NS",
    "punjab national bank": "PNB.NS", "pnb": "PNB.NS",
    "bank of baroda": "BANKBARODA.NS",
    "canara bank": "CANBK.NS",
    "union bank of india": "UNIONBANK.NS",
    "federal bank": "FEDERALBNK.NS",
    "yes bank": "YESBANK.NS",
    "idfc first": "IDFCFIRSTB.NS",
    "bajaj finance": "BAJFINANCE.NS",
    "bajaj finserv": "BAJAJFINSV.NS",
    "bajaj auto": "BAJAJ-AUTO.NS",
    "muthoot": "MUTHOOTFIN.NS",
    "power finance corporation": "PFC.NS", "pfc": "PFC.NS",
    "rec ltd": "RECLTD.NS",
    "lic": "LICI.NS", "life insurance corporation": "LICI.NS",
    "bharti airtel": "BHARTIARTL.NS", "airtel": "BHARTIARTL.NS",
    "vodafone idea": "IDEA.NS",
    "itc": "ITC.NS",
    "hindustan unilever": "HINDUNILVR.NS", "hul": "HINDUNILVR.NS",
    "nestle india": "NESTLEIND.NS",
    "britannia": "BRITANNIA.NS",
    "dabur": "DABUR.NS",
    "marico": "MARICO.NS",
    "godrej consumer": "GODREJCP.NS",
    "tata consumer": "TATACONSUM.NS",
    "varun beverages": "VBL.NS",
    "colgate-palmolive india": "COLPAL.NS",
    "larsen & toubro": "LT.NS", "larsen and toubro": "LT.NS", "l&t": "LT.NS",
    "tata motors": "TATAMOTORS.NS",
    "tata steel": "TATASTEEL.NS",
    "tata power": "TATAPOWER.NS",
    "tata elxsi": "TATAELXSI.NS",
    "wipro": "WIPRO.NS",
    "hcl tech": "HCLTECH.NS", "hcltech": "HCLTECH.NS",
    "hcl technologies": "HCLTECH.NS",
    "tech mahindra": "TECHM.NS",
    "ltimindtree": "LTIM.NS",
    "persistent systems": "PERSISTENT.NS",
    "coforge": "COFORGE.NS",
    "mphasis": "MPHASIS.NS",
    "adani enterprises": "ADANIENT.NS", "adani": "ADANIENT.NS",
    "adani ports": "ADANIPORTS.NS",
    "adani power": "ADANIPOWER.NS",
    "adani green": "ADANIGREEN.NS",
    "maruti suzuki": "MARUTI.NS", "maruti": "MARUTI.NS",
    "mahindra & mahindra": "M&M.NS", "mahindra and mahindra": "M&M.NS",
    "mahindra": "M&M.NS",
    "eicher motors": "EICHERMOT.NS", "royal enfield": "EICHERMOT.NS",
    "hero motocorp": "HEROMOTOCO.NS",
    "tvs motor": "TVSMOTOR.NS",
    "ola electric": "OLAELEC.NS",
    "motherson": "MOTHERSON.NS",
    "mrf": "MRF.NS",
    "apollo tyres": "APOLLOTYRE.NS",
    "bosch india": "BOSCHLTD.NS",
    "sun pharma": "SUNPHARMA.NS",
    "cipla": "CIPLA.NS",
    "dr reddy": "DRREDDY.NS", "dr. reddy": "DRREDDY.NS",
    "divis labs": "DIVISLAB.NS", "divi's": "DIVISLAB.NS",
    "lupin": "LUPIN.NS",
    "aurobindo pharma": "AUROPHARMA.NS",
    "biocon": "BIOCON.NS",
    "zydus": "ZYDUSLIFE.NS",
    "mankind pharma": "MANKIND.NS",
    "glenmark": "GLENMARK.NS",
    "torrent pharma": "TORNTPHARM.NS",
    "apollo hospitals": "APOLLOHOSP.NS",
    "max healthcare": "MAXHEALTH.NS",
    "fortis": "FORTIS.NS",
    "asian paints": "ASIANPAINT.NS",
    "berger paints": "BERGEPAINT.NS",
    "pidilite": "PIDILITIND.NS",
    "titan company": "TITAN.NS", "titan": "TITAN.NS",
    "ultratech": "ULTRACEMCO.NS",
    "ambuja cement": "AMBUJACEM.NS", "ambuja": "AMBUJACEM.NS",
    "shree cement": "SHREECEM.NS",
    "grasim": "GRASIM.NS",
    "ntpc": "NTPC.NS",
    "ongc": "ONGC.NS",
    "power grid corporation": "POWERGRID.NS",
    "coal india": "COALINDIA.NS",
    "indian oil": "IOC.NS",
    "bharat petroleum": "BPCL.NS", "bpcl": "BPCL.NS",
    "gail india": "GAIL.NS",
    "nhpc": "NHPC.NS",
    "suzlon": "SUZLON.NS",
    "jsw steel": "JSWSTEEL.NS",
    "jindal steel": "JINDALSTEL.NS",
    "steel authority of india": "SAIL.NS",
    "nmdc": "NMDC.NS",
    "hindalco": "HINDALCO.NS",
    "vedanta": "VEDL.NS",
    "hindustan aeronautics": "HAL.NS",
    "bharat electronics": "BEL.NS",
    "bhel": "BHEL.NS",
    "irctc": "IRCTC.NS",
    "irfc": "IRFC.NS",
    "dlf": "DLF.NS",
    "macrotech": "LODHA.NS", "lodha": "LODHA.NS",
    "indigo": "INDIGO.NS", "interglobe": "INDIGO.NS",
    "indian hotels": "INDHOTEL.NS", "taj hotels": "INDHOTEL.NS",
    "zomato": "ETERNAL.NS", "blinkit": "ETERNAL.NS", "eternal ltd": "ETERNAL.NS",
    "swiggy": "SWIGGY.NS",
    "paytm": "PAYTM.NS", "one97": "PAYTM.NS",
    "nykaa": "NYKAA.NS",
    "pb fintech": "POLICYBZR.NS", "policybazaar": "POLICYBZR.NS",
    "info edge": "NAUKRI.NS", "naukri": "NAUKRI.NS",
    "delhivery": "DELHIVERY.NS",
    "avenue supermarts": "DMART.NS", "dmart": "DMART.NS",
    "trent": "TRENT.NS", "zudio": "TRENT.NS",
    "zee entertainment": "ZEEL.NS",
    "pvr inox": "PVRINOX.NS", "pvr": "PVRINOX.NS",
    "havells": "HAVELLS.NS",
    "voltas": "VOLTAS.NS",
    "blue star": "BLUESTARCO.NS",
    "polycab": "POLYCAB.NS",
    "dixon": "DIXON.NS",
    "siemens india": "SIEMENS.NS",
    "abb india": "ABB.NS",
    "cummins india": "CUMMINSIND.NS",
}

# US large caps reachable for Indian retail investors via LRS (and the odd
# global listing); articles name these companies constantly.
US_COMPANY_MAP: Dict[str, str] = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "tesla": "TSLA",
    "amazon": "AMZN", "alphabet": "GOOGL", "google": "GOOGL", "meta": "META",
    "facebook": "META", "netflix": "NFLX", "intel": "INTC", "amd": "AMD",
    "advanced micro devices": "AMD", "qualcomm": "QCOM", "broadcom": "AVGO",
    "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE", "ibm": "IBM",
    "cisco": "CSCO", "palantir": "PLTR", "uber": "UBER", "airbnb": "ABNB",
    "paypal": "PYPL", "shopify": "SHOP", "spotify": "SPOT",
    "snowflake": "SNOW", "coinbase": "COIN", "robinhood": "HOOD",
    "berkshire hathaway": "BRK-B", "berkshire": "BRK-B",
    "jpmorgan": "JPM", "jp morgan": "JPM", "goldman sachs": "GS",
    "morgan stanley": "MS", "bank of america": "BAC", "wells fargo": "WFC",
    "citigroup": "C", "visa": "V", "mastercard": "MA",
    "american express": "AXP", "blackrock": "BLK",
    "exxon": "XOM", "exxonmobil": "XOM", "chevron": "CVX",
    "boeing": "BA", "lockheed": "LMT", "caterpillar": "CAT",
    "general electric": "GE", "general motors": "GM", "ford": "F",
    "toyota": "TM", "rivian": "RIVN",
    "walmart": "WMT", "costco": "COST", "home depot": "HD",
    "mcdonald's": "MCD", "mcdonalds": "MCD", "starbucks": "SBUX",
    "nike": "NKE", "disney": "DIS", "coca-cola": "KO", "coca cola": "KO",
    "pepsico": "PEP", "procter & gamble": "PG",
    "johnson & johnson": "JNJ", "pfizer": "PFE", "moderna": "MRNA",
    "merck": "MRK", "eli lilly": "LLY", "abbvie": "ABBV",
    "unitedhealth": "UNH", "novo nordisk": "NVO",
    "taiwan semiconductor": "TSM", "tsmc": "TSM", "micron": "MU",
    "texas instruments": "TXN", "arm holdings": "ARM", "asml": "ASML",
    "verizon": "VZ", "at&t": "T", "t-mobile": "TMUS", "comcast": "CMCSA",
    "fedex": "FDX", "openai": "MSFT",  # private; most direct public exposure
}

COMPANY_MAP: Dict[str, str] = {**US_COMPANY_MAP, **INDIA_COMPANY_MAP}

# Base symbol (without .NS) -> full Yahoo symbol, used to resolve bare
# mentions like "(NSE: RELIANCE)" or user input "RELIANCE" to RELIANCE.NS.
INDIAN_BASES: Dict[str, str] = {
    sym.split(".")[0]: sym
    for sym in set(INDIA_COMPANY_MAP.values())
    if sym.endswith(".NS")
}

# Symbols that collide with everyday English words; only matched via
# cashtags ($F) or company names, never as bare uppercase words.
AMBIGUOUS_SYMBOLS: Set[str] = {
    "A", "ALL", "AN", "ANY", "ARE", "AT", "BE", "BIG", "BY", "CAN", "CEO",
    "DAY", "DO", "EPS", "ETF", "EU", "FOR", "GDP", "GO", "HAS", "HE", "IPO",
    "IT", "KEY", "LOW", "MAIN", "NEW", "NEXT", "NOW", "ON", "ONE", "OPEN",
    "OR", "OUT", "PM", "REAL", "SEE", "SHE", "SO", "TECH", "THE", "TOP",
    "TWO", "UK", "UP", "US", "USA", "WELL", "WHO", "YOU", "C", "F", "GS",
    "MA", "MS", "T", "V", "DE", "GE", "GM", "HD", "KO", "PG", "LT", "IDEA",
    "SAIL", "TRENT", "MRF", "BEL", "HAL", "GAIL", "PNB", "DLF",
}

_CASHTAG_RE = re.compile(r"\$([A-Z][A-Z0-9]{0,9}(?:[.\-][A-Z]{1,2})?)\b")
# Exchange notation like "(NSE: RELIANCE)" or "(NASDAQ: AAPL)". The exchange
# prefix is required so ordinary parenthesised words ("(IPO)") never match.
_SYMBOL_RE = re.compile(
    r"\(\s*(?:NSE|BSE|NYSE|NASDAQ|Nasdaq|AMEX)\s*:\s*([A-Z][A-Z0-9&\-]{0,14})\s*\)"
)


def resolve_symbol(symbol: str) -> str:
    """Map a bare Indian base symbol to its Yahoo .NS form (RELIANCE ->
    RELIANCE.NS); anything else passes through unchanged."""
    symbol = symbol.upper()
    if "." not in symbol and symbol in INDIAN_BASES:
        return INDIAN_BASES[symbol]
    return symbol


def extract_tickers(text: str, universe: Iterable[str], extra_names: Dict[str, str]) -> List[str]:
    """Return tickers mentioned in text.

    universe: symbols eligible for bare-word matching (e.g. portfolio).
    extra_names: extra lowercase company-name -> ticker aliases.
    """
    found: Set[str] = set()
    lower = (text or "").lower()

    for match in _CASHTAG_RE.findall(text or ""):
        found.add(resolve_symbol(match))
    for match in _SYMBOL_RE.findall(text or ""):
        found.add(resolve_symbol(match))

    names = dict(COMPANY_MAP)
    names.update(extra_names)
    for name, symbol in names.items():
        if re.search(r"\b" + re.escape(name) + r"\b", lower):
            found.add(symbol)

    for symbol in universe:
        symbol = symbol.upper()
        if symbol in found:
            continue
        base = symbol.split(".")[0]
        if base in AMBIGUOUS_SYMBOLS or len(base) < 2:
            continue
        if re.search(r"\b" + re.escape(base) + r"\b", text or ""):
            found.add(symbol)

    return sorted(found)
