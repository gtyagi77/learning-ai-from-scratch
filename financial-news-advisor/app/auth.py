"""Accounts and sessions: scrypt passwords, server-side session tokens,
login rate-limiting, and Google OAuth 2.0 sign-in. Standard library +
requests only — no new dependencies.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

import requests

from . import config, database

log = logging.getLogger("auth")

SESSION_COOKIE = "advisor_session"

# --------------------------------------------------------------------------
# passwords (hashlib.scrypt — stdlib, memory-hard)
# --------------------------------------------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt,
                                n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# --------------------------------------------------------------------------
# login rate limiting (per-IP sliding window, in-memory)
# --------------------------------------------------------------------------

RATE_LIMIT_ATTEMPTS = 8
RATE_LIMIT_WINDOW_S = 300

_attempts: Dict[str, deque] = defaultdict(deque)
_attempts_lock = threading.Lock()


def rate_limited(ip: str) -> bool:
    now = time.time()
    with _attempts_lock:
        window = _attempts[ip]
        while window and window[0] < now - RATE_LIMIT_WINDOW_S:
            window.popleft()
        if len(window) >= RATE_LIMIT_ATTEMPTS:
            return True
        window.append(now)
        return False


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------

def start_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)  # 256 bits
    database.create_session(token, user_id, config.SESSION_TTL_DAYS * 86400)
    return token


def user_from_token(token: Optional[str]) -> Optional[Dict]:
    if not token:
        return None
    return database.get_session_user(token)


def end_session(token: Optional[str]) -> None:
    if token:
        database.delete_session(token)


# --------------------------------------------------------------------------
# registration / login
# --------------------------------------------------------------------------

def register(email: str, password: str, username: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str]]:
    """(user, error). First user becomes admin and adopts any pre-auth
    portfolio; later signups honor ALLOW_SIGNUP."""
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 254:
        return None, "enter a valid email address"
    if len(password or "") < 8:
        return None, "password must be at least 8 characters"
    first = database.count_users() == 0
    if not first and not config.ALLOW_SIGNUP:
        return None, "signup is closed on this server"
    if database.get_user_by_email(email):
        return None, "an account with this email already exists"
    user = database.create_user(email, username or email.split("@")[0],
                                hash_password(password), is_admin=first)
    _seed_new_user(user["id"], first)
    return user, None


def login(email: str, password: str) -> Tuple[Optional[Dict], Optional[str]]:
    user = database.get_user_by_email((email or "").strip().lower())
    if not user or not verify_password(password, user.get("password_hash")):
        return None, "incorrect email or password"
    return user, None


def _seed_new_user(user_id: int, first_user: bool) -> None:
    if first_user:
        database.adopt_orphan_portfolio(user_id)
    if not database.get_portfolio(user_id):
        for symbol, name in config.DEFAULT_PORTFOLIO:
            database.upsert_holding(symbol, name, user_id=user_id)


# --------------------------------------------------------------------------
# Google OAuth 2.0 (authorization-code flow)
# --------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_oauth_states: Dict[str, float] = {}
_oauth_lock = threading.Lock()


def google_enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def _redirect_uri(base: Optional[str] = None) -> str:
    """base overrides config.OAUTH_REDIRECT_BASE — used to derive the
    callback URL from the incoming request when the env var hasn't been
    explicitly set, so Google sign-in works without extra configuration on
    a freshly deployed single-domain host (see main._request_base)."""
    root = (base or config.OAUTH_REDIRECT_BASE).rstrip("/")
    return root + "/api/auth/google/callback"


def google_auth_url(base: Optional[str] = None) -> str:
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _oauth_lock:
        _oauth_states[state] = now
        for s, ts in list(_oauth_states.items()):  # prune stale states
            if now - ts > 600:
                del _oauth_states[s]
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri(base),
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return f"{GOOGLE_AUTH_URL}?{params}"


def google_callback(code: str, state: str,
                    base: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str]]:
    """Exchange the code, fetch userinfo, create/link the user. base must
    match whatever redirect_uri google_auth_url() used for this same
    request cycle (main.py derives it identically both times)."""
    with _oauth_lock:
        if state not in _oauth_states:
            return None, "invalid or expired sign-in state — try again"
        del _oauth_states[state]
    try:
        token_resp = requests.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": _redirect_uri(base),
            "grant_type": "authorization_code",
        }, timeout=config.HTTP_TIMEOUT_SECONDS)
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        info_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=config.HTTP_TIMEOUT_SECONDS)
        info_resp.raise_for_status()
        info = info_resp.json()
    except Exception as exc:
        log.warning("google oauth failed: %s", exc)
        return None, "Google sign-in failed — try again"

    sub, email = info.get("sub"), (info.get("email") or "").lower()
    if not sub or not email:
        return None, "Google did not return an email address"

    user = database.get_user_by_google_sub(sub)
    if user:
        return user, None
    user = database.get_user_by_email(email)
    if user:  # existing password account -> link Google to it
        database.link_google_sub(user["id"], sub)
        return user, None

    first = database.count_users() == 0
    if not first and not config.ALLOW_SIGNUP:
        return None, "signup is closed on this server"
    user = database.create_user(email, info.get("name") or email.split("@")[0],
                                None, google_sub=sub, is_admin=first)
    _seed_new_user(user["id"], first)
    return user, None
