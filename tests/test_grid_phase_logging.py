"""Device detection (NILM stage 0, dev): grid meter per-phase fields, gate, push log, VO."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ehal.field_registry import loxone_spec
from ehal.grid_phase_fields import GRID_PHASE_KINDS, grid_phase_ids, grid_phase_log_ids
from ehal.profiles import list_device_roles, load_device_role
from ehal.qualified_ids import GRID_KINDS, qualified_plant_id
from ehal.signal_catalog import iter_catalog_entries
from runtime_store import ehal_push_inbox as inbox
from runtime_store import grid_phase_log
from runtime_store.env_vars import is_device_detection_enabled
from runtime_store.loxone_push_parse import is_valid_ehal_id
from scripts.pilot_vo_template_gen import grid_phase_signals, render_template
from ui import mode_selector

STAMP = datetime(2026, 10, 29, 8, 15, 3, 412000, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.delenv("EARNIE_UI_MODES", raising=False)
    inbox.reset_memory_for_tests()
    yield
    inbox.reset_memory_for_tests()


def _log_rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / grid_phase_log.LOG_DIRNAME / "2026-10-29.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_phase_kinds_exchange_as_grid_meter_and_pass_the_inbox() -> None:
    assert set(GRID_PHASE_KINDS) <= GRID_KINDS
    for kind, ehal_id in zip(GRID_PHASE_KINDS, grid_phase_ids()):
        assert ehal_id == f"grid.meter.{kind}" == qualified_plant_id(kind)
        assert is_valid_ehal_id(ehal_id)
    assert "grid.meter.sens_grid_power_active" in grid_phase_log_ids()


def test_role_file_holds_loxone_conversion_for_every_phase_kind() -> None:
    assert "grid_phases" in list_device_roles()
    doc = load_device_role("grid_phases")
    assert doc["status"] == "dev"
    assert [item["field"] for item in doc["ehal_fields"]] == list(GRID_PHASE_KINDS)
    for kind in GRID_PHASE_KINDS:
        assert loxone_spec(kind) is not None, kind
    # Per-phase power uses the same hub convention as the total (kW, + = import).
    total = loxone_spec("sens_grid_power_active")
    for phase in ("l1", "l2", "l3"):
        spec = loxone_spec(f"sens_grid_power_active_{phase}")
        assert (spec.unit, spec.ehal_unit, spec.factor, spec.sign) == (
            total.unit, total.ehal_unit, total.factor, total.sign,
        )


def test_phase_kinds_stay_out_of_the_public_mapping_catalog() -> None:
    house = {"plant": {"ehal_bindings": {"sens_grid_power_active": ""}}, "profiles": {}}
    kinds = {entry.ehal_id for entry in iter_catalog_entries(house, {})}
    assert not kinds & set(grid_phase_ids())
    assert GRID_PHASE_KINDS[0] not in json.dumps(load_device_role("grid"))


@pytest.mark.parametrize(
    ("raw", "enabled"),
    [
        (None, False),
        ("sunset2sunset,live_environment", False),
        ("sunset2sunset, Device_Detection", True),
        ("device_detection", True),
    ],
)
def test_gate_reads_earnie_ui_modes(monkeypatch, raw, enabled) -> None:
    if raw is not None:
        monkeypatch.setenv("EARNIE_UI_MODES", raw)
    assert is_device_detection_enabled() is enabled


def test_device_detection_alone_keeps_the_default_page(monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_UI_MODES", "device_detection")
    assert mode_selector.get_enabled_ui_mode_keys() == ["sunset2sunset", "device_detection"]
    monkeypatch.setenv("EARNIE_UI_MODES", "sunset2sunset,live_environment,device_detection")
    assert mode_selector.get_enabled_ui_mode_keys() == [
        "sunset2sunset", "live_environment", "device_detection",
    ]


def test_push_is_logged_only_with_the_gate(tmp_path, monkeypatch) -> None:
    inbox.record_push("grid.meter.sens_grid_voltage_l1", "231.4", "10.0.0.2", now=STAMP)
    assert _log_rows(tmp_path) == []

    monkeypatch.setenv("EARNIE_UI_MODES", "sunset2sunset,device_detection")
    inbox.record_push("grid.meter.sens_grid_voltage_l1", "231.4", "10.0.0.2", now=STAMP)
    inbox.record_push("grid.meter.sens_grid_power_active", "0.512", "10.0.0.2", now=STAMP)
    inbox.record_push("grid.meter.sens_grid_power_factor", "n/a", "10.0.0.2", now=STAMP)
    inbox.record_push("sens_temperature_outside", "12.0", "10.0.0.2", now=STAMP)

    assert _log_rows(tmp_path) == [
        {"ts": "2026-10-29T08:15:03.412+00:00", "id": "grid.meter.sens_grid_voltage_l1", "v": 231.4},
        {"ts": "2026-10-29T08:15:03.412+00:00", "id": "grid.meter.sens_grid_power_active", "v": 0.512},
        {"ts": "2026-10-29T08:15:03.412+00:00", "id": "grid.meter.sens_grid_power_factor", "v": None, "raw": "n/a"},
    ]


def test_vo_template_has_one_analog_push_per_phase_kind() -> None:
    signals = grid_phase_signals()
    assert [s.ehal_id for s in signals] == list(grid_phase_ids())
    assert not any(s.digital for s in signals)
    xml = render_template("Netz_Phasen", signals, host="10.0.0.5", port=8542, token="tok_12345678")
    for ehal_id in grid_phase_ids():
        assert f'CmdOn="/ehal/telemetry/{ehal_id}/&lt;v&gt;?t=tok_12345678"' in xml
    assert 'Address="http://10.0.0.5:8542"' in xml
