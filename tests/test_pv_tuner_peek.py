"""Tests für PV-Integral (sens_pv_production_active × Δt)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from data import pv_tuner


class _FrozenDateTime(datetime):
    """datetime subclass with fixed now() for integral Δt tests."""

    _frozen: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        assert cls._frozen is not None
        return cls._frozen


def _seed_integral_state(path, *, power_w: float, ts: datetime) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "last_power_w": power_w,
                "last_ts": ts.isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )


def test_get_pv_delta_peek_does_not_write_state(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    past = datetime(2026, 7, 29, 12, 0, 0)
    now = past + timedelta(hours=1)
    _seed_integral_state(state_file, power_w=2000.0, ts=past)
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))
    _FrozenDateTime._frozen = now
    monkeypatch.setattr(pv_tuner, "datetime", _FrozenDateTime)

    with patch.object(
        pv_tuner.ehal_live, "read_live_power_kw", return_value={"pv": 2.0}
    ):
        delta = pv_tuner.get_pv_delta_peek()

    assert delta == 2.0  # avg 2000 W × 1 h → 2 kWh
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["last_power_w"] == 2000.0
    assert saved["last_ts"] == past.isoformat(timespec="seconds")


def test_get_pv_delta_and_update_writes_state(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    past = datetime(2026, 7, 29, 12, 0, 0)
    now = past + timedelta(hours=1)
    _seed_integral_state(state_file, power_w=1000.0, ts=past)
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))
    _FrozenDateTime._frozen = now
    monkeypatch.setattr(pv_tuner, "datetime", _FrozenDateTime)

    with patch.object(
        pv_tuner.ehal_live, "read_live_power_kw", return_value={"pv": 3.0}
    ):
        delta = pv_tuner.get_pv_delta_and_update()

    # avg (1000+3000)/2 W × 1 h = 2 kWh
    assert delta == 2.0
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["last_power_w"] == 3000.0
    assert saved["last_ts"] == now.isoformat(timespec="seconds")
    assert saved["schema_version"] == 2


def test_get_pv_delta_peek_without_state_returns_none(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))

    with patch.object(
        pv_tuner.ehal_live, "read_live_power_kw", return_value={"pv": 1.5}
    ):
        assert pv_tuner.get_pv_delta_peek() is None


def test_legacy_counter_state_migrates_without_delta(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    state_file.write_text(
        json.dumps({"schema_version": 1, "last_total_pv": 100.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))

    with patch.object(
        pv_tuner.ehal_live, "read_live_power_kw", return_value={"pv": 2.5}
    ):
        assert pv_tuner.get_pv_delta_and_update() is None

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["last_power_w"] == 2500.0
    assert "last_ts" in saved
