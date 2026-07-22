import hashlib
import hmac
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, database, digest, notify, recommender  # noqa: E402


def setup_module():
    database.init(":memory:")


# ---------------- notify.py: delivery channels ----------------

def test_send_telegram_request_shape(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "999")

    calls = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResp()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    assert notify.send_telegram("hello") is True
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://api.telegram.org/bottok123/sendMessage"
    assert payload == {"chat_id": "999", "text": "hello"}


def test_send_telegram_unconfigured_is_noop(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    assert notify.send_telegram("hello") is False


def test_send_hermes_hmac_signature(monkeypatch):
    monkeypatch.setattr(config, "HERMES_WEBHOOK_URL", "http://localhost:8644/webhooks/digest")
    monkeypatch.setattr(config, "HERMES_WEBHOOK_SECRET", "shh")

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    assert notify.send_hermes("hello") is True

    assert captured["url"] == "http://localhost:8644/webhooks/digest"
    ts = captured["headers"]["X-Webhook-Timestamp"]
    expected_sig = hmac.new(
        b"shh", f"{ts}.{captured['data']}".encode(), hashlib.sha256).hexdigest()
    assert captured["headers"]["X-Webhook-Signature-V2"] == f"sha256={expected_sig}"


def test_send_digest_reports_only_succeeding_channels(monkeypatch):
    monkeypatch.setattr(notify, "send_telegram", lambda text: False)
    monkeypatch.setattr(notify, "send_hermes", lambda text: True)
    assert notify.send_digest("hi") == ["hermes"]

    monkeypatch.setattr(notify, "send_telegram", lambda text: True)
    monkeypatch.setattr(notify, "send_hermes", lambda text: True)
    assert notify.send_digest("hi") == ["telegram", "hermes"]


# ---------------- digest.py: message building ----------------

def _make_authed_user():
    from tests.conftest import make_authed_client
    import secrets
    email = f"u{secrets.token_hex(6)}@test.local"
    client = make_authed_client(email=email)
    user = database.get_user_by_email(email)
    return client, user


def test_digest_reports_rating_change_and_new_headlines(monkeypatch):
    client, user = _make_authed_user()
    client.post("/api/portfolio", json={"ticker": "DIGCO.NS", "name": "Digest Co"})

    # Establish "last digest sent" first, then a headline that arrives
    # after it -- _build_message only reports news since that timestamp.
    database.set_digest_state(user["id"], {"DIGCO.NS": "HOLD"})
    database.insert_article(
        "Test", "Digest Co wins big order", "https://example.com/digco1",
        "", time.time() + 1, 0.6, ["DIGCO.NS"], ["DIGCO.NS"],
    )

    fake_rec = {"ticker": "DIGCO.NS", "action": "BUY"}
    monkeypatch.setattr(recommender, "cached_recommendations", lambda uid, p: [fake_rec])

    text = digest._build_message(user)
    assert text is not None
    assert "DIGCO: HOLD -> BUY" in text
    assert "Digest Co wins big order" in text
    # state should now reflect the new action
    assert database.get_digest_state(user["id"])["DIGCO.NS"] == "BUY"


def test_digest_returns_none_when_nothing_changed_and_no_news(monkeypatch):
    client, user = _make_authed_user()
    client.post("/api/portfolio", json={"ticker": "QUIETCO.NS", "name": "Quiet Co"})
    database.set_digest_state(user["id"], {"QUIETCO.NS": "HOLD"})

    fake_rec = {"ticker": "QUIETCO.NS", "action": "HOLD"}
    monkeypatch.setattr(recommender, "cached_recommendations", lambda uid, p: [fake_rec])

    assert digest._build_message(user) is None


def test_digest_skips_users_with_empty_portfolio():
    user = {"id": 999999, "risk_profile": "balanced"}
    assert digest._build_message(user) is None


# ---------------- recommender.py: warm cache ----------------

def test_cached_recommendations_hit_and_miss():
    recommender._rec_cache.clear()
    assert recommender.cached_recommendations(1, "balanced") is None

    recommender._rec_cache[1] = (time.time(), "balanced", [{"ticker": "X.NS"}])
    assert recommender.cached_recommendations(1, "balanced") == [{"ticker": "X.NS"}]
    # wrong profile -> treated as a miss
    assert recommender.cached_recommendations(1, "aggressive") is None

    # stale entry (older than 2x refresh interval) -> treated as a miss
    stale_ts = time.time() - (config.RECS_REFRESH_INTERVAL_SECONDS * 2 + 1)
    recommender._rec_cache[2] = (stale_ts, "balanced", [{"ticker": "Y.NS"}])
    assert recommender.cached_recommendations(2, "balanced") is None


def test_refresh_user_cache_populates_entry(monkeypatch):
    recommender._rec_cache.clear()
    monkeypatch.setattr(recommender, "recommend_portfolio_for_user",
                        lambda uid, profile: [{"ticker": "Z.NS", "action": "BUY"}])
    recs = recommender.refresh_user_cache(42, "balanced")
    assert recs == [{"ticker": "Z.NS", "action": "BUY"}]
    assert recommender.cached_recommendations(42, "balanced") == recs
    assert recommender.cache_age_seconds(42) is not None
    assert recommender.cache_age_seconds(43) is None


def test_recommendations_endpoint_serves_warm_cache_without_recompute(monkeypatch):
    client, user = _make_authed_user()
    client.post("/api/portfolio", json={"ticker": "CACHECO.NS", "name": "Cache Co"})

    calls = {"n": 0}

    def fake_live(uid, profile):
        calls["n"] += 1
        return [{"ticker": "CACHECO.NS", "action": "HOLD", "rationale": "r",
                 "implied_move_pct": None}]

    monkeypatch.setattr(recommender, "recommend_portfolio_for_user", fake_live)

    # No cache yet -> falls back to live compute.
    resp1 = client.get("/api/recommendations")
    assert resp1.status_code == 200
    assert calls["n"] == 1
    assert resp1.json()["cache_age_s"] is None

    # Warm the cache directly (as the background thread would).
    recommender.refresh_user_cache(user["id"], "balanced")
    calls["n"] = 0

    resp2 = client.get("/api/recommendations")
    assert resp2.status_code == 200
    assert calls["n"] == 0  # served from cache, no live recompute
    assert resp2.json()["cache_age_s"] is not None


# ---------------- prices.py: split success/failure TTL ----------------

def test_price_cache_failure_ttl_shorter_than_success(monkeypatch):
    from app import prices

    monkeypatch.setattr(config, "PRICE_CACHE_TTL_SECONDS", 1000)
    monkeypatch.setattr(config, "PRICE_CACHE_FAILURE_TTL_SECONDS", 1)
    prices._cache.clear()

    calls = {"n": 0}

    def fake_dispatch(symbol):
        calls["n"] += 1
        return None if calls["n"] == 1 else {"price": 1.0, "previous_close": 1.0,
                                              "currency": "INR", "change_pct": 0.0}

    monkeypatch.setattr(prices, "_dispatch", fake_dispatch)

    assert prices.get_quote("FAILCO.NS") is None
    assert calls["n"] == 1
    time.sleep(1.05)
    # failure TTL expired -> retried, this time succeeds
    result = prices.get_quote("FAILCO.NS")
    assert calls["n"] == 2
    assert result["price"] == 1.0

    # successful quote now cached under the much longer success TTL
    result2 = prices.get_quote("FAILCO.NS")
    assert calls["n"] == 2
    assert result2 == result
