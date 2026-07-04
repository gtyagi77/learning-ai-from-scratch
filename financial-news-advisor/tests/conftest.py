import os
import secrets
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth, financials, fundamentals, macro  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_data(monkeypatch):
    """Keep tests off the network: no fundamentals/financials/macro unless a
    test stubs its own richer versions. Also reset the login rate limiter so
    tests registering many users don't trip it."""
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda s: None)
    monkeypatch.setattr(financials, "get_financials",
                        lambda s, allow_fetch=True: None)
    monkeypatch.setattr(macro, "macro_tilt", lambda s: (None, []))
    monkeypatch.setattr(macro, "get_indicators", lambda: {})
    auth._attempts.clear()


def make_authed_client(email: str = None, password: str = "password123"):
    """TestClient with a fresh registered+logged-in user (session cookie)."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    email = email or f"u{secrets.token_hex(6)}@test.local"
    resp = client.post("/api/auth/register",
                       json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture
def client():
    return make_authed_client()
