"""Tests für runtime_store.appliance_schedules."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import appliance_schedules

TZ = ZoneInfo("Europe/Vienna")


@pytest.fixture(autouse=True)
def _isolated_schedules_file(tmp_path, monkeypatch):
    path = tmp_path / "appliance_schedules.json"
    monkeypatch.setattr(appliance_schedules, "_schedules_path", lambda: str(path))
    yield path


def test_save_and_load_schedule():
    start = datetime(2026, 7, 8, 18, 0, tzinfo=TZ)
    entry = appliance_schedules.save_schedule(
        "waschmaschine",
        start_at=start,
        power_kw=2.0,
        runtime_h=2.0,
    )
    assert entry["power_kw"] == 2.0
    loaded = appliance_schedules.load_schedules()
    assert "waschmaschine" in loaded


def test_purge_expired_removes_finished_plan():
    start = datetime(2026, 7, 8, 10, 0, tzinfo=TZ)
    appliance_schedules.save_schedule(
        "waschmaschine",
        start_at=start,
        power_kw=2.0,
        runtime_h=1.0,
    )
    after = start + timedelta(hours=2)
    kept = appliance_schedules.purge_expired(after)
    assert kept == {}


def test_save_falls_back_to_direct_write_on_smb_replace_error(monkeypatch, tmp_path):
    path = tmp_path / "appliance_schedules.json"
    monkeypatch.setattr(appliance_schedules, "_schedules_path", lambda: str(path))
    start = datetime(2026, 7, 8, 18, 0, tzinfo=TZ)

    def _fail_replace(src, dst):
        raise PermissionError(13, "Zugriff verweigert", dst, dst, 5)

    monkeypatch.setattr(appliance_schedules.os, "replace", _fail_replace)
    appliance_schedules.save_schedule(
        "waschmaschine",
        start_at=start,
        power_kw=2.0,
        runtime_h=2.0,
    )
    assert path.is_file()
    assert "waschmaschine" in appliance_schedules.load_schedules()
