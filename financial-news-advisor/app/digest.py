"""Daily proactive digest: rating changes + fresh headlines for each user's
portfolio, pushed via app/notify.py's channels (Telegram, Hermes Agent).

Runs on its own daemon thread, sleeping until the next occurrence of
config.DIGEST_HOUR_IST local time rather than a fixed interval, so it
lands at a predictable time each morning instead of drifting with process
start time. Nothing is sent when there's no rating change and no fresh
headline since the last digest -- silence on quiet days, not noise.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from . import database, notify, recommender

log = logging.getLogger("digest")

_stop = threading.Event()


def _seconds_until_next_run(hour: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _build_message(user: Dict) -> Optional[str]:
    user_id = user["id"]
    portfolio = database.get_portfolio(user_id)
    if not portfolio:
        return None

    profile = user.get("risk_profile") or "balanced"
    recs = recommender.cached_recommendations(user_id, profile)
    if recs is None:
        recs = recommender.recommend_portfolio_for_user(user_id, profile)

    prev_actions = database.get_digest_state(user_id)
    since_ts = database.get_last_digest_ts(user_id) or (time.time() - 86400)

    changes, current_actions = [], {}
    for rec in recs:
        ticker, action = rec["ticker"], rec["action"]
        current_actions[ticker] = action
        prev = prev_actions.get(ticker)
        if prev and prev != action:
            changes.append(f"{ticker.split('.')[0]}: {prev} -> {action}")

    headlines = []
    for h in portfolio:
        for a in database.recent_articles(limit=3, ticker=h["ticker"], since_ts=since_ts):
            headlines.append(f"[{h['ticker'].split('.')[0]}] {a['title']}")

    # Persist the snapshot regardless of whether anything is sent, so a
    # rating that later reverts doesn't get re-reported as a fresh change,
    # and so the news window always starts from the last time we looked.
    database.set_digest_state(user_id, current_actions)

    if not changes and not headlines:
        return None

    lines = ["Portfolio digest"]
    if changes:
        lines += ["", "Rating changes:"] + [f"- {c}" for c in changes]
    if headlines:
        lines += ["", "New headlines:"] + [f"- {h}" for h in headlines[:15]]
    return "\n".join(lines)


def send_all() -> None:
    for user in database.list_users():
        try:
            text = _build_message(user)
        except Exception:
            log.exception("digest build failed for user %s", user["id"])
            continue
        if not text:
            continue
        sent = notify.send_digest(text)
        if sent:
            log.info("digest sent to user %s via %s", user["id"], ", ".join(sent))
        else:
            log.info("digest built for user %s but no channel configured/succeeded",
                     user["id"])


def _loop(hour: int) -> None:
    while not _stop.is_set():
        if _stop.wait(_seconds_until_next_run(hour)):
            break
        try:
            send_all()
        except Exception:
            log.exception("digest cycle crashed")


def start(hour: int) -> None:
    thread = threading.Thread(target=_loop, args=(hour,), name="digest", daemon=True)
    thread.start()


def stop() -> None:
    _stop.set()
