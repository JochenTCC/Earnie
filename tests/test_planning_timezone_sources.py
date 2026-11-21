"""Live UI clock and the SE price index follow the configured planning timezone."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

import config
from data import edibert_market_range as emr
from data import live_consumption


@pytest.fixture
def berlin(monkeypatch):
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Berlin")


@pytest.fixture
def lisbon(monkeypatch):
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Lisbon")


def test_live_ui_clock_uses_the_planning_timezone(lisbon):
    now = live_consumption._ui_slot_datetime()

    assert str(now.tzinfo) == "Europe/Lisbon"


def test_price_index_is_local_time_of_the_planning_timezone(lisbon):
    stamps = pd.Series(["2026-06-01T10:00:00Z", "2026-06-01T10:15:00Z"])

    frame = emr._local_frame(stamps, pd.Series([5.0, 7.0]))

    assert list(frame.index) == [pd.Timestamp("2026-06-01 11:00"), pd.Timestamp("2026-06-01 11:15")]


def test_archive_request_spans_whole_local_days(berlin, monkeypatch, tmp_path):
    seen = {}

    class _Archive:
        def __init__(self, zone, path, timeout):
            pass

        def prices(self, first, last):
            seen["first"], seen["last"] = first, last
            return type("Data", (), {"notes": [], "prices": {}})()

    monkeypatch.setattr(emr.api, "MarketArchive", _Archive)
    monkeypatch.setattr(emr, "runtime_path", lambda name: str(tmp_path / name))

    emr._archive_prices("DE", pd.Timestamp("2026-06-01 13:00"), pd.Timestamp("2026-06-02 08:00"), 5.0)

    assert str(seen["first"].tzinfo) == "Europe/Berlin"
    assert (seen["first"].hour, seen["last"] - seen["first"]) == (0, timedelta(days=2))
