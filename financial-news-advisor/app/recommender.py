"""Turns recent per-ticker news sentiment into portfolio recommendations.

For each holding:
  1. Collect articles from the lookback window that mention the ticker.
  2. Recency-weight each article's sentiment (exponential decay).
  3. Combine into one signal in [-1, 1].
  4. Confidence blends news volume and how much the articles agree.
  5. Map signal -> action (STRONG BUY .. STRONG SELL) and derive a target
     price as an implied short-horizon move off the live quote.

Educational tooling only — not investment advice.
"""

import time
from typing import Dict, List, Optional

from . import config, database, prices, sentiment, universe


def _recency_weight(article: Dict, now: float) -> float:
    ts = article.get("published_ts") or article.get("fetched_ts") or now
    age_hours = max(0.0, (now - ts) / 3600.0)
    return 0.5 ** (age_hours / config.RECENCY_HALF_LIFE_HOURS)


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


def _confidence(weights: List[float], scores: List[float], signal: float) -> float:
    """0..1: how much to trust the signal."""
    if not weights:
        return 0.0
    effective_n = sum(weights)
    volume = min(1.0, effective_n / 5.0)  # ~5 fresh articles = full volume

    # Agreement: 1 when all articles point the same way, lower when mixed.
    total_w = sum(weights)
    mean = sum(w * s for w, s in zip(weights, scores)) / total_w
    variance = sum(w * (s - mean) ** 2 for w, s in zip(weights, scores)) / total_w
    agreement = 1.0 / (1.0 + 4.0 * variance)

    conviction = min(1.0, abs(signal) / 0.5)
    return round(min(1.0, 0.15 + 0.85 * (0.45 * volume + 0.35 * agreement + 0.20 * conviction)), 2)


RATING_THRESHOLDS = (
    "signal ≥ +0.35 STRONG BUY · ≥ +0.12 BUY · between −0.12 and +0.12 HOLD"
    " · ≤ −0.12 SELL · ≤ −0.35 STRONG SELL"
)


def _rationale(signal: float, n_articles: int, action: str) -> str:
    """One-sentence, plain-language explanation of how the rating was set."""
    if n_articles == 0:
        return "No news mentioning this stock in the last 48h — defaulting to HOLD."
    return (
        f"Average news sentiment {signal:+.2f} across {n_articles} recent "
        f"article{'s' if n_articles != 1 else ''}, newer headlines weighted "
        f"more → {action}."
    )


def _degree(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "moderate"
    if confidence > 0.0:
        return "low"
    return "none"


def recommend_for_ticker(ticker: str, name: Optional[str] = None,
                         quote_mode: str = "always") -> Dict:
    """quote_mode: "always" fetches a live quote unconditionally; "auto"
    fetches one only when the ticker has news in the window — used by the
    universe scan so a 100+ symbol sweep doesn't hammer the quote API."""
    ticker = ticker.upper()
    now = time.time()
    since = now - config.LOOKBACK_HOURS * 3600
    articles = database.recent_articles(limit=200, ticker=ticker, since_ts=since)

    weights = [_recency_weight(a, now) for a in articles]
    scores = [a["sentiment"] for a in articles]

    if weights and sum(weights) > 0:
        signal = sum(w * s for w, s in zip(weights, scores)) / sum(weights)
    else:
        signal = 0.0
    signal = round(signal, 3)

    confidence = _confidence(weights, scores, signal)
    action = _action(signal) if articles else "HOLD"

    want_quote = quote_mode == "always" or (quote_mode == "auto" and articles)
    quote = prices.get_quote(ticker) if want_quote else None

    # The news-implied move (upside/downside %) depends only on the signal
    # and confidence, so it is always available — even when no live quote
    # resolves and a ₹ target price cannot be anchored. Weak or uncertain
    # news implies a move close to zero.
    implied_move = signal * config.MAX_IMPLIED_MOVE * (0.4 + 0.6 * confidence)
    implied_move_pct = round(implied_move * 100, 2)
    target_price = round(quote["price"] * (1 + implied_move), 2) if quote else None

    top = sorted(
        articles,
        key=lambda a: abs(a["sentiment"]) * _recency_weight(a, now),
        reverse=True,
    )[:5]

    return {
        "ticker": ticker,
        "name": name,
        "action": action,
        "signal": signal,
        "signal_label": sentiment.label(signal),
        "confidence": confidence,
        "degree": _degree(confidence),
        "rationale": _rationale(signal, len(articles), _action(signal) if articles else "HOLD"),
        "news_count": len(articles),
        "current_price": quote["price"] if quote else None,
        "change_pct": quote["change_pct"] if quote else None,
        "currency": quote["currency"] if quote else None,
        "target_price": target_price,
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
