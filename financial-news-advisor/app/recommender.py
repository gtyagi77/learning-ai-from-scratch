"""Valuation + news recommendations for each ticker.

The rating is NOT "the stock moved up, so buy". Two independent components:

  Valuation score in [-1, +1] (cheap = positive), from whatever fundamentals
  resolve: trailing/forward P/E vs a sector baseline, analyst mean target vs
  price, gap to the 200-day average (stretched = negative), and position in
  the 52-week range. This is 60% of the combined signal.

  News signal in [-1, +1]: recency-weighted average sentiment of *specific*
  coverage — articles naming the stock in the headline count fully, passing
  mentions count 0.35x, multi-stock roundups ("10 stocks to watch") 0.3x.
  This is 40% of the combined signal.

When no valuation data resolves the rating falls back to news alone but is
capped at BUY/SELL — a STRONG rating always requires valuation support.

Target price is valuation-anchored when possible: the average of the analyst
mean target and a sector-P/E fair value, nudged by news sentiment. Only when
neither exists does it fall back to a news-implied move off the live quote.

Educational tooling only — not investment advice.
"""

import time
from typing import Dict, List, Optional, Tuple

from . import config, database, fundamentals, prices, sentiment, universe

VALUATION_WEIGHT = 0.6
NEWS_WEIGHT = 0.4


# --------------------------------------------------------------------------
# news component
# --------------------------------------------------------------------------

def _recency_weight(article: Dict, now: float) -> float:
    ts = article.get("published_ts") or article.get("fetched_ts") or now
    age_hours = max(0.0, (now - ts) / 3600.0)
    return 0.5 ** (age_hours / config.RECENCY_HALF_LIFE_HOURS)


def _relevance(article: Dict, ticker: str) -> float:
    """How specifically this article is about the ticker (0..1)."""
    rel = 1.0 if ticker in (article.get("title_tickers") or []) else 0.35
    if len(article.get("tickers") or []) > 3:  # multi-stock roundup piece
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
# valuation component
# --------------------------------------------------------------------------

def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _fmt_money(v: Optional[float], ccy: Optional[str]) -> str:
    sym = "₹" if (ccy or "INR") == "INR" else "$"
    return f"{sym}{v:,.0f}" if v is not None else "—"


def valuation_score(f: Optional[Dict], sector_pe: float) -> Tuple[Optional[float], List[str], Optional[float]]:
    """(score in [-1,1] or None, human-readable notes, fair_value or None).

    Each component contributes what data allows; missing data simply drops
    the component rather than faking a number.
    """
    if not f:
        return None, [], None

    comps: List[Tuple[float, float, str]] = []  # (score, weight, note)
    fair_estimates: List[Tuple[float, float]] = []  # (value, weight)
    price = f.get("price")
    ccy = f.get("currency")

    pe = f.get("trailing_pe") or f.get("forward_pe")
    if pe and pe > 0 and sector_pe:
        # At the sector multiple -> 0; half the multiple -> +0.5; double -> -1.
        score = _clamp((sector_pe - pe) / sector_pe)
        cheap = "below" if pe < sector_pe else "above"
        comps.append((score, 1.0, f"P/E {pe:.1f} vs sector ~{sector_pe:.0f} ({cheap})"))
        if price:
            fair = price * _clamp(sector_pe / pe, 0.6, 1.4)
            fair_estimates.append((fair, 0.4))

    target_mean = f.get("target_mean")
    if target_mean and price:
        upside = (target_mean - price) / price
        comps.append((_clamp(upside * 2.5), 1.0,
                      f"analyst mean target {_fmt_money(target_mean, ccy)} ({upside * 100:+.0f}%)"))
        fair_estimates.append((target_mean, 0.6))

    gap = f.get("dma_gap_pct")
    if gap is not None:
        # Far above the 200-day average = stretched (negative), far below =
        # depressed (positive). ±25% gap saturates at ∓0.5.
        comps.append((_clamp(-gap / 100 * 2.0), 0.6,
                      f"{abs(gap):.0f}% {'above' if gap >= 0 else 'below'} 200-day avg"))

    pos = f.get("pos52")
    if pos is not None:
        comps.append(((0.5 - pos) * 1.6, 0.5,
                      f"at {pos * 100:.0f}% of 52-week range"))

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
# rating
# --------------------------------------------------------------------------

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


def _cap_news_only(action: str) -> str:
    return {"STRONG BUY": "BUY", "STRONG SELL": "SELL"}.get(action, action)


def _confidence(weights: List[float], scores: List[float], signal: float,
                has_valuation: bool) -> float:
    """0..1: how much to trust the signal."""
    if not weights and not has_valuation:
        return 0.0
    effective_n = sum(weights)
    volume = min(1.0, effective_n / 4.0)  # ~4 specific fresh articles = full

    agreement = 1.0
    if weights and sum(weights) > 0:
        total_w = sum(weights)
        mean = sum(w * s for w, s in zip(weights, scores)) / total_w
        variance = sum(w * (s - mean) ** 2 for w, s in zip(weights, scores)) / total_w
        agreement = 1.0 / (1.0 + 4.0 * variance)

    conviction = min(1.0, abs(signal) / 0.5)
    data_bonus = 0.15 if has_valuation else 0.0
    base = 0.10 + 0.75 * (0.40 * volume + 0.35 * agreement + 0.25 * conviction)
    return round(min(1.0, base + data_bonus), 2)


def _degree(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "moderate"
    if confidence > 0.0:
        return "low"
    return "none"


def _rationale(val_score: Optional[float], val_notes: List[str],
               news_signal: float, n_articles: int, n_specific: int,
               combined: float, action: str) -> str:
    parts = []
    if val_score is not None:
        parts.append(f"Valuation {val_score:+.2f} ({'; '.join(val_notes)})")
    else:
        parts.append("Valuation data unavailable")
    if n_articles:
        parts.append(
            f"news sentiment {news_signal:+.2f} from {n_articles} "
            f"article{'s' if n_articles != 1 else ''} "
            f"({n_specific} headline-specific)")
    else:
        parts.append("no news in the 48h window")
    tail = f" → combined {combined:+.2f} → {action}."
    if val_score is None and n_articles:
        tail += " News-only ratings are capped at BUY/SELL."
    return "; ".join(parts) + tail


# --------------------------------------------------------------------------
# main entry points
# --------------------------------------------------------------------------

def recommend_for_ticker(ticker: str, name: Optional[str] = None,
                         quote_mode: str = "always") -> Dict:
    """quote_mode: "always" fetches a live quote unconditionally; "auto"
    fetches one only when the ticker has news in the window — used by the
    universe scan so a 100+ symbol sweep doesn't hammer the quote API."""
    ticker = ticker.upper()
    now = time.time()
    since = now - config.LOOKBACK_HOURS * 3600
    articles = database.recent_articles(limit=200, ticker=ticker, since_ts=since)

    news_sig, weights, scores = _news_signal(articles, ticker, now)
    n_specific = sum(1 for a in articles if ticker in (a.get("title_tickers") or []))

    funda = fundamentals.get_fundamentals(ticker) if (
        quote_mode == "always" or articles) else None
    val_score, val_notes, fair_value = valuation_score(
        funda, universe.sector_pe_for(ticker))

    if val_score is not None:
        combined = round(VALUATION_WEIGHT * val_score + NEWS_WEIGHT * news_sig, 3)
    else:
        combined = news_sig

    confidence = _confidence(weights, scores, combined, val_score is not None)
    action = _action(combined) if (articles or val_score is not None) else "HOLD"
    if val_score is None:
        action = _cap_news_only(action)

    want_quote = quote_mode == "always" or (quote_mode == "auto" and articles)
    quote = prices.get_quote(ticker) if want_quote else None
    price = quote["price"] if quote else (funda or {}).get("price")
    currency = quote["currency"] if quote else (funda or {}).get("currency")

    # Target price: valuation-anchored when a fair value exists (analyst mean
    # target and/or sector-P/E fair value), nudged slightly by news; else a
    # news/valuation-implied move off the price.
    if fair_value:
        target_price = round(fair_value * (1 + news_sig * 0.03), 2)
        target_basis = "valuation-anchored"
        implied_move_pct = (round((target_price - price) / price * 100, 2)
                            if price else None)
    else:
        implied_move = combined * config.MAX_IMPLIED_MOVE * (0.4 + 0.6 * confidence)
        implied_move_pct = round(implied_move * 100, 2)
        target_price = round(price * (1 + implied_move), 2) if price else None
        target_basis = "news-implied"

    # Coherence guard: never rate BUY with a target below the current price
    # (or SELL with a target above it). When the valuation-anchored target
    # disagrees with the rating's direction, the honest call is HOLD.
    moderated = False
    if fair_value and implied_move_pct is not None:
        if "BUY" in action and implied_move_pct < -1.0:
            action, moderated = "HOLD", True
        elif "SELL" in action and implied_move_pct > 1.0:
            action, moderated = "HOLD", True

    rationale = _rationale(val_score, val_notes, news_sig,
                           len(articles), n_specific, combined, action)
    if moderated:
        rationale += (" Moderated to HOLD: the rating and the "
                      "valuation-anchored target pointed in opposite directions.")

    top = sorted(
        articles,
        key=lambda a: abs(a["sentiment"]) * _recency_weight(a, now) * _relevance(a, ticker),
        reverse=True,
    )[:5]

    return {
        "ticker": ticker,
        "name": name,
        "action": action,
        "signal": combined,
        "signal_label": sentiment.label(combined),
        "news_signal": news_sig,
        "valuation_score": val_score,
        "valuation_notes": val_notes,
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


def recommend_portfolio() -> List[Dict]:
    return [
        recommend_for_ticker(h["ticker"], h.get("name"))
        for h in database.get_portfolio()
    ]


def scan_universe(max_per_sector: int = 10) -> List[Dict]:
    """Scan the whole watch universe (Nifty 50 + sector baskets) and return,
    per sector, the tickers with news in the window ranked by signal
    strength. Tickers shared between sectors are analysed once."""
    cache: Dict[str, Dict] = {}
    sectors = []
    for sector, members in universe.SECTORS.items():
        rows = []
        seen = set()
        for symbol, name in members:
            if symbol in seen:
                continue
            seen.add(symbol)
            rec = cache.get(symbol)
            if rec is None:
                rec = recommend_for_ticker(symbol, name, quote_mode="auto")
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
