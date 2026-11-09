"""Debug dump captures the Live Sankey power read (not the legacy Loxone path)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from integrations import ehal_live, live_power_capture
from integrations.loxone_adapter import LoxoneAdapterError
from runtime_store import ehal_push_inbox

_NOW = datetime(2026, 11, 9, 17, 48, tzinfo=timezone.utc)
_POWER = {"pv": 0.0, "house": 0.42, "battery": 2.1, "grid": -1.68}
_GRID = "plant.sens_grid_power_active"
_ESS = "ess.15_kwh_speicher.sens_ess_power"
_PV = "inv.wr_main.sens_inv_power_pv"


def _ts(age_s: float) -> str:
    return (_NOW - timedelta(seconds=age_s)).isoformat()


@pytest.fixture
def _push_loxone(monkeypatch):
    monkeypatch.setattr(
        "runtime_store.ehal_setup.active_ehal_backend", lambda *a, **k: "loxone"
    )
    inbox = {
        _GRID: {"value": -1680.0, "last_ts": _ts(2), "parse_ok": True},
        _ESS: {"value": 2100.0, "last_ts": _ts(3), "parse_ok": True},
        "flex.pool.sens_power_act": {"value": 900.0, "last_ts": _ts(1)},
    }
    monkeypatch.setattr(ehal_push_inbox, "memory_snapshot", lambda: dict(inbox))
    # PV bound but never pushed (night): appears with its derived state.
    monkeypatch.setattr(
        "ehal.loxone_push_source.get_ehal_index",
        lambda: {_GRID: object(), _ESS: object(), _PV: object(), "flex.pool.x": object()},
    )


def test_capture_uses_sankey_read_and_push_status(monkeypatch, _push_loxone):
    monkeypatch.setattr(ehal_live, "read_live_power_kw_strict", lambda: dict(_POWER))
    monkeypatch.setattr(
        ehal_live,
        "fetch_live_power",
        lambda: pytest.fail("legacy Loxone path must not be used"),
    )

    out = live_power_capture.capture_live_power(now=_NOW)

    assert out["live_power"] == _POWER
    meta = out["live_power_capture"]
    assert meta["backend"] == "loxone"
    assert meta["error"] is None
    assert meta["push_signals_error"] is None
    assert meta["source"] == "ehal_live.read_live_power_kw"
    rows = {r["ehal_id"]: r for r in meta["push_signals"]}
    assert set(rows) == {_ESS, _PV, _GRID}  # power-flow kinds only
    assert rows[_GRID]["state"] == ehal_push_inbox.STATE_OK
    assert rows[_GRID]["value"] == -1680.0
    assert rows[_GRID]["age_s"] == pytest.approx(2.0)
    assert rows[_ESS]["state"] == ehal_push_inbox.STATE_OK
    assert rows[_PV]["state"] == ehal_push_inbox.STATE_ZERO_ASSUMED_NEVER
    assert rows[_PV]["last_ts"] is None


def test_capture_records_read_error_instead_of_dropping_it(monkeypatch, _push_loxone):
    def _fail():
        raise LoxoneAdapterError("Loxone marker read failed for sens_grid_power_active")

    monkeypatch.setattr(ehal_live, "read_live_power_kw_strict", _fail)

    out = live_power_capture.capture_live_power(now=_NOW)

    assert out["live_power"] is None
    assert out["live_power_capture"]["error"] == (
        "LoxoneAdapterError: Loxone marker read failed for sens_grid_power_active"
    )
    assert out["live_power_capture"]["push_signals"]  # still captured for triage


def test_capture_pull_backend_has_no_push_signals(monkeypatch):
    monkeypatch.setattr(
        "runtime_store.ehal_setup.active_ehal_backend", lambda *a, **k: "openems"
    )
    monkeypatch.setattr(ehal_live, "read_live_power_kw_strict", lambda: dict(_POWER))

    meta = live_power_capture.capture_live_power(now=_NOW)["live_power_capture"]

    assert meta["backend"] == "openems"
    assert meta["push_signals"] is None
    assert meta["push_signals_error"] is None


def test_read_live_power_kw_logs_and_returns_none_on_error(monkeypatch):
    def _fail():
        raise ValueError("incomplete coverage")

    monkeypatch.setattr(ehal_live, "read_live_power_kw_strict", _fail)
    assert ehal_live.read_live_power_kw() is None


def test_ui_save_debug_dump_writes_captured_live_power(monkeypatch):
    from ui import chart_debug_capture as ui_capture

    captured = {
        "live_power": dict(_POWER),
        "live_power_capture": {"backend": "loxone", "error": None},
    }
    seen: dict = {}

    def _build_chart_section(bundle, **kwargs):
        seen.update(kwargs)
        return {"live_power": kwargs["live_power"]}

    monkeypatch.setattr(ui_capture, "capture_live_power", lambda: captured)
    monkeypatch.setattr(ui_capture, "build_chart_section", _build_chart_section)
    monkeypatch.setattr(ui_capture, "_session_meta", lambda: {})
    monkeypatch.setattr(ui_capture, "_chart1_plotly_json", lambda bundle: None)
    monkeypatch.setattr(
        ui_capture,
        "write_debug_dump_zip",
        lambda **kwargs: seen.setdefault("zip_kwargs", kwargs) and "dump.zip",
    )

    path = ui_capture._save_debug_dump(
        SimpleNamespace(), 55.0, title=" t ", symptom=" s "
    )

    assert path == "dump.zip"
    assert seen["live_power"] == _POWER
    assert seen["live_power_capture"] == captured["live_power_capture"]
    assert seen["zip_kwargs"]["chart_payload"] == {"live_power": _POWER}
