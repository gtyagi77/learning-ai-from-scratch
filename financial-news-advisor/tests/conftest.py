import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import financials, fundamentals, macro  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_data(monkeypatch):
    """Keep tests off the network: no fundamentals/financials/macro unless a
    test stubs its own richer versions."""
    monkeypatch.setattr(fundamentals, "get_fundamentals", lambda s: None)
    monkeypatch.setattr(financials, "get_financials",
                        lambda s, allow_fetch=True: None)
    monkeypatch.setattr(macro, "macro_tilt", lambda s: (None, []))
    monkeypatch.setattr(macro, "get_indicators", lambda: {})
