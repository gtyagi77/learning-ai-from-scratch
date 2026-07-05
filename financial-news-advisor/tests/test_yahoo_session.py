import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import yahoo_session  # noqa: E402


def _reset():
    yahoo_session._session = None
    yahoo_session._crumb = None
    yahoo_session._handshake_ok = False


class _FakeResp:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _HandshakeSession:
    """Fake requests.Session: succeeds at the cookie+crumb handshake, then
    answers the real request with chart_status/crumb_used so a test can
    check which crumb (if any) was actually sent."""

    def __init__(self, crumb, chart_status=200):
        self.headers = {}
        self.crumb = crumb
        self.chart_status = chart_status
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append((url, params))
        if "getcrumb" in url:
            return _FakeResp(200, text=self.crumb)
        if "fc.yahoo.com" in url:
            return _FakeResp(200)
        return _FakeResp(self.chart_status, json_data={"crumb_used": (params or {}).get("crumb")})


class _BlockedHandshakeSession:
    """Fake requests.Session: the crumb handshake itself is blocked/fails,
    but a plain (crumb-less) request to any other URL still succeeds — the
    realistic shape of "Yahoo challenges getcrumb but the chart endpoint
    still answers without one"."""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append((url, params))
        if "getcrumb" in url or "fc.yahoo.com" in url:
            raise RuntimeError("blocked")
        return _FakeResp(200, json_data={"crumb_used": (params or {}).get("crumb")})


def test_handshake_success_sets_crumb_and_session_ok(monkeypatch):
    _reset()
    fake = _HandshakeSession(crumb="abc123")
    monkeypatch.setattr(yahoo_session.requests, "Session", lambda: fake)

    assert yahoo_session.session_ok() is True
    assert yahoo_session._crumb == "abc123"


def test_get_appends_crumb_when_available(monkeypatch):
    _reset()
    fake = _HandshakeSession(crumb="abc123")
    monkeypatch.setattr(yahoo_session.requests, "Session", lambda: fake)

    resp = yahoo_session.get("https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS")
    assert resp.json()["crumb_used"] == "abc123"


def test_handshake_failure_degrades_without_raising(monkeypatch):
    _reset()
    fake = _BlockedHandshakeSession()
    monkeypatch.setattr(yahoo_session.requests, "Session", lambda: fake)

    assert yahoo_session.session_ok() is False
    # get() must still work (no crumb appended) instead of raising.
    resp = yahoo_session.get("https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS")
    assert resp.json()["crumb_used"] is None


def test_get_retries_once_on_401_with_a_fresh_crumb(monkeypatch):
    _reset()
    sessions = [_HandshakeSession(crumb="old-crumb", chart_status=401),
                _HandshakeSession(crumb="new-crumb", chart_status=200)]
    monkeypatch.setattr(yahoo_session.requests, "Session", lambda: sessions.pop(0))

    resp = yahoo_session.get("https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS")
    assert resp.status_code == 200
    assert resp.json()["crumb_used"] == "new-crumb"
