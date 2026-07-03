"""Lexicon-based financial sentiment scoring, implemented from scratch.

Inspired by the Loughran-McDonald finance lexicon and VADER's handling of
negation/intensifiers, but hand-rolled and dependency-free. Scores fall in
[-1, 1]: negative = bearish, positive = bullish.
"""

import math
import re
from typing import Dict, List, Tuple

# word -> polarity weight. Magnitudes reflect how strongly a word tends to
# move a stock when it appears in a headline.
LEXICON: Dict[str, float] = {
    # --- bullish ---
    "beat": 2.0, "beats": 2.0, "surge": 2.0, "surges": 2.0, "soar": 2.2,
    "soars": 2.2, "rally": 1.8, "rallies": 1.8, "record": 1.5, "upgrade": 2.0,
    "upgrades": 2.0, "upgraded": 2.0, "outperform": 1.8, "overweight": 1.5,
    "bullish": 1.8, "growth": 1.2, "profit": 1.2, "profits": 1.2,
    "profitable": 1.4, "gain": 1.2, "gains": 1.2, "jump": 1.6, "jumps": 1.6,
    "jumped": 1.6, "climb": 1.2, "climbs": 1.2, "strong": 1.4, "stronger": 1.4,
    "strength": 1.2, "boost": 1.4, "boosts": 1.4, "boosted": 1.4, "raise": 1.2,
    "raises": 1.2, "raised": 1.2, "hike": 1.0, "hikes": 1.0, "exceed": 1.6,
    "exceeds": 1.6, "exceeded": 1.6, "top": 1.2, "tops": 1.4, "topped": 1.4,
    "buyback": 1.5, "dividend": 1.0, "breakthrough": 1.8, "approval": 1.6,
    "approved": 1.6, "approves": 1.6, "win": 1.4, "wins": 1.4, "won": 1.4,
    "partnership": 1.2, "expansion": 1.2, "expands": 1.2, "upbeat": 1.6,
    "optimism": 1.4, "optimistic": 1.4, "recover": 1.2, "recovers": 1.2,
    "recovery": 1.2, "rebound": 1.4, "rebounds": 1.4, "upside": 1.4,
    "milestone": 1.2, "accelerate": 1.2, "accelerates": 1.2, "momentum": 1.0,
    "innovative": 1.0, "innovation": 1.0, "launch": 0.8, "launches": 0.8,
    "expand": 1.0, "improved": 1.2, "improves": 1.2, "improvement": 1.2,
    "success": 1.4, "successful": 1.4, "robust": 1.4, "solid": 1.2,
    "blowout": 2.0, "stellar": 1.8, "impressive": 1.4, "buy": 1.0,
    "outperforms": 1.8, "advances": 1.0, "booming": 1.8, "boom": 1.4,
    "demand": 0.8, "resilient": 1.2, "undervalued": 1.4, "attractive": 1.0,
    "smashes": 2.0, "crushes": 2.0, "surpasses": 1.6, "surpassed": 1.6,
    "inflows": 1.2, "oversubscribed": 1.6, "multibagger": 1.8,
    # --- bearish ---
    "miss": -2.0, "misses": -2.0, "missed": -2.0, "plunge": -2.2,
    "plunges": -2.2, "plunged": -2.2, "crash": -2.4, "crashes": -2.4,
    "tumble": -2.0, "tumbles": -2.0, "tumbled": -2.0, "downgrade": -2.0,
    "downgrades": -2.0, "downgraded": -2.0, "underperform": -1.8,
    "underweight": -1.5, "bearish": -1.8, "loss": -1.4, "losses": -1.4,
    "decline": -1.2, "declines": -1.2, "declined": -1.2, "fall": -1.2,
    "falls": -1.2, "fell": -1.2, "drop": -1.4, "drops": -1.4, "dropped": -1.4,
    "weak": -1.4, "weaker": -1.4, "weakness": -1.4, "cut": -1.2, "cuts": -1.2,
    "lawsuit": -1.6, "sues": -1.6, "sued": -1.6, "probe": -1.6, "probes": -1.6,
    "investigation": -1.6, "investigates": -1.6, "recall": -1.8,
    "recalls": -1.8, "layoff": -1.6, "layoffs": -1.6, "bankruptcy": -2.4,
    "bankrupt": -2.4, "fraud": -2.2, "warning": -1.4, "warns": -1.6,
    "warned": -1.6, "downside": -1.4, "slump": -1.8, "slumps": -1.8,
    "selloff": -1.8, "sell-off": -1.8, "fears": -1.4, "fear": -1.2,
    "concern": -1.0, "concerns": -1.0, "worries": -1.2, "worry": -1.2,
    "risk": -0.8, "risks": -0.8, "default": -2.0, "delist": -2.0,
    "scandal": -2.0, "fine": -1.2, "fined": -1.4, "penalty": -1.2,
    "halt": -1.4, "halts": -1.4, "halted": -1.4, "sink": -1.8, "sinks": -1.8,
    "sank": -1.8, "disappointing": -1.8, "disappoints": -1.8,
    "disappointed": -1.6, "slowdown": -1.4, "slows": -1.0, "slowing": -1.0,
    "shortfall": -1.6, "struggles": -1.4, "struggling": -1.4, "slide": -1.4,
    "slides": -1.4, "slid": -1.4, "pressure": -0.8, "pressured": -1.0,
    "volatile": -0.8, "volatility": -0.8, "recession": -1.6, "inflation": -0.8,
    "sell": -1.0, "shorts": -1.0, "overvalued": -1.4, "bubble": -1.4,
    "tariff": -1.0, "tariffs": -1.0, "sanction": -1.2, "sanctions": -1.2,
    "delay": -1.0, "delays": -1.0, "delayed": -1.2, "outage": -1.4,
    "breach": -1.6, "hack": -1.6, "hacked": -1.8, "resigns": -1.2,
    "resignation": -1.2, "plummet": -2.2, "plummets": -2.2,
    "wipeout": -2.0, "collapse": -2.2, "collapses": -2.2, "crisis": -1.8,
    "outflows": -1.2, "npa": -1.4, "npas": -1.4, "undersubscribed": -1.4,
}

# Words that flip the polarity of the next few sentiment-bearing tokens.
NEGATORS = {"not", "no", "never", "without", "fails", "failed", "fail", "cannot", "can't", "won't", "doesn't", "didn't", "isn't", "aren't"}

# Words that amplify or dampen the following sentiment token.
INTENSIFIERS: Dict[str, float] = {
    "sharply": 1.5, "significantly": 1.4, "strongly": 1.4, "hugely": 1.6,
    "massively": 1.6, "dramatically": 1.5, "wildly": 1.5, "very": 1.3,
    "extremely": 1.5, "record": 1.3, "slightly": 0.6, "modestly": 0.7,
    "marginally": 0.6, "somewhat": 0.7, "barely": 0.5,
}

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z'\-]*")

# How many following tokens a negator affects.
NEGATION_WINDOW = 3


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def score_text(text: str) -> float:
    """Score a piece of text in [-1, 1]. 0 means neutral / no signal."""
    tokens = tokenize(text)
    if not tokens:
        return 0.0

    total = 0.0
    hits = 0
    negate_until = -1
    multiplier = 1.0

    for i, tok in enumerate(tokens):
        if tok in NEGATORS:
            negate_until = i + NEGATION_WINDOW
            continue
        if tok in INTENSIFIERS:
            multiplier = INTENSIFIERS[tok]
            continue

        weight = LEXICON.get(tok)
        if weight:
            if i <= negate_until:
                weight = -weight * 0.8
            weight *= multiplier
            total += weight
            hits += 1
        multiplier = 1.0

    if hits == 0:
        return 0.0
    # Normalise by hit count so long articles do not dominate, then squash.
    return math.tanh(total / (2.0 * math.sqrt(hits)))


def score_article(title: str, summary: str) -> float:
    """Score an article, weighting the headline over the body summary."""
    title_score = score_text(title)
    summary_score = score_text(summary)
    if summary_score == 0.0:
        return title_score
    if title_score == 0.0:
        return summary_score * 0.7
    return 0.7 * title_score + 0.3 * summary_score


def label(score: float) -> str:
    if score >= 0.35:
        return "very positive"
    if score >= 0.10:
        return "positive"
    if score <= -0.35:
        return "very negative"
    if score <= -0.10:
        return "negative"
    return "neutral"
