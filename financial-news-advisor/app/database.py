"""SQLite persistence for articles and the portfolio."""

import json
import sqlite3
import threading
import time
from typing import Dict, List, Optional

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
                ticker TEXT PRIMARY KEY,
                name TEXT,
                shares REAL,
                cost_basis REAL,
                added_ts REAL NOT NULL
            );
            """
        )
        # Migration for databases created before title_tickers existed.
        cols = {row[1] for row in _conn.execute("PRAGMA table_info(articles)")}
        if "title_tickers" not in cols:
            _conn.execute(
                "ALTER TABLE articles ADD COLUMN title_tickers TEXT NOT NULL DEFAULT '[]'"
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


def get_portfolio() -> List[Dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM portfolio ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


def upsert_holding(ticker: str, name: Optional[str] = None,
                   shares: Optional[float] = None,
                   cost_basis: Optional[float] = None) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO portfolio (ticker, name, shares, cost_basis, added_ts)
               VALUES (?,?,?,?,?)
               ON CONFLICT(ticker) DO UPDATE SET
                 name = COALESCE(excluded.name, portfolio.name),
                 shares = COALESCE(excluded.shares, portfolio.shares),
                 cost_basis = COALESCE(excluded.cost_basis, portfolio.cost_basis)""",
            (ticker.upper(), name, shares, cost_basis, time.time()),
        )
        _conn.commit()


def remove_holding(ticker: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker.upper(),))
        _conn.commit()
    return cur.rowcount > 0


def prune_articles(max_age_days: float = 14.0) -> None:
    cutoff = time.time() - max_age_days * 86400
    with _lock:
        _conn.execute(
            "DELETE FROM articles WHERE COALESCE(published_ts, fetched_ts) < ?",
            (cutoff,),
        )
        _conn.commit()
