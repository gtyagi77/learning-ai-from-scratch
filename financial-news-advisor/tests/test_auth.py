import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, config, database  # noqa: E402
from app.main import app  # noqa: E402
from tests.conftest import make_authed_client  # noqa: E402


def setup_module():
    database.init(":memory:")


def test_password_hash_roundtrip():
    h = auth.hash_password("s3cret-password")
    assert h.startswith("scrypt$")
    assert auth.verify_password("s3cret-password", h)
    assert not auth.verify_password("wrong", h)
    assert not auth.verify_password("anything", None)
    assert not auth.verify_password("anything", "garbage")


def test_register_login_logout_flow():
    client = TestClient(app)
    r = client.post("/api/auth/register",
                    json={"email": "first@test.local", "password": "longenough1"})
    assert r.status_code == 200 and r.json()["is_admin"] is True  # first = admin

    me = client.get("/api/auth/me").json()
    assert me["authenticated"] and me["email"] == "first@test.local"

    # weak password / duplicate email rejected
    assert client.post("/api/auth/register",
                       json={"email": "x@test.local", "password": "short"}).status_code == 400
    assert client.post("/api/auth/register",
                       json={"email": "first@test.local", "password": "longenough1"}).status_code == 400

    # wrong password rejected; right one logs in
    fresh = TestClient(app)
    assert fresh.post("/api/auth/login",
                      json={"email": "first@test.local", "password": "nope-nope"}).status_code == 401
    assert fresh.post("/api/auth/login",
                      json={"email": "first@test.local", "password": "longenough1"}).status_code == 200
    assert fresh.get("/api/auth/me").json()["authenticated"]

    # logout revokes the server-side session
    fresh.post("/api/auth/logout")
    assert fresh.get("/api/auth/me").json()["authenticated"] is False


def test_login_rate_limited():
    client = TestClient(app)
    codes = []
    for _ in range(auth.RATE_LIMIT_ATTEMPTS + 2):
        codes.append(client.post("/api/auth/login",
                                 json={"email": "nobody@test.local",
                                       "password": "wrongwrong"}).status_code)
    assert 429 in codes


def test_users_cannot_see_each_others_data():
    a = make_authed_client()
    b = make_authed_client()

    a.post("/api/portfolio", json={"ticker": "ZYDUSLIFE.NS", "name": "Zydus"})
    a_tickers = {h["ticker"] for h in a.get("/api/portfolio").json()["holdings"]}
    b_tickers = {h["ticker"] for h in b.get("/api/portfolio").json()["holdings"]}
    assert "ZYDUSLIFE.NS" in a_tickers
    assert "ZYDUSLIFE.NS" not in b_tickers

    # Holdings lots are scoped too.
    csv_body = "symbol,quantity,buy_price,buy_date\nZYDUSLIFE.NS,10,900,2025-01-10\n"
    r = a.post("/api/holdings/upload", content=csv_body,
               headers={"Content-Type": "text/csv"})
    assert r.status_code == 200 and r.json()["imported"] == 1
    assert a.get("/api/holdings").json()["positions"]
    assert b.get("/api/holdings").json()["positions"] == []


def test_signup_can_be_closed(monkeypatch):
    make_authed_client()  # ensure at least one user exists
    monkeypatch.setattr(config, "ALLOW_SIGNUP", False)
    client = TestClient(app)
    r = client.post("/api/auth/register",
                    json={"email": "late@test.local", "password": "longenough1"})
    assert r.status_code == 400 and "closed" in r.json()["detail"]


def test_google_callback_stubbed(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "csec")

    class _Resp:
        def __init__(self, payload):
            self._p = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._p

    monkeypatch.setattr(auth.requests, "post",
                        lambda *a, **k: _Resp({"access_token": "tok"}))
    monkeypatch.setattr(auth.requests, "get",
                        lambda *a, **k: _Resp({"sub": "g-123",
                                               "email": "google@test.local",
                                               "name": "G User"}))

    # A state must come from google_auth_url(); forged states are rejected.
    user, err = auth.google_callback("code", "forged-state")
    assert user is None and "state" in err

    url = auth.google_auth_url()
    state = url.split("state=")[1].split("&")[0]
    user, err = auth.google_callback("code", state)
    assert err is None and user["email"] == "google@test.local"

    # Same Google account signs in again -> same user, no duplicate.
    url2 = auth.google_auth_url()
    state2 = url2.split("state=")[1].split("&")[0]
    user2, err2 = auth.google_callback("code", state2)
    assert err2 is None and user2["id"] == user["id"]


def test_marker_cookie_set_on_login_and_cleared_on_logout():
    from app.main import SEEN_COOKIE

    client = TestClient(app)
    email = "marker@test.local"
    client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert client.cookies.get(SEEN_COOKIE) == "1"
    assert client.cookies.get(auth.SESSION_COOKIE)  # HttpOnly, but TestClient jar still sees it

    client.post("/api/auth/logout")
    assert client.cookies.get(SEEN_COOKIE) is None
    assert client.cookies.get(auth.SESSION_COOKIE) is None


def test_google_redirect_uri_derived_from_request(monkeypatch):
    """Regression test: OAUTH_REDIRECT_BASE defaulting to localhost must not
    break Google sign-in on a real deployment — the redirect_uri sent to
    Google should match whatever host the browser actually used."""
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "csec")
    assert config.OAUTH_REDIRECT_BASE == config.OAUTH_REDIRECT_BASE_DEFAULT

    client = TestClient(app, follow_redirects=False)
    resp = client.get("/api/auth/google", headers={"host": "myapp.onrender.com",
                                                    "x-forwarded-proto": "https"})
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "redirect_uri=https%3A%2F%2Fmyapp.onrender.com" in location
    assert "127.0.0.1" not in location


def test_google_error_query_param_shows_friendly_message(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "csec")
    resp = TestClient(app, follow_redirects=False).get(
        "/api/auth/google/callback", params={"error": "access_denied"})
    assert resp.status_code == 302
    assert "auth_error=access_denied" in resp.headers["location"]


def test_origin_check_accepts_x_forwarded_host():
    client = make_authed_client()
    # Origin matches the proxy's original host (X-Forwarded-Host), not the
    # internal Host header uvicorn sees behind the proxy — must be allowed.
    r = client.post("/api/portfolio", json={"ticker": "INFY.NS"},
                    headers={"Origin": "https://public.example",
                            "X-Forwarded-Host": "public.example"})
    assert r.status_code == 200


def test_security_headers_present():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_cross_origin_writes_rejected():
    client = make_authed_client()
    r = client.post("/api/portfolio", json={"ticker": "INFY.NS"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_hidden_sectors_get_set_round_trip():
    user, _ = auth.register("sectors@test.local", "longenough1", None)
    assert database.get_hidden_sectors(user["id"]) == []
    database.set_hidden_sectors(user["id"], ["IT Services", "Defence"])
    assert database.get_hidden_sectors(user["id"]) == ["IT Services", "Defence"]


def test_hidden_sectors_migration_backfills_existing_users(tmp_path):
    import json
    import sqlite3
    import time

    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    # Pre-migration schema: users table without hidden_sectors.
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            username TEXT,
            password_hash TEXT,
            google_sub TEXT UNIQUE,
            is_admin INTEGER NOT NULL DEFAULT 0,
            risk_profile TEXT NOT NULL DEFAULT 'balanced',
            created_ts REAL NOT NULL
        )
    """)
    conn.execute("INSERT INTO users (email, created_ts) VALUES (?, ?)",
                ("legacy@test.local", time.time()))
    conn.commit()
    conn.close()

    database.init(db_path)
    try:
        row = database.get_user_by_email("legacy@test.local")
        assert json.loads(row["hidden_sectors"]) == ["IT Services"]
    finally:
        database.init(":memory:")  # restore in-memory DB for later tests


def test_set_hidden_sectors_endpoint_filters_scan():
    client = make_authed_client()
    assert client.post("/api/sectors/hidden",
                       json={"hidden": ["Not A Sector"]}).status_code == 400

    r = client.post("/api/sectors/hidden", json={"hidden": ["IT Services"]})
    assert r.status_code == 200 and r.json()["hidden_sectors"] == ["IT Services"]
    scan = client.get("/api/scan").json()
    assert "IT Services" not in {s["sector"] for s in scan["sectors"]}

    client.post("/api/sectors/hidden", json={"hidden": []})
    scan = client.get("/api/scan").json()
    assert "IT Services" in {s["sector"] for s in scan["sectors"]}


def test_custom_sectors_and_members_db_round_trip():
    user, _ = auth.register("customsectors@test.local", "longenough1", None)
    uid = user["id"]
    assert database.get_custom_sectors(uid) == []
    database.create_custom_sector(uid, "My Watchlist")
    assert database.get_custom_sectors(uid) == ["My Watchlist"]

    database.add_sector_member(uid, "My Watchlist", "ZOMATO.NS", "Zomato")
    database.add_sector_member(uid, "IT Services", "PERSISTENT.NS", "Persistent Systems")
    members = database.get_sector_members(uid)
    assert members["My Watchlist"] == [("ZOMATO.NS", "Zomato")]
    assert members["IT Services"] == [("PERSISTENT.NS", "Persistent Systems")]

    assert database.remove_sector_member(uid, "IT Services", "PERSISTENT.NS") is True
    assert database.remove_sector_member(uid, "IT Services", "PERSISTENT.NS") is False
    assert "IT Services" not in database.get_sector_members(uid)

    # Deleting a custom sector cascades its members.
    assert database.delete_custom_sector(uid, "My Watchlist") is True
    assert database.get_custom_sectors(uid) == []
    assert database.get_sector_members(uid) == {}


def test_search_companies_endpoint():
    client = make_authed_client()
    r = client.get("/api/companies/search", params={"q": "infosys"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(x["ticker"] == "INFY.NS" for x in results)


def test_create_and_delete_custom_sector_endpoint():
    client = make_authed_client()
    r = client.post("/api/sectors", json={"name": "My Watchlist"})
    assert r.status_code == 200 and r.json()["name"] == "My Watchlist"

    # Duplicate (case-insensitive) and curated names are rejected.
    assert client.post("/api/sectors", json={"name": "my watchlist"}).status_code == 400
    assert client.post("/api/sectors", json={"name": "Nifty 50"}).status_code == 400
    assert client.post("/api/sectors", json={"name": "  "}).status_code == 400

    assert client.delete("/api/sectors/My Watchlist").status_code == 200
    # Curated sectors can't be deleted through this endpoint.
    assert client.delete("/api/sectors/Nifty 50").status_code == 404


def test_sector_members_endpoint_add_remove_and_validation():
    client = make_authed_client()
    client.post("/api/sectors", json={"name": "My Watchlist"})

    r = client.post("/api/sectors/members",
                    json={"sector": "My Watchlist", "ticker": "reliance", "name": "Reliance"})
    assert r.status_code == 200

    # Curated sectors accept additions too.
    r2 = client.post("/api/sectors/members",
                     json={"sector": "IT Services", "ticker": "PERSISTENT.NS"})
    assert r2.status_code == 200

    assert client.post("/api/sectors/members",
                       json={"sector": "Not A Sector", "ticker": "TCS.NS"}).status_code == 400
    assert client.post("/api/sectors/members",
                       json={"sector": "My Watchlist", "ticker": "BAD TICKER!"}).status_code == 422

    assert client.delete("/api/sectors/members/My Watchlist/RELIANCE.NS").status_code == 200
    assert client.delete("/api/sectors/members/My Watchlist/RELIANCE.NS").status_code == 404


def test_scan_reflects_custom_sector_and_added_member(monkeypatch):
    import time as _time

    from app import prices
    monkeypatch.setattr(prices, "get_quote", lambda s: None)

    client = make_authed_client()
    client.post("/api/sectors", json={"name": "My Watchlist"})
    client.post("/api/sectors/members",
               json={"sector": "My Watchlist", "ticker": "WIDGETCO", "name": "Widget Corp"})
    client.post("/api/sectors/members",
               json={"sector": "Defence", "ticker": "GADGETCO", "name": "Gadget Corp"})
    database.insert_article("Test", "Gadget Corp swings to profit, shares rally",
                            "https://example.com/gadgetco", "", _time.time() - 600, 0.6,
                            ["GADGETCO"])

    scan = client.get("/api/scan").json()["sectors"]
    by_name = {s["sector"]: s for s in scan}
    assert by_name["My Watchlist"]["is_custom"] is True
    assert by_name["My Watchlist"]["watched"] == 1
    defence_rows = {r["ticker"]: r for r in by_name["Defence"]["results"]}
    assert defence_rows["GADGETCO"]["custom"] is True
