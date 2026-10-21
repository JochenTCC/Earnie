"""2.7.q Q5: write_field publish ledger + push-only Loud writes."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from integrations import ehal_write as ew
from integrations.loxone_status_json import build_loxone_status_payload
from runtime_store import loxone_callback_status as cbs


@pytest.fixture
def publish_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    ew.clear_published_for_tests()
    yield tmp_path
    ew.clear_published_for_tests()


def test_write_field_persists_and_loads(publish_dir: Path) -> None:
    record = ew.write_field("consumer.waschmaschine.set_enable", 1.0)
    assert record.published is True
    assert record.qualified_id == "consumer.waschmaschine.set_enable"
    assert record.value == 1.0
    assert record.published_at
    assert ew.load_published()["consumer.waschmaschine.set_enable"] == 1.0
    path = publish_dir / ew.PUBLISH_FILENAME
    assert path.is_file()


def test_write_field_empty_id_not_published(publish_dir: Path) -> None:
    record = ew.write_field("", 2.0)
    assert record.published is False
    assert ew.load_published() == {}


def test_status_payload_sees_published_value(publish_dir: Path) -> None:
    ew.write_field("evcs.garage.set_evcs_max_current", 12.0)
    payload = build_loxone_status_payload(
        loxone_sent={},
        consumers=[
            {
                "id": "garage",
                "type": "ev",
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ],
        plant_io_index={},
        now_ts=10.0,
    )
    assert payload["evcs.garage.set_evcs_max_current"] == 12.0
    assert "ev.garage.Earnie_EAuto_Soll_A" not in payload


def test_published_fetched_at_from_callback(publish_dir: Path) -> None:
    assert ew.published_fetched_at() is None
    cbs.record_loxone_callback("10.0.0.1")
    assert ew.published_fetched_at()


def test_send_huawei_publishes_only(publish_dir: Path) -> None:
    from integrations import loxone_client as lc
    from integrations.loxone_comm_trace import LoxoneWriteRecord

    ess_names = {
        "set_ess_active_power": "Active",
        "set_ess_charge_power_limit": "Charge",
        "set_ess_discharge_power_limit": "Discharge",
        "set_ess_mode": "Cmd",
    }
    io_index = {
        "Active": "set_ess_active_power",
        "Charge": "set_ess_charge_power_limit",
        "Discharge": "set_ess_discharge_power_limit",
        "Cmd": "set_ess_mode",
    }
    with (
        patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ),
        patch(
            "house_config.ess_bindings.resolve_primary_ess_binding",
            side_effect=lambda kind, **kw: ess_names.get(kind, ""),
        ),
        patch(
            "integrations.ehal_debug_mapping.build_loxone_setpoint_io_index",
            return_value=io_index,
        ),
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=False,
        ),
    ):
        records = lc.send_huawei_modbus_states(
            mode=3, target_power_kw=1.5, target_soc=55.0
        )

    assert len(records) == 4
    assert all(isinstance(r, LoxoneWriteRecord) and r.success for r in records)
    published = ew.load_published()
    assert published["set_ess_active_power"] == pytest.approx(1.5)
    assert published["set_ess_mode"] == pytest.approx(2.0)


def test_send_huawei_publishes_export_limit_qualified(publish_dir: Path, monkeypatch) -> None:
    from integrations import loxone_client as lc
    from integrations.loxone_comm_trace import LoxoneWriteRecord

    ess_names = {
        "set_ess_active_power": "Active",
        "set_ess_charge_power_limit": "Charge",
        "set_ess_discharge_power_limit": "Discharge",
        "set_ess_mode": "Cmd",
    }
    io_index = {
        "Active": "set_ess_active_power",
        "Charge": "set_ess_charge_power_limit",
        "Discharge": "set_ess_discharge_power_limit",
        "Cmd": "set_ess_mode",
    }
    monkeypatch.setattr(
        "optimizer.live_export_limit.live_unconstrained_export_kw", lambda: 15.0
    )
    monkeypatch.setattr(
        "house_config.ehal_bindings.resolve_plant_binding",
        lambda *_a, **_k: "Earnie_EinspeiseLeistungs-Limit",
    )
    with (
        patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ),
        patch(
            "house_config.ess_bindings.resolve_primary_ess_binding",
            side_effect=lambda kind, **kw: ess_names.get(kind, ""),
        ),
        patch(
            "integrations.ehal_debug_mapping.build_loxone_setpoint_io_index",
            return_value=io_index,
        ),
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=False,
        ),
    ):
        records = lc.send_huawei_modbus_states(
            mode=3,
            target_power_kw=1.5,
            target_soc=55.0,
            export_cap_kw=2.0,
        )

    assert len(records) == 5
    assert all(isinstance(r, LoxoneWriteRecord) and r.success for r in records)
    published = ew.load_published()
    assert published["grid.meter.set_grid_export_power_limit"] == pytest.approx(2.0)
    assert "set_grid_export_power_limit" not in published


def _other_process_writes(publish_dir: Path, qid: str, value: float, ts: str) -> None:
    import json
    import os

    path = publish_dir / ew.PUBLISH_FILENAME
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data[qid] = {"value": value, "published_at": ts}
    path.write_text(json.dumps(data), encoding="utf-8")
    # Make sure the mtime differs even on coarse file systems.
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))


def test_ledger_picks_up_values_written_by_another_process(publish_dir: Path) -> None:
    # HA testbed F17: the UI (Schreibtest) and the daemon (status.json) are two
    # processes sharing only ehal_published.json.
    ew.write_field("ess.house.set_ess_charge_power_limit", 0.0)
    assert ew.load_published()["ess.house.set_ess_charge_power_limit"] == 0.0
    _other_process_writes(
        publish_dir, "ess.house.set_ess_charge_power_limit", 1234.0, "2999-01-01T00:00:00+00:00"
    )
    assert ew.load_published()["ess.house.set_ess_charge_power_limit"] == 1234.0


def test_ledger_write_keeps_other_processes_entries(publish_dir: Path) -> None:
    ew.write_field("ess.house.set_ess_active_power", 100.0)
    _other_process_writes(
        publish_dir, "ess.house.set_ess_discharge_power_limit", 5000.0, "2999-01-01T00:00:00+00:00"
    )
    ew.write_field("ess.house.set_ess_active_power", 200.0)
    on_disk = ew._load_from_disk()
    assert on_disk["ess.house.set_ess_discharge_power_limit"]["value"] == 5000.0
    assert on_disk["ess.house.set_ess_active_power"]["value"] == 200.0


def test_ledger_ignores_older_disk_entries(publish_dir: Path) -> None:
    ew.write_field("ess.house.set_ess_active_power", 300.0)
    _other_process_writes(
        publish_dir, "ess.house.set_ess_active_power", 999.0, "2000-01-01T00:00:00+00:00"
    )
    assert ew.load_published()["ess.house.set_ess_active_power"] == 300.0
