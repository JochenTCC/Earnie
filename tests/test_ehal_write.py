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

    names = {
        "LOXONE_TARGET_ACTIVE_POWER_NAME": "Active",
        "LOXONE_TARGET_CHARGE_POWER_NAME": "Charge",
        "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Discharge",
        "LOXONE_CONTROL_CMD_NAME": "Cmd",
    }
    io_index = {
        "Active": "set_ess_active_power",
        "Charge": "set_ess_charge_power_limit",
        "Discharge": "set_ess_discharge_power_limit",
        "Cmd": "set_ess_mode",
    }
    with (
        patch.object(lc.config, "get", side_effect=lambda name, **kw: names.get(name)),
        patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ),
        patch.object(lc, "_send_loxone_value_traced") as mock_http,
        patch(
            "integrations.ehal_debug_mapping.build_loxone_setpoint_io_index",
            return_value=io_index,
        ),
    ):
        records = lc.send_huawei_modbus_states(
            mode=3, target_power_kw=1.5, target_soc=55.0
        )

    assert len(records) == 4
    assert all(isinstance(r, LoxoneWriteRecord) and r.success for r in records)
    mock_http.assert_not_called()
    published = ew.load_published()
    assert published["set_ess_active_power"] == pytest.approx(1.5)
    assert published["set_ess_mode"] == pytest.approx(2.0)


def test_send_huawei_publishes_export_limit_qualified(publish_dir: Path, monkeypatch) -> None:
    from integrations import loxone_client as lc
    from integrations.loxone_comm_trace import LoxoneWriteRecord

    names = {
        "LOXONE_TARGET_ACTIVE_POWER_NAME": "Active",
        "LOXONE_TARGET_CHARGE_POWER_NAME": "Charge",
        "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Discharge",
        "LOXONE_CONTROL_CMD_NAME": "Cmd",
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
        patch.object(lc.config, "get", side_effect=lambda name, **kw: names.get(name)),
        patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ),
        patch.object(lc, "_send_loxone_value_traced") as mock_http,
        patch(
            "integrations.ehal_debug_mapping.build_loxone_setpoint_io_index",
            return_value=io_index,
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
    mock_http.assert_not_called()
    published = ew.load_published()
    assert published["grid.meter.set_grid_export_power_limit"] == pytest.approx(2.0)
    assert "set_grid_export_power_limit" not in published
