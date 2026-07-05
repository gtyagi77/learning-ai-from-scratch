"""Indian listed-equity capital gains analysis over FIFO lots.

Rules implemented (configurable in config.py; post-July-2024 defaults):
  STCG: holding <= TAX_LT_DAYS (365) days -> TAX_STCG_RATE (20%)
  LTCG: holding  > 365 days -> TAX_LTCG_RATE (12.5%), with a per-financial-
        year exemption of TAX_LTCG_EXEMPTION (₹1.25 lakh) applied at the
        PORTFOLIO level (it is consumed across all sales in a FY, so
        per-position figures are shown pre-exemption / marginal).

Lots with unknown buy dates are treated as short-term (conservative).
Pre-2018 grandfathering is out of scope. Educational only — not tax advice.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from . import config


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _is_long_term(buy: Optional[date], today: date) -> Optional[bool]:
    if buy is None:
        return None  # unknown -> treated as short-term downstream
    return (today - buy).days > config.TAX_LT_DAYS


def analyze_position(ticker: str, lots: List[Dict],
                     current_price: Optional[float]) -> Dict:
    """Per-position P&L and tax profile from FIFO lots."""
    today = date.today()
    quantity = sum(l["quantity"] for l in lots)
    invested = sum(l["quantity"] * l["buy_price"] for l in lots)
    avg_cost = round(invested / quantity, 2) if quantity else None

    current_value = round(quantity * current_price, 2) if current_price else None
    unrealized = (round(current_value - invested, 2)
                  if current_value is not None else None)

    st_qty = lt_qty = unknown_qty = 0.0
    st_gain = lt_gain = 0.0
    next_lt: Optional[date] = None
    st_gain_pending_lt = 0.0  # ST gains that will become LT if we wait

    for lot in lots:
        buy = _parse_date(lot.get("buy_date"))
        lt = _is_long_term(buy, today)
        gain = ((current_price - lot["buy_price"]) * lot["quantity"]
                if current_price else 0.0)
        if lt is True:
            lt_qty += lot["quantity"]
            lt_gain += gain
        else:
            st_qty += lot["quantity"]
            st_gain += gain
            if lt is None:
                unknown_qty += lot["quantity"]
            elif buy is not None:
                turns_lt = buy + timedelta(days=config.TAX_LT_DAYS + 1)
                if next_lt is None or turns_lt < next_lt:
                    next_lt = turns_lt
                if gain > 0:
                    st_gain_pending_lt += gain

    # Marginal tax if the whole position were sold today (exemption applied
    # at portfolio level, not here).
    tax_now = None
    after_tax = None
    if current_price is not None:
        tax_now = round(max(0.0, st_gain) * config.TAX_STCG_RATE
                        + max(0.0, lt_gain) * config.TAX_LTCG_RATE, 2)
        after_tax = round(current_value - tax_now, 2)

    tax_saved_by_waiting = round(
        max(0.0, st_gain_pending_lt) * (config.TAX_STCG_RATE - config.TAX_LTCG_RATE), 2)

    return {
        "ticker": ticker,
        "quantity": quantity,
        "avg_cost": avg_cost,
        "invested": round(invested, 2),
        "current_price": current_price,
        "current_value": current_value,
        "unrealized_gain": unrealized,
        "unrealized_gain_pct": (round(unrealized / invested * 100, 2)
                                if unrealized is not None and invested else None),
        "st_quantity": st_qty,
        "lt_quantity": lt_qty,
        "date_unknown_quantity": unknown_qty,
        "st_gain": round(st_gain, 2),
        "lt_gain": round(lt_gain, 2),
        "tax_if_sold_today": tax_now,
        "after_tax_value": after_tax,
        "next_lt_date": next_lt.isoformat() if next_lt else None,
        "next_lt_days": (next_lt - today).days if next_lt else None,
        "tax_saved_by_waiting": tax_saved_by_waiting,
        "lots": lots,
    }


def portfolio_summary(positions: List[Dict]) -> Dict:
    """Portfolio-level totals with the LTCG exemption applied once."""
    invested = sum(p["invested"] for p in positions)
    valued = [p for p in positions if p["current_value"] is not None]
    current = sum(p["current_value"] for p in valued) if valued else None
    st_gain = sum(max(0.0, p["st_gain"]) for p in positions)
    lt_gain = sum(max(0.0, p["lt_gain"]) for p in positions)
    # Gains are computed off live quotes; with none available (e.g. quote
    # provider unreachable) st_gain/lt_gain are 0 for every position, which
    # would otherwise render as a confident "₹0.00 tax" rather than the
    # "unknown" it actually is — match the same all-or-nothing rule already
    # used for current_value/unrealized_gain above.
    if valued:
        lt_taxable = max(0.0, lt_gain - config.TAX_LTCG_EXEMPTION)
        tax = round(st_gain * config.TAX_STCG_RATE + lt_taxable * config.TAX_LTCG_RATE, 2)
        exemption_applied = round(min(lt_gain, config.TAX_LTCG_EXEMPTION), 2)
    else:
        tax = None
        exemption_applied = None
    return {
        "invested": round(invested, 2),
        "current_value": round(current, 2) if current is not None else None,
        "unrealized_gain": (round(current - invested, 2)
                            if current is not None else None),
        "st_gain": round(st_gain, 2),
        "lt_gain": round(lt_gain, 2),
        "ltcg_exemption_applied": exemption_applied,
        "tax_if_all_sold_today": tax,
        "positions": len(positions),
        "note": ("STCG {:.0%} <= {} days; LTCG {:.1%} beyond, with ₹{:,.0f}/FY "
                 "exemption applied at portfolio level. Unknown buy dates are "
                 "treated as short-term. Educational only — not tax advice."
                 ).format(config.TAX_STCG_RATE, config.TAX_LT_DAYS,
                          config.TAX_LTCG_RATE, config.TAX_LTCG_EXEMPTION),
    }


def tax_adjust_action(action: str, implied_move_pct: Optional[float],
                      position: Optional[Dict]) -> tuple:
    """On SELL advice, weigh the STCG cost of selling now against the
    expected downside; waiting a short time for LTCG can beat selling.
    Returns (action, note_or_None)."""
    if not position or "SELL" not in action:
        return action, None
    saved = position.get("tax_saved_by_waiting") or 0.0
    days = position.get("next_lt_days")
    value = position.get("current_value")
    if not value or saved <= 0 or days is None or days > 60:
        return action, None
    saved_pct = saved / value * 100
    expected_downside = abs(min(0.0, implied_move_pct or 0.0))
    if saved_pct > expected_downside:
        note = (f"Tax-aware: waiting {days} days (until "
                f"{position['next_lt_date']}) turns short-term lots long-term "
                f"and saves ≈₹{saved:,.0f} ({saved_pct:.1f}% of the position) — "
                f"more than the {expected_downside:.1f}% expected downside. "
                f"Moderated to HOLD.")
        return "HOLD", note
    note = (f"Tax-aware: selling now costs ≈₹{saved:,.0f} extra STCG vs "
            f"waiting {days} days, but expected downside "
            f"({expected_downside:.1f}%) outweighs it.")
    return action, note
