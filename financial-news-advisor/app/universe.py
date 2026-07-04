"""The watch universe scanned on every cycle, beyond the user's portfolio.

Nifty 50 constituents plus thematic baskets Indian retail investors track
closely: AI/IT, data centers & digital infrastructure, energy & power, and
defence. Symbols use Yahoo Finance form (.NS = NSE). Index membership
changes a couple of times a year — edit the lists here to keep them fresh.
A ticker may appear in several sectors (e.g. Reliance in energy and data
centers); the scanner dedupes the underlying analysis.
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

AI_AND_IT: List[Tuple[str, str]] = [
    ("TCS.NS", "Tata Consultancy Services"),
    ("INFY.NS", "Infosys"),
    ("HCLTECH.NS", "HCL Technologies"),
    ("WIPRO.NS", "Wipro"),
    ("TECHM.NS", "Tech Mahindra"),
    ("LTIM.NS", "LTIMindtree"),
    ("PERSISTENT.NS", "Persistent Systems"),
    ("COFORGE.NS", "Coforge"),
    ("MPHASIS.NS", "Mphasis"),
    ("TATAELXSI.NS", "Tata Elxsi"),
    ("KPITTECH.NS", "KPIT Technologies"),
    ("CYIENT.NS", "Cyient"),
    ("OFSS.NS", "Oracle Financial Services"),
    ("AFFLE.NS", "Affle India"),
    ("NETWEB.NS", "Netweb Technologies"),
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
    "AI & IT": AI_AND_IT,
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
    "AI & IT": 26.0,
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
