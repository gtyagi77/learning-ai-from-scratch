"""SQLite persistence for articles and the portfolio."""

import json
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import config

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def init(db_path: Optional[str] = None) -> None:
    global _conn
    _conn = sqlite3.connect(db_path or config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                summary TEXT,
                published_ts REAL,
                fetched_ts REAL NOT NULL,
                sentiment REAL NOT NULL,
                tickers TEXT NOT NULL DEFAULT '[]',
                title_tickers TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_ts);
            CREATE TABLE IF NOT EXISTS portfolio (
                user_id INTEGER NOT NULL DEFAULT 0,
                ticker TEXT NOT NULL,
                name TEXT,
                shares REAL,
                cost_basis REAL,
                added_ts REAL NOT NULL,
                PRIMARY KEY (user_id, ticker)
            );
            CREATE TABLE IF NOT EXISTS financials_cache (
                ticker TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                payload TEXT NOT NULL,
                fetched_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                username TEXT,
                password_hash TEXT,
                google_sub TEXT UNIQUE,
                is_admin INTEGER NOT NULL DEFAULT 0,
                risk_profile TEXT NOT NULL DEFAULT 'balanced',
                hidden_sectors TEXT NOT NULL DEFAULT '[]',
                created_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_ts REAL NOT NULL,
                expires_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                quantity REAL NOT NULL,
                buy_price REAL NOT NULL,
                buy_date TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lots_user ON lots(user_id, ticker);
            CREATE TABLE IF NOT EXISTS custom_sectors (
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_ts REAL NOT NULL,
                PRIMARY KEY (user_id, name)
            );
            CREATE TABLE IF NOT EXISTS sector_members (
                user_id INTEGER NOT NULL,
                sector TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                added_ts REAL NOT NULL,
                PRIMARY KEY (user_id, sector, ticker)
            );
            CREATE INDEX IF NOT EXISTS idx_sector_members_user ON sector_members(user_id);
            CREATE TABLE IF NOT EXISTS digest_state (
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                last_action TEXT NOT NULL,
                sent_ts REAL NOT NULL,
                PRIMARY KEY (user_id, ticker)
            );
            """
        )
        # Migrations for databases created before these columns existed.
        cols = {row[1] for row in _conn.execute("PRAGMA table_info(articles)")}
        if "title_tickers" not in cols:
            _conn.execute(
                "ALTER TABLE articles ADD COLUMN title_tickers TEXT NOT NULL DEFAULT '[]'"
            )
        ucols = {row[1] for row in _conn.execute("PRAGMA table_info(users)")}
        if "hidden_sectors" not in ucols:
            _conn.execute(
                "ALTER TABLE users ADD COLUMN hidden_sectors TEXT NOT NULL DEFAULT '[]'"
            )
            # IT Services was already hidden from Market Scan for existing
            # accounts just before this migration (a hardcoded exclusion,
            # now replaced by this per-account setting) — preserve that
            # experience on upgrade rather than silently un-hiding it. Runs
            # only the first time this column is added, so it can never
            # clobber a later hide/unhide choice made through the UI.
            _conn.execute(
                "UPDATE users SET hidden_sectors = ? WHERE hidden_sectors = '[]'",
                (json.dumps(["IT Services"]),),
            )
        # Old single-user portfolio (ticker PK, no user_id) -> rebuild with a
        # composite (user_id, ticker) key; orphan rows go to user_id 0 and
        # are adopted by the first registered user (see adopt_orphan_portfolio).
        pcols = {row[1] for row in _conn.execute("PRAGMA table_info(portfolio)")}
        if "user_id" not in pcols:
            _conn.executescript(
                """
                ALTER TABLE portfolio RENAME TO portfolio_old;
                CREATE TABLE portfolio (
                    user_id INTEGER NOT NULL DEFAULT 0,
                    ticker TEXT NOT NULL,
                    name TEXT, shares REAL, cost_basis REAL,
                    added_ts REAL NOT NULL,
                    PRIMARY KEY (user_id, ticker)
                );
                INSERT INTO portfolio (user_id, ticker, name, shares, cost_basis, added_ts)
                    SELECT 0, ticker, name, shares, cost_basis, added_ts FROM portfolio_old;
                DROP TABLE portfolio_old;
                """
            )
        _conn.commit()


def insert_article(source: str, title: str, link: str, summary: str,
                   published_ts: Optional[float], sentiment: float,
                   tickers: List[str],
                   title_tickers: Optional[List[str]] = None) -> bool:
    """Insert an article; returns False if the link was already stored.

    title_tickers: the subset of tickers mentioned in the headline itself —
    used to weight headline-specific coverage above passing mentions."""
    with _lock:
        try:
            _conn.execute(
                "INSERT INTO articles (source, title, link, summary, published_ts,"
                " fetched_ts, sentiment, tickers, title_tickers)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (source, title, link, summary, published_ts, time.time(),
                 sentiment, json.dumps(tickers), json.dumps(title_tickers or [])),
            )
            _conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def has_article(link: str) -> bool:
    with _lock:
        row = _conn.execute("SELECT 1 FROM articles WHERE link = ?", (link,)).fetchone()
    return row is not None


def recent_articles(limit: int = 50, ticker: Optional[str] = None,
                    since_ts: Optional[float] = None) -> List[Dict]:
    query = "SELECT * FROM articles"
    clauses, params = [], []
    if ticker:
        clauses.append("tickers LIKE ?")
        params.append(f'%"{ticker.upper()}"%')
    if since_ts is not None:
        clauses.append("COALESCE(published_ts, fetched_ts) >= ?")
        params.append(since_ts)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY COALESCE(published_ts, fetched_ts) DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _conn.execute(query, params).fetchall()
    return [_article_dict(r) for r in rows]


def _article_dict(row: sqlite3.Row) -> Dict:
    d = dict(row)
    d["tickers"] = json.loads(d["tickers"])
    d["title_tickers"] = json.loads(d.get("title_tickers") or "[]")
    return d


def article_count() -> int:
    with _lock:
        return _conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def get_portfolio(user_id: Optional[int] = None) -> List[Dict]:
    """user_id=None returns the union across all users (crawler feeds)."""
    with _lock:
        if user_id is None:
            rows = _conn.execute(
                "SELECT MIN(user_id) AS user_id, ticker, MAX(name) AS name,"
                " NULL AS shares, NULL AS cost_basis, MIN(added_ts) AS added_ts"
                " FROM portfolio GROUP BY ticker ORDER BY ticker").fetchall()
        else:
            rows = _conn.execute(
                "SELECT * FROM portfolio WHERE user_id = ? ORDER BY ticker",
                (user_id,)).fetchall()
    return [dict(r) for r in rows]


def upsert_holding(ticker: str, name: Optional[str] = None,
                   shares: Optional[float] = None,
                   cost_basis: Optional[float] = None,
                   user_id: int = 0) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO portfolio (user_id, ticker, name, shares, cost_basis, added_ts)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id, ticker) DO UPDATE SET
                 name = COALESCE(excluded.name, portfolio.name),
                 shares = COALESCE(excluded.shares, portfolio.shares),
                 cost_basis = COALESCE(excluded.cost_basis, portfolio.cost_basis)""",
            (user_id, ticker.upper(), name, shares, cost_basis, time.time()),
        )
        _conn.commit()


def remove_holding(ticker: str, user_id: int = 0) -> bool:
    with _lock:
        cur = _conn.execute(
            "DELETE FROM portfolio WHERE ticker = ? AND user_id = ?",
            (ticker.upper(), user_id))
        _conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# users & sessions
# ---------------------------------------------------------------------------

def count_users() -> int:
    with _lock:
        return _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users() -> List[Dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def create_user(email: str, username: Optional[str], password_hash: Optional[str],
                google_sub: Optional[str] = None, is_admin: bool = False) -> Dict:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO users (email, username, password_hash, google_sub,"
            " is_admin, created_ts) VALUES (?,?,?,?,?,?)",
            (email.lower(), username, password_hash, google_sub,
             1 if is_admin else 0, time.time()))
        _conn.commit()
        row = _conn.execute("SELECT * FROM users WHERE id = ?",
                            (cur.lastrowid,)).fetchone()
    return dict(row)


def get_user_by_email(email: str) -> Optional[Dict]:
    with _lock:
        row = _conn.execute("SELECT * FROM users WHERE email = ?",
                            (email.lower(),)).fetchone()
    return dict(row) if row else None


def get_user_by_google_sub(sub: str) -> Optional[Dict]:
    with _lock:
        row = _conn.execute("SELECT * FROM users WHERE google_sub = ?",
                            (sub,)).fetchone()
    return dict(row) if row else None


def link_google_sub(user_id: int, sub: str) -> None:
    with _lock:
        _conn.execute("UPDATE users SET google_sub = ? WHERE id = ?", (sub, user_id))
        _conn.commit()


def set_risk_profile(user_id: int, profile: str) -> None:
    with _lock:
        _conn.execute("UPDATE users SET risk_profile = ? WHERE id = ?",
                      (profile, user_id))
        _conn.commit()


def get_hidden_sectors(user_id: int) -> List[str]:
    with _lock:
        row = _conn.execute("SELECT hidden_sectors FROM users WHERE id = ?",
                            (user_id,)).fetchone()
    return json.loads(row["hidden_sectors"]) if row and row["hidden_sectors"] else []


def set_hidden_sectors(user_id: int, sectors: List[str]) -> None:
    with _lock:
        _conn.execute("UPDATE users SET hidden_sectors = ? WHERE id = ?",
                      (json.dumps(sectors), user_id))
        _conn.commit()


def create_custom_sector(user_id: int, name: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO custom_sectors (user_id, name, created_ts) "
            "VALUES (?, ?, ?)", (user_id, name, time.time()))
        _conn.commit()


def get_custom_sectors(user_id: int) -> List[str]:
    with _lock:
        rows = _conn.execute(
            "SELECT name FROM custom_sectors WHERE user_id = ? ORDER BY created_ts",
            (user_id,)).fetchall()
    return [r["name"] for r in rows]


def delete_custom_sector(user_id: int, name: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "DELETE FROM custom_sectors WHERE user_id = ? AND name = ?",
            (user_id, name))
        _conn.execute(
            "DELETE FROM sector_members WHERE user_id = ? AND sector = ?",
            (user_id, name))
        _conn.commit()
    return cur.rowcount > 0


def add_sector_member(user_id: int, sector: str, ticker: str, name: Optional[str]) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO sector_members "
            "(user_id, sector, ticker, name, added_ts) VALUES (?, ?, ?, ?, ?)",
            (user_id, sector, ticker, name, time.time()))
        _conn.commit()


def remove_sector_member(user_id: int, sector: str, ticker: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "DELETE FROM sector_members WHERE user_id = ? AND sector = ? AND ticker = ?",
            (user_id, sector, ticker))
        _conn.commit()
    return cur.rowcount > 0


def get_sector_members(user_id: int) -> Dict[str, List[Tuple[str, str]]]:
    with _lock:
        rows = _conn.execute(
            "SELECT sector, ticker, name FROM sector_members "
            "WHERE user_id = ? ORDER BY sector, added_ts", (user_id,)).fetchall()
    out: Dict[str, List[Tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r["sector"], []).append((r["ticker"], r["name"] or r["ticker"]))
    return out


def adopt_orphan_portfolio(user_id: int) -> None:
    """Assign pre-auth (user_id 0) portfolio rows to the first real user."""
    with _lock:
        _conn.execute(
            "UPDATE OR IGNORE portfolio SET user_id = ? WHERE user_id = 0",
            (user_id,))
        _conn.execute("DELETE FROM portfolio WHERE user_id = 0")
        _conn.commit()


def create_session(token: str, user_id: int, ttl_seconds: float) -> None:
    now = time.time()
    with _lock:
        _conn.execute(
            "INSERT INTO sessions (token, user_id, created_ts, expires_ts)"
            " VALUES (?,?,?,?)", (token, user_id, now, now + ttl_seconds))
        _conn.execute("DELETE FROM sessions WHERE expires_ts < ?", (now,))
        _conn.commit()


def get_session_user(token: str) -> Optional[Dict]:
    with _lock:
        row = _conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ? AND s.expires_ts > ?",
            (token, time.time())).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        _conn.commit()


# ---------------------------------------------------------------------------
# holdings lots
# ---------------------------------------------------------------------------

def add_lot(user_id: int, ticker: str, quantity: float, buy_price: float,
            buy_date: Optional[str], source: str = "manual") -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO lots (user_id, ticker, quantity, buy_price, buy_date,"
            " source, created_ts) VALUES (?,?,?,?,?,?,?)",
            (user_id, ticker.upper(), quantity, buy_price, buy_date, source,
             time.time()))
        _conn.commit()
    return cur.lastrowid


def get_lots(user_id: int, ticker: Optional[str] = None) -> List[Dict]:
    q = "SELECT * FROM lots WHERE user_id = ?"
    params: list = [user_id]
    if ticker:
        q += " AND ticker = ?"
        params.append(ticker.upper())
    q += " ORDER BY COALESCE(buy_date, '9999') ASC, id ASC"  # FIFO
    with _lock:
        rows = _conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def delete_lot(lot_id: int, user_id: int) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM lots WHERE id = ? AND user_id = ?",
                            (lot_id, user_id))
        _conn.commit()
    return cur.rowcount > 0


def update_lot_date(lot_id: int, user_id: int, buy_date: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "UPDATE lots SET buy_date = ? WHERE id = ? AND user_id = ?",
            (buy_date, lot_id, user_id))
        _conn.commit()
    return cur.rowcount > 0


def clear_lots(user_id: int, source: Optional[str] = None) -> int:
    with _lock:
        if source:
            cur = _conn.execute(
                "DELETE FROM lots WHERE user_id = ? AND source = ?",
                (user_id, source))
        else:
            cur = _conn.execute("DELETE FROM lots WHERE user_id = ?", (user_id,))
        _conn.commit()
    return cur.rowcount


def get_cached_financials(ticker: str) -> Optional[Dict]:
    with _lock:
        row = _conn.execute(
            "SELECT source, payload, fetched_ts FROM financials_cache WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
    if not row:
        return None
    return {"source": row["source"], "payload": json.loads(row["payload"]),
            "fetched_ts": row["fetched_ts"]}


def put_cached_financials(ticker: str, source: str, payload: Dict) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO financials_cache (ticker, source, payload, fetched_ts)"
            " VALUES (?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET"
            " source=excluded.source, payload=excluded.payload,"
            " fetched_ts=excluded.fetched_ts",
            (ticker.upper(), source, json.dumps(payload), time.time()),
        )
        _conn.commit()


def prune_articles(max_age_days: float = 14.0) -> None:
    cutoff = time.time() - max_age_days * 86400
    with _lock:
        _conn.execute(
            "DELETE FROM articles WHERE COALESCE(published_ts, fetched_ts) < ?",
            (cutoff,),
        )


# ---------------------------------------------------------------------------
# digest state (last action sent per user/ticker, for the daily digest)
# ---------------------------------------------------------------------------

def get_digest_state(user_id: int) -> Dict[str, str]:
    """{ticker: last_action} as of the previous digest sent to this user."""
    with _lock:
        rows = _conn.execute(
            "SELECT ticker, last_action FROM digest_state WHERE user_id = ?",
            (user_id,)).fetchall()
    return {r["ticker"]: r["last_action"] for r in rows}


def get_last_digest_ts(user_id: int) -> Optional[float]:
    with _lock:
        row = _conn.execute(
            "SELECT MAX(sent_ts) AS ts FROM digest_state WHERE user_id = ?",
            (user_id,)).fetchone()
    return row["ts"] if row and row["ts"] is not None else None


def set_digest_state(user_id: int, actions: Dict[str, str]) -> None:
    now = time.time()
    with _lock:
        for ticker, action in actions.items():
            _conn.execute(
                """INSERT INTO digest_state (user_id, ticker, last_action, sent_ts)
                   VALUES (?,?,?,?)
                   ON CONFLICT(user_id, ticker) DO UPDATE SET
                     last_action = excluded.last_action, sent_ts = excluded.sent_ts""",
                (user_id, ticker.upper(), action, now))
        _conn.commit()
        _conn.commit()
