import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import fundamentals  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_fundamentals(monkeypatch):
    """Keep tests off the network: no fundamentals unless a test stubs its
    own. Tests that need valuation data monkeypatch get_fundamentals again."""
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda s: None)
