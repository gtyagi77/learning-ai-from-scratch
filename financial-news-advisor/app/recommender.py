"""Valuation + quality + news + macro recommendations per ticker.

Components (each in [-1, +1], dropped when its data is unavailable):

  Value    — P/E vs sector baseline (screener's Stock P/E backfills Yahoo's
             gated trailing P/E), analyst mean-target upside, analyst
             consensus rating.
  Quality  — ROE, debt-to-equity (skipped for banks/NBFCs), revenue &
             net-profit 3y CAGR, operating-margin trend, latest-quarter
             sales YoY. Requires >= 2 sub-components to count.
  News     — recency-weighted sentiment of *specific* coverage (headline
             mentions 1.0, passing mentions 0.35x, roundups 0.3x).
  Macro    — sector-sensitivity tilt from Nifty trend, USD/INR, Brent,
             India VIX (app/macro.py), share capped at 0.25.

Weights depend on the user's risk profile (conservative / balanced /
aggressive) and are renormalized over available components. Guards:
STRONG ratings require both value and quality; news-only ratings are
capped at BUY/SELL; a rating never contradicts its own target's direction;
macro alone never produces a rating.

Every recommendation carries dated horizons (1m news-driven, 3m valuation
mean-reversion, 12m analyst/growth) and a plain-language strategy block
(entry, stop-loss, profit booking, position-size hint, review triggers).

Educational tooling only — not investment advice.
"""

import time
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from . import (config, database, financials, fundamentals, macro, prices,
               sentiment, universe)

RISK_PROFILES = {
    "conservative": {"value": 0.40, "quality": 0.35, "news": 0.15, "macro": 0.10},
    "balanced":     {"value": 0.35, "quality": 0.25, "news": 0.25, "macro": 0.15},
    "aggressive":   {"value": 0.25, "quality": 0.15, "news": 0.40, "macro": 0.20},
}
MACRO_SHARE_CAP = 0.25
POSITION_BASE_PCT = {"conservative": 4.0, "balanced": 6.0, "aggressive": 10.0}


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _fmt_money(v: Optional[float], ccy: Optional[str]) -> str:
    sym = "₹" if (ccy or "INR") == "INR" else "$"
    return f"{sym}{v:,.0f}" if v is not None else "—"


# --------------------------------------------------------------------------
# news component
# --------------------------------------------------------------------------

def _recency_weight(article: Dict, now: float) -> float:
    ts = article.get("published_ts") or article.get("fetched_ts") or now
    age_hours = max(0.0, (now - ts) / 3600.0)
    return 0.5 ** (age_hours / config.RECENCY_HALF_LIFE_HOURS)


def _relevance(article: Dict, ticker: str) -> float:
    rel = 1.0 if ticker in (article.get("title_tickers") or []) else 0.35
    if len(article.get("tickers") or []) > 3:
        rel *= 0.3
    return rel


def _news_signal(articles: List[Dict], ticker: str, now: float) -> Tuple[float, List[float], List[float]]:
    weights = [_recency_weight(a, now) * _relevance(a, ticker) for a in articles]
    scores = [a["sentiment"] for a in articles]
    if weights and sum(weights) > 0:
        signal = sum(w * s for w, s in zip(weights, scores)) / sum(weights)
    else:
        signal = 0.0
    return round(signal, 3), weights, scores


# --------------------------------------------------------------------------
# value component
# --------------------------------------------------------------------------

def valuation_score(f: Optional[Dict], sector_pe: float,
                    fin: Optional[Dict] = None) -> Tuple[Optional[float], List[str], Optional[float]]:
    """(score, notes, fair_value). f = price stats/analyst data
    (fundamentals.get_fundamentals), fin = statements (financials)."""
    f = f or {}
    fin = fin or {}
    if not f and not fin:
        return None, [], None

    comps: List[Tuple[float, float, str]] = []
    fair_estimates: List[Tuple[float, float]] = []
    price = f.get("price")
    ccy = f.get("currency")

    # Screener's Stock P/E backfills Yahoo's often-gated trailing P/E.
    pe = f.get("trailing_pe") or f.get("forward_pe") or fin.get("stock_pe")
    if pe and pe > 0 and sector_pe:
        score = _clamp((sector_pe - pe) / sector_pe)
        cheap = "below" if pe < sector_pe else "above"
        comps.append((score, 1.0, f"P/E {pe:.1f} vs sector ~{sector_pe:.0f} ({cheap})"))
        if price:
            fair = price * _clamp(sector_pe / pe, 0.6, 1.4)
            fair_estimates.append((fair, 0.4))

    target_mean = f.get("target_mean")
    if target_mean and price:
        upside = (target_mean - price) / price
        rng = ""
        if f.get("target_low") and f.get("target_high"):
            rng = f", range {_fmt_money(f['target_low'], ccy)}–{_fmt_money(f['target_high'], ccy)}"
        comps.append((_clamp(upside * 2.5), 1.0,
                      f"analyst mean target {_fmt_money(target_mean, ccy)} ({upside * 100:+.0f}%{rng})"))
        fair_estimates.append((target_mean, 0.6))

    rating = f.get("analyst_rating")
    if rating:
        # Street consensus scale: 1 strong buy .. 5 sell -> [-1, +1].
        score = _clamp((3.0 - rating) / 2.0)
        n = f.get("analyst_count")
        comps.append((score, 0.6,
                      f"street consensus {rating:.1f}/5"
                      + (f" from {int(n)} analysts" if n else "")))

    gap = f.get("dma_gap_pct")
    if gap is not None:
        comps.append((_clamp(-gap / 100 * 2.0), 0.6,
                      f"{abs(gap):.0f}% {'above' if gap >= 0 else 'below'} 200-day avg"))

    pos = f.get("pos52")
    if pos is not None:
        comps.append(((0.5 - pos) * 1.6, 0.5, f"at {pos * 100:.0f}% of 52-week range"))

    if not comps:
        return None, [], None

    total_w = sum(w for _, w, _ in comps)
    score = round(sum(s * w for s, w, _ in comps) / total_w, 3)
    notes = [n for _, _, n in comps]

    fair_value = None
    if fair_estimates:
        fw = sum(w for _, w in fair_estimates)
        fair_value = round(sum(v * w for v, w in fair_estimates) / fw, 2)
    return score, notes, fair_value


# --------------------------------------------------------------------------
# quality component (revenues, profits, balance sheet)
# --------------------------------------------------------------------------

def quality_score(fin: Optional[Dict], is_financial: bool) -> Tuple[Optional[float], List[str]]:
    """Balance-sheet & growth quality in [-1, 1]; None unless >= 2
    sub-components resolve."""
    if not fin:
        return None, []

    comps: List[Tuple[float, float, str]] = []

    roe = fin.get("roe_pct") or fin.get("roce_pct")
    if roe is not None:
        comps.append((_clamp((roe - 12.0) / 15.0), 1.0, f"ROE {roe:.1f}%"))

    de = fin.get("debt_to_equity")
    if de is not None and not is_financial:
        comps.append((_clamp(1.0 - de), 0.8, f"debt/equity {de:.2f}"))

    rev = fin.get("rev_cagr_3y_pct")
    if rev is not None:
        comps.append((_clamp(rev / 20.0), 1.0, f"revenue growth {rev:+.1f}%/yr"))

    prof = fin.get("profit_cagr_3y_pct")
    if prof is not None:
        comps.append((_clamp(prof / 25.0), 1.0, f"profit growth {prof:+.1f}%/yr"))

    opm = fin.get("opm_trend_pp")
    if opm is not None:
        comps.append((_clamp(opm / 5.0), 0.6, f"margins {opm:+.1f}pp vs 3y avg"))

    qyoy = fin.get("q_sales_yoy_pct")
    if qyoy is not None:
        comps.append((_clamp(qyoy / 25.0), 0.6, f"latest quarter sales {qyoy:+.1f}% YoY"))

    if len(comps) < 2:
        return None, []
    total_w = sum(w for _, w, _ in comps)
    score = round(sum(s * w for s, w, _ in comps) / total_w, 3)
    return score, [n for _, _, n in comps]


# --------------------------------------------------------------------------
# blending, rating, guards
# --------------------------------------------------------------------------

def _blend(components: Dict[str, Optional[float]], profile: str) -> Tuple[Optional[float], Dict[str, float]]:
    """Renormalized weighted blend over available components. Macro's
    renormalized share is capped; macro alone yields no signal."""
    weights = RISK_PROFILES.get(profile, RISK_PROFILES["balanced"])
    avail = {k: v for k, v in components.items() if v is not None}
    if not avail or set(avail) == {"macro"}:
        return None, {}
    w = {k: weights[k] for k in avail}
    total = sum(w.values())
    w = {k: v / total for k, v in w.items()}
    if "macro" in w and w["macro"] > MACRO_SHARE_CAP and len(w) > 1:
        excess = w["macro"] - MACRO_SHARE_CAP
        w["macro"] = MACRO_SHARE_CAP
        others = [k for k in w if k != "macro"]
        rest = sum(w[k] for k in others)
        for k in others:
            w[k] += excess * (w[k] / rest)
    combined = round(sum(w[k] * avail[k] for k in avail), 3)
    return combined, {k: round(v, 3) for k, v in w.items()}


def _action(signal: float) -> str:
    if signal >= 0.35:
        return "STRONG BUY"
    if signal >= 0.12:
        return "BUY"
    if signal <= -0.35:
        return "STRONG SELL"
    if signal <= -0.12:
        return "SELL"
    return "HOLD"


def _cap(action: str) -> str:
    return {"STRONG BUY": "BUY", "STRONG SELL": "SELL"}.get(action, action)


def _confidence(weights: List[float], scores: List[float], signal: float,
                n_components: int) -> float:
    if not weights and n_components == 0:
        return 0.0
    effective_n = sum(weights)
    volume = min(1.0, effective_n / 4.0)
    agreement = 1.0
    if weights and sum(weights) > 0:
        total_w = sum(weights)
        mean = sum(w * s for w, s in zip(weights, scores)) / total_w
        variance = sum(w * (s - mean) ** 2 for w, s in zip(weights, scores)) / total_w
        agreement = 1.0 / (1.0 + 4.0 * variance)
    conviction = min(1.0, abs(signal) / 0.5)
    data_bonus = min(0.20, 0.07 * max(0, n_components - 1))
    base = 0.10 + 0.70 * (0.40 * volume + 0.35 * agreement + 0.25 * conviction)
    return round(min(1.0, base + data_bonus), 2)


def _degree(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "moderate"
    if confidence > 0.0:
        return "low"
    return "none"


# --------------------------------------------------------------------------
# horizons & strategy
# --------------------------------------------------------------------------

def _next_results_window(today: date) -> str:
    """Indian quarterly results seasons: mid-Jan, mid-Apr, mid-Jul, mid-Oct."""
    months = [1, 4, 7, 10]
    for m in months:
        if (today.month, today.day) < (m, 15):
            return date(today.year, m, 15).strftime("%b %Y")
    return date(today.year + 1, 1, 15).strftime("%b %Y")


def _horizons(price: Optional[float], news_sig: float, val_score: Optional[float],
              macro_t: Optional[float], fair_value: Optional[float],
              f: Dict, fin: Dict, confidence: float) -> List[Dict]:
    today = date.today()

    def entry(label, days, target, basis):
        ret = (round((target - price) / price * 100, 1)
               if (price and target) else None)
        return {"label": label, "date": (today + timedelta(days=days)).isoformat(),
                "target_price": round(target, 2) if target else None,
                "expected_return_pct": ret, "basis": basis}

    out = []
    # Short (1 month): news momentum off the live price.
    short_t = price * (1 + news_sig * 0.05 * (0.4 + 0.6 * confidence)) if price else None
    out.append(entry("Short (1m)", 28, short_t, "news momentum"))

    # Medium (3 months): pull halfway to fair value, tilted by macro.
    med_t = None
    if price:
        base = fair_value if fair_value else price * (1 + (val_score or 0) * 0.08)
        med_t = (price + 0.5 * (base - price)) * (1 + (macro_t or 0) * 0.03)
    out.append(entry("Medium (3m)", 91, med_t,
                     "valuation mean-reversion + macro tilt"))

    # Long (12 months): analyst target, else fair value grown by profit CAGR.
    long_t = f.get("target_mean")
    basis = "analyst mean target"
    if not long_t and price:
        growth = _clamp((fin.get("profit_cagr_3y_pct") or 0) / 100, -0.25, 0.25)
        long_t = (fair_value or price) * (1 + growth)
        basis = "fair value + profit growth"
    out.append(entry("Long (12m)", 365, long_t, basis))
    return out


def _strategy(action: str, price: Optional[float], f: Dict, horizons: List[Dict],
              confidence: float, profile: str, ccy: Optional[str],
              sector: str) -> Dict:
    today = date.today()
    dma200 = f.get("dma200")
    stop = round(max(dma200 or 0, (price or 0) * 0.92), 2) if price else None
    long_target = next((h["target_price"] for h in reversed(horizons)
                        if h["target_price"]), None)

    if "BUY" in action:
        if price and dma200 and (price - dma200) / dma200 > 0.10:
            entry = (f"extended {((price - dma200) / dma200 * 100):.0f}% above the "
                     f"200-day avg — accumulate on dips toward {_fmt_money(dma200, ccy)}")
        else:
            entry = "buy at current levels"
    elif "SELL" in action:
        entry = "reduce into strength; avoid adding"
    else:
        entry = "hold; wait for a clearer value or news signal before adding"

    pos = round(POSITION_BASE_PCT.get(profile, 6.0) * confidence, 1)
    return {
        "entry": entry,
        "stop_loss": stop if "BUY" in action else None,
        "book_profit_at": long_target if "BUY" in action else None,
        "position_size_hint_pct": pos,
        "review": [f"quarterly results window (~{_next_results_window(today)})",
                   f"macro shifts affecting {sector} (see macro strip)"],
        "profile": profile,
    }


# --------------------------------------------------------------------------
# rationale
# --------------------------------------------------------------------------

def _rationale(parts: Dict, combined: Optional[float], action: str,
               capped: bool, moderated: bool) -> str:
    bits = []
    if parts.get("value") is not None:
        bits.append(f"Value {parts['value']:+.2f} ({'; '.join(parts['value_notes'][:3])})")
    if parts.get("quality") is not None:
        bits.append(f"Quality {parts['quality']:+.2f} ({'; '.join(parts['quality_notes'][:3])})")
    if parts.get("news") is not None:
        bits.append(f"news {parts['news']:+.2f} from {parts['n_articles']} "
                    f"article{'s' if parts['n_articles'] != 1 else ''} "
                    f"({parts['n_specific']} headline-specific)")
    if parts.get("macro") is not None:
        bits.append(f"macro {parts['macro']:+.2f}")
    if not bits:
        return "No usable data in the window — defaulting to HOLD."
    text = "; ".join(bits)
    if combined is not None:
        text += f" → combined {combined:+.2f} → {action}."
    if capped:
        text += " News-only ratings are capped at BUY/SELL."
    if moderated:
        text += (" Moderated to HOLD: the rating and the valuation-anchored "
                 "target pointed in opposite directions.")
    return text


# --------------------------------------------------------------------------
# main entry points
# --------------------------------------------------------------------------

def recommend_for_ticker(ticker: str, name: Optional[str] = None,
                         quote_mode: str = "always",
                         risk_profile: str = "balanced",
                         allow_financials_fetch: bool = True) -> Dict:
    ticker = ticker.upper()
    if risk_profile not in RISK_PROFILES:
        risk_profile = "balanced"
    now = time.time()
    since = now - config.LOOKBACK_HOURS * 3600
    articles = database.recent_articles(limit=200, ticker=ticker, since_ts=since)

    news_sig, weights, scores = _news_signal(articles, ticker, now)
    n_specific = sum(1 for a in articles if ticker in (a.get("title_tickers") or []))

    active = quote_mode == "always" or bool(articles)
    funda = fundamentals.get_fundamentals(ticker) if active else None
    fin = financials.get_financials(ticker, allow_fetch=allow_financials_fetch and active) if active else None

    val_score, val_notes, fair_value = valuation_score(
        funda, universe.sector_pe_for(ticker), fin)
    qual_score, qual_notes = quality_score(fin, ticker in universe.FINANCIAL_SYMBOLS)
    macro_t, macro_notes = macro.macro_tilt(ticker) if active else (None, [])

    components = {
        "value": val_score,
        "quality": qual_score,
        "news": news_sig if articles else None,
        "macro": macro_t,
    }
    combined, applied_weights = _blend(components, risk_profile)

    n_components = sum(1 for v in components.values() if v is not None)
    confidence = _confidence(weights, scores, combined or 0.0, n_components)

    action = _action(combined) if combined is not None else "HOLD"
    capped = False
    if val_score is None and qual_score is None and combined is not None:
        new_action = _cap(action)
        capped = action != new_action
        action = new_action
    elif action in ("STRONG BUY", "STRONG SELL") and (
            val_score is None or qual_score is None):
        action = _cap(action)  # STRONG needs both value and quality

    quote = prices.get_quote(ticker) if (
        quote_mode == "always" or (quote_mode == "auto" and articles)) else None
    price = quote["price"] if quote else (funda or {}).get("price")
    currency = quote["currency"] if quote else (funda or {}).get("currency")

    if fair_value:
        target_price = round(fair_value * (1 + news_sig * 0.03), 2)
        target_basis = "valuation-anchored"
        implied_move_pct = (round((target_price - price) / price * 100, 2)
                            if price else None)
    else:
        implied_move = (combined or 0.0) * config.MAX_IMPLIED_MOVE * (0.4 + 0.6 * confidence)
        implied_move_pct = round(implied_move * 100, 2)
        target_price = round(price * (1 + implied_move), 2) if price else None
        target_basis = "news-implied"

    moderated = False
    if fair_value and implied_move_pct is not None:
        if "BUY" in action and implied_move_pct < -1.0:
            action, moderated = "HOLD", True
        elif "SELL" in action and implied_move_pct > 1.0:
            action, moderated = "HOLD", True

    horizons = _horizons(price, news_sig, val_score, macro_t, fair_value,
                         funda or {}, fin or {}, confidence)
    strategy = _strategy(action, price, funda or {}, horizons, confidence,
                         risk_profile, currency, universe.sector_for(ticker))

    rationale = _rationale(
        {"value": val_score, "value_notes": val_notes,
         "quality": qual_score, "quality_notes": qual_notes,
         "news": news_sig if articles else None,
         "n_articles": len(articles), "n_specific": n_specific,
         "macro": macro_t},
        combined, action, capped, moderated)

    top = sorted(
        articles,
        key=lambda a: abs(a["sentiment"]) * _recency_weight(a, now) * _relevance(a, ticker),
        reverse=True,
    )[:5]

    return {
        "ticker": ticker,
        "name": name,
        "action": action,
        "signal": combined if combined is not None else 0.0,
        "signal_label": sentiment.label(combined or 0.0),
        "news_signal": news_sig,
        "valuation_score": val_score,
        "valuation_notes": val_notes,
        "quality_score": qual_score,
        "quality_notes": qual_notes,
        "macro_tilt": macro_t,
        "macro_notes": macro_notes,
        "applied_weights": applied_weights,
        "risk_profile": risk_profile,
        "fair_value": fair_value,
        "confidence": confidence,
        "degree": _degree(confidence),
        "rationale": rationale,
        "news_count": len(articles),
        "news_specific_count": n_specific,
        "current_price": price,
        "change_pct": quote["change_pct"] if quote else None,
        "currency": currency,
        "target_price": target_price,
        "target_basis": target_basis,
        "implied_move_pct": implied_move_pct,
        "horizons": horizons,
        "strategy": strategy,
        "financials_source": (fin or {}).get("source"),
        "analyst": {
            "rating": (funda or {}).get("analyst_rating"),
            "count": (funda or {}).get("analyst_count"),
            "target_mean": (funda or {}).get("target_mean"),
            "target_low": (funda or {}).get("target_low"),
            "target_high": (funda or {}).get("target_high"),
        },
        "top_articles": [
            {
                "title": a["title"],
                "link": a["link"],
                "source": a["source"],
                "sentiment": round(a["sentiment"], 3),
                "sentiment_label": sentiment.label(a["sentiment"]),
                "published_ts": a.get("published_ts") or a.get("fetched_ts"),
            }
            for a in top
        ],
    }


def recommend_portfolio(risk_profile: str = "balanced") -> List[Dict]:
    return [
        recommend_for_ticker(h["ticker"], h.get("name"), risk_profile=risk_profile)
        for h in database.get_portfolio()
    ]


def recommend_portfolio_for_user(user_id: int,
                                 risk_profile: str = "balanced") -> List[Dict]:
    return [
        recommend_for_ticker(h["ticker"], h.get("name"), risk_profile=risk_profile)
        for h in database.get_portfolio(user_id)
    ]


def scan_universe(max_per_sector: int = 10, risk_profile: str = "balanced",
                  hidden_sectors: Optional[Iterable[str]] = None) -> List[Dict]:
    """Scan the watch universe; financials are cache-only here so a 100+
    symbol sweep never triggers a screener crawl. hidden_sectors lets a
    caller drop sectors a user has hidden from their Market Scan view."""
    hidden = set(hidden_sectors or ())
    cache: Dict[str, Dict] = {}
    sectors = []
    for sector, members in universe.SECTORS.items():
        if sector in hidden:
            continue
        rows = []
        seen = set()
        for symbol, name in members:
            if symbol in seen:
                continue
            seen.add(symbol)
            rec = cache.get(symbol)
            if rec is None:
                rec = recommend_for_ticker(symbol, name, quote_mode="auto",
                                           risk_profile=risk_profile,
                                           allow_financials_fetch=False)
                cache[symbol] = rec
            if rec["news_count"] > 0:
                rows.append(rec)
        rows.sort(key=lambda r: abs(r["signal"]), reverse=True)
        sectors.append({
            "sector": sector,
            "watched": len(members),
            "with_news": len(rows),
            "results": rows[:max_per_sector],
        })
    return sectors
