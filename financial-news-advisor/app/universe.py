"""The watch universe scanned on every cycle, beyond the user's portfolio.

Nifty 50 constituents plus thematic baskets Indian retail investors track
closely: AI & emerging tech, IT services, data centers & digital
infrastructure, energy & power, and defence. AI and IT services are
deliberately separate baskets — the AI basket is product/data-led companies,
not the large headcount-billed outsourcing majors. Symbols use Yahoo Finance
form (.NS = NSE). Index membership changes a couple of times a year — edit
the lists here to keep them fresh. A ticker may appear in several sectors
(e.g. Reliance in energy and data centers); the scanner dedupes the
underlying analysis.
"""

from typing import Dict, List, Tuple

NIFTY_50: List[Tuple[str, str]] = [
    ("ADANIENT.NS", "Adani Enterprises"),
    ("ADANIPORTS.NS", "Adani Ports"),
    ("APOLLOHOSP.NS", "Apollo Hospitals"),
    ("ASIANPAINT.NS", "Asian Paints"),
    ("AXISBANK.NS", "Axis Bank"),
    ("BAJAJ-AUTO.NS", "Bajaj Auto"),
    ("BAJFINANCE.NS", "Bajaj Finance"),
    ("BAJAJFINSV.NS", "Bajaj Finserv"),
    ("BEL.NS", "Bharat Electronics"),
    ("BHARTIARTL.NS", "Bharti Airtel"),
    ("CIPLA.NS", "Cipla"),
    ("COALINDIA.NS", "Coal India"),
    ("DRREDDY.NS", "Dr Reddy's Labs"),
    ("EICHERMOT.NS", "Eicher Motors"),
    ("ETERNAL.NS", "Eternal (Zomato)"),
    ("GRASIM.NS", "Grasim Industries"),
    ("HCLTECH.NS", "HCL Technologies"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("HDFCLIFE.NS", "HDFC Life"),
    ("HEROMOTOCO.NS", "Hero MotoCorp"),
    ("HINDALCO.NS", "Hindalco"),
    ("HINDUNILVR.NS", "Hindustan Unilever"),
    ("ICICIBANK.NS", "ICICI Bank"),
    ("INDUSINDBK.NS", "IndusInd Bank"),
    ("INFY.NS", "Infosys"),
    ("ITC.NS", "ITC"),
    ("JIOFIN.NS", "Jio Financial"),
    ("JSWSTEEL.NS", "JSW Steel"),
    ("KOTAKBANK.NS", "Kotak Mahindra Bank"),
    ("LT.NS", "Larsen & Toubro"),
    ("M&M.NS", "Mahindra & Mahindra"),
    ("MARUTI.NS", "Maruti Suzuki"),
    ("NESTLEIND.NS", "Nestle India"),
    ("NTPC.NS", "NTPC"),
    ("ONGC.NS", "ONGC"),
    ("POWERGRID.NS", "Power Grid Corporation"),
    ("RELIANCE.NS", "Reliance Industries"),
    ("SBILIFE.NS", "SBI Life"),
    ("SBIN.NS", "State Bank of India"),
    ("SHRIRAMFIN.NS", "Shriram Finance"),
    ("SUNPHARMA.NS", "Sun Pharma"),
    ("TATACONSUM.NS", "Tata Consumer"),
    ("TATAMOTORS.NS", "Tata Motors"),
    ("TATASTEEL.NS", "Tata Steel"),
    ("TCS.NS", "Tata Consultancy Services"),
    ("TECHM.NS", "Tech Mahindra"),
    ("TITAN.NS", "Titan Company"),
    ("TRENT.NS", "Trent"),
    ("ULTRACEMCO.NS", "UltraTech Cement"),
    ("WIPRO.NS", "Wipro"),
]

# Genuine AI / analytics / emerging-tech plays — deliberately excludes the
# large staffing-model IT services firms (those are their own basket below),
# so this reflects companies whose business is AI/data/product-led rather
# than headcount-billed services.
AI_AND_EMERGING_TECH: List[Tuple[str, str]] = [
    ("TATAELXSI.NS", "Tata Elxsi"),
    ("KPITTECH.NS", "KPIT Technologies"),
    ("AFFLE.NS", "Affle India"),
    ("NETWEB.NS", "Netweb Technologies"),
    ("LATENTVIEW.NS", "LatentView Analytics"),
    ("ZENSARTECH.NS", "Zensar Technologies"),
    ("HAPPSTMNDS.NS", "Happiest Minds Technologies"),
    ("TANLA.NS", "Tanla Platforms"),
]

# Traditional headcount-billed IT services companies — split out from AI so
# the "AI" basket isn't dominated by generic outsourcing majors.
IT_SERVICES: List[Tuple[str, str]] = [
    ("TCS.NS", "Tata Consultancy Services"),
    ("INFY.NS", "Infosys"),
    ("HCLTECH.NS", "HCL Technologies"),
    ("WIPRO.NS", "Wipro"),
    ("TECHM.NS", "Tech Mahindra"),
    ("LTIM.NS", "LTIMindtree"),
    ("PERSISTENT.NS", "Persistent Systems"),
    ("COFORGE.NS", "Coforge"),
    ("MPHASIS.NS", "Mphasis"),
    ("CYIENT.NS", "Cyient"),
    ("OFSS.NS", "Oracle Financial Services"),
]

DATA_CENTERS: List[Tuple[str, str]] = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("BHARTIARTL.NS", "Bharti Airtel"),
    ("TATACOMM.NS", "Tata Communications"),
    ("INDUSTOWER.NS", "Indus Towers"),
    ("RAILTEL.NS", "RailTel"),
    ("ANANTRAJ.NS", "Anant Raj"),
    ("NETWEB.NS", "Netweb Technologies"),
    ("E2E.NS", "E2E Networks"),
    ("ADANIENT.NS", "Adani Enterprises"),
]

ENERGY_AND_POWER: List[Tuple[str, str]] = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("ONGC.NS", "ONGC"),
    ("OIL.NS", "Oil India"),
    ("IOC.NS", "Indian Oil"),
    ("BPCL.NS", "Bharat Petroleum"),
    ("HINDPETRO.NS", "Hindustan Petroleum"),
    ("GAIL.NS", "GAIL India"),
    ("PETRONET.NS", "Petronet LNG"),
    ("NTPC.NS", "NTPC"),
    ("POWERGRID.NS", "Power Grid Corporation"),
    ("COALINDIA.NS", "Coal India"),
    ("TATAPOWER.NS", "Tata Power"),
    ("ADANIGREEN.NS", "Adani Green Energy"),
    ("ADANIPOWER.NS", "Adani Power"),
    ("ADANIENSOL.NS", "Adani Energy Solutions"),
    ("JSWENERGY.NS", "JSW Energy"),
    ("NHPC.NS", "NHPC"),
    ("SJVN.NS", "SJVN"),
    ("TORNTPOWER.NS", "Torrent Power"),
    ("CESC.NS", "CESC"),
    ("SUZLON.NS", "Suzlon Energy"),
    ("INOXWIND.NS", "Inox Wind"),
    ("IREDA.NS", "IREDA"),
]

DEFENCE: List[Tuple[str, str]] = [
    ("HAL.NS", "Hindustan Aeronautics"),
    ("BEL.NS", "Bharat Electronics"),
    ("BDL.NS", "Bharat Dynamics"),
    ("MAZDOCK.NS", "Mazagon Dock Shipbuilders"),
    ("COCHINSHIP.NS", "Cochin Shipyard"),
    ("GRSE.NS", "Garden Reach Shipbuilders"),
    ("BEML.NS", "BEML"),
    ("MIDHANI.NS", "Mishra Dhatu Nigam"),
    ("SOLARINDS.NS", "Solar Industries"),
    ("DATAPATTNS.NS", "Data Patterns"),
    ("ZENTEC.NS", "Zen Technologies"),
    ("ASTRAMICRO.NS", "Astra Microwave"),
    ("PARAS.NS", "Paras Defence"),
    ("IDEAFORGE.NS", "ideaForge"),
    ("BHARATFORG.NS", "Bharat Forge"),
]

SECTORS: Dict[str, List[Tuple[str, str]]] = {
    "AI & Emerging Tech": AI_AND_EMERGING_TECH,
    "IT Services": IT_SERVICES,
    "Data Centers & Digital Infra": DATA_CENTERS,
    "Energy & Power": ENERGY_AND_POWER,
    "Defence": DEFENCE,
    "Nifty 50": NIFTY_50,
}

# symbol -> display name across every sector (first name wins).
WATCHLIST: Dict[str, str] = {}
for _members in SECTORS.values():
    for _sym, _name in _members:
        WATCHLIST.setdefault(_sym, _name)


def watch_symbols() -> List[str]:
    return list(WATCHLIST.keys())


# Rough sector-average trailing P/E baselines for the valuation score —
# a stock trading well below its sector's typical multiple scores as cheap,
# well above as expensive. Deliberately coarse; edit as market levels shift.
SECTOR_PE: Dict[str, float] = {
    "AI & Emerging Tech": 45.0,   # smaller, higher-growth, richer-multiple names
    "IT Services": 24.0,
    "Data Centers & Digital Infra": 30.0,
    "Energy & Power": 14.0,
    "Defence": 38.0,
}
DEFAULT_MARKET_PE = 22.0  # ~Nifty 50 long-run average


def sector_pe_for(symbol: str) -> float:
    """Sector P/E baseline for a symbol: its first thematic basket's value,
    else the broad-market average."""
    symbol = symbol.upper()
    for sector, members in SECTORS.items():
        if sector == "Nifty 50":
            continue
        if any(sym == symbol for sym, _ in members):
            return SECTOR_PE.get(sector, DEFAULT_MARKET_PE)
    return DEFAULT_MARKET_PE


def sector_for(symbol: str) -> str:
    """First thematic basket containing the symbol, else 'Nifty 50'."""
    symbol = symbol.upper()
    for sector, members in SECTORS.items():
        if sector == "Nifty 50":
            continue
        if any(sym == symbol for sym, _ in members):
            return sector
    return "Nifty 50"


# Banks/NBFCs/insurers: leverage is their business model, so the
# debt-to-equity quality component is skipped for these symbols.
FINANCIAL_SYMBOLS = {
    "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
    "INDUSINDBK.NS", "PNB.NS", "BANKBARODA.NS", "CANBK.NS", "UNIONBANK.NS",
    "FEDERALBNK.NS", "YESBANK.NS", "IDFCFIRSTB.NS", "BAJFINANCE.NS",
    "BAJAJFINSV.NS", "SHRIRAMFIN.NS", "MUTHOOTFIN.NS", "PFC.NS", "RECLTD.NS",
    "IRFC.NS", "IREDA.NS", "LICI.NS", "HDFCLIFE.NS", "SBILIFE.NS",
    "ICICIPRULI.NS", "JIOFIN.NS",
}

# Macro sensitivity: sector -> {indicator: weight}. Tilt contribution is
# weight x indicator state, where states are: nifty (+ = uptrend),
# usdinr (+ = rupee weakening), brent (+ = crude rising), vix (+ = fear
# rising). E.g. IT exporters benefit from a weak rupee (+0.6 x usdinr);
# the broad market suffers from it (FII outflows, import bill).
MACRO_SENSITIVITY = {
    "AI & Emerging Tech":           {"nifty": 0.5, "usdinr": 0.3, "brent": 0.0, "vix": -0.4},
    "IT Services":                  {"nifty": 0.4, "usdinr": 0.6, "brent": 0.0, "vix": -0.3},
    "Data Centers & Digital Infra": {"nifty": 0.5, "usdinr": 0.2, "brent": -0.1, "vix": -0.3},
    "Energy & Power":              {"nifty": 0.4, "usdinr": -0.2, "brent": -0.3, "vix": -0.3},
    "Defence":                     {"nifty": 0.3, "usdinr": 0.0, "brent": -0.1, "vix": -0.2},
    "Nifty 50":                    {"nifty": 0.6, "usdinr": -0.2, "brent": -0.2, "vix": -0.4},
}

# Per-symbol overrides where the sector-level sign is wrong: upstream
# producers gain from rising crude; refiner-marketers lose.
MACRO_SYMBOL_OVERRIDES = {
    "ONGC.NS": {"brent": 0.6},
    "OIL.NS": {"brent": 0.6},
    "IOC.NS": {"brent": -0.5},
    "BPCL.NS": {"brent": -0.5},
    "HINDPETRO.NS": {"brent": -0.5},
}
