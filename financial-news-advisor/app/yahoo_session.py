"""Shared crumb/cookie session for Yahoo Finance's undocumented API.

Yahoo's quoteSummary endpoint (and increasingly its chart endpoint too) has
required a crumb+cookie handshake for non-browser clients since ~2022-2024.
This module performs that handshake once per process and hands back a
session that both fundamentals.py and prices.py use, instead of each of
them making bare, keyless requests.get calls. If the handshake itself
fails (no network, or Yahoo blocking this host outright), callers still
get a working plain session — just without a crumb — so behavior never
regresses below the pre-crumb "unauthenticated, best-effort" state.
"""

import logging
import threading
from typing import Dict, Optional

import requests

from . import config

log = logging.getLogger("yahoo_session")

_COOKIE_URL = "https://fc.yahoo.com"
_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"

_lock = threading.Lock()
_session: Optional[requests.Session] = None
_crumb: Optional[str] = None
_handshake_ok = False


def _handshake() -> None:
    """(Re)populate _session/_crumb/_handshake_ok. Always leaves _session
    set to a usable session, falling back to a crumb-less one on failure."""
    global _session, _crumb, _handshake_ok
    sess = requests.Session()
    sess.headers["User-Agent"] = config.USER_AGENT
    try:
        sess.get(_COOKIE_URL, timeout=config.HTTP_TIMEOUT_SECONDS)
        resp = sess.get(_CRUMB_URL, timeout=config.HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        crumb = resp.text.strip()
        if not crumb or "<html" in crumb.lower():
            raise ValueError("no usable crumb in response")
        _crumb = crumb
        _handshake_ok = True
    except Exception as exc:
        log.warning("yahoo crumb handshake failed, continuing without a crumb: %s", exc)
        _crumb = None
        _handshake_ok = False
    _session = sess


def _ensure_session() -> None:
    if _session is None:
        with _lock:
            if _session is None:
                _handshake()


def session_ok() -> bool:
    """Whether the last crumb handshake succeeded — a proxy for whether the
    Yahoo path is structurally reachable from this host at all."""
    _ensure_session()
    return _handshake_ok


def get(url: str, params: Optional[Dict] = None, **kwargs) -> requests.Response:
    """GET url through the shared crumb/cookie session, appending the crumb
    to params when available. Retries once with a freshly re-handshaken
    session on 401/403, since crumbs can expire mid-process."""
    _ensure_session()
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT_SECONDS)

    req_params = dict(params or {})
    if _crumb:
        req_params["crumb"] = _crumb
    resp = _session.get(url, params=req_params, **kwargs)

    if resp.status_code in (401, 403):
        with _lock:
            _handshake()
        req_params = dict(params or {})
        if _crumb:
            req_params["crumb"] = _crumb
        resp = _session.get(url, params=req_params, **kwargs)
    return resp
