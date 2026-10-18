"""HA plant energy side channel via push inbox (Binding P5e)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from integrations.ha_meter_energy import (
    parse_ha_energy_kwh,
    plant_energy_entity_ids,
    read_ha_plant_energy,
    read_plant_energy_readings,
)
from integrations.loxone_meter_energy import overlay_counter_on_closed


def test_parse_ha_energy_kwh_wh_to_kwh():
    assert parse_ha_energy_kwh("1500", unit="Wh") == pytest.approx(1.5)
    assert parse_ha_energy_kwh("1.5", unit="kWh") == pytest.approx(1.5)
    assert parse_ha_energy_kwh("2,25", unit="kWh") == pytest.approx(2.25)
    assert parse_ha_energy_kwh("0.5", unit="MWh") == pytest.approx(500.0)


def test_parse_ha_energy_kwh_rejects_power_unit():
    from integrations.ha_units import UnitMismatchError

    with pytest.raises(UnitMismatchError):
        parse_ha_energy_kwh("1500", unit="W")


def test_parse_ha_energy_rejects_unavailable():
    with pytest.raises(ValueError):
        parse_ha_energy_kwh("unavailable", unit="kWh")


def test_plant_energy_entity_ids_keeps_activation_keys():
    assert plant_energy_entity_ids(
        {
            "sens_pv_energy": "",
            "sens_grid_energy_import": "",
            "sens_grid_power_active": "",
        }
    ) == {
        "sens_pv_energy": "",
        "sens_grid_energy_import": "",
    }


def test_read_plant_energy_readings_from_push(monkeypatch):
    adapter = MagicMock()
    adapter.cfg.entities = {
        "sens_pv_energy": "",
        "sens_grid_energy_import": "",
        "sens_grid_energy_export": "",
    }
    adapter.cfg.push_read_qids = {
        "sens_pv_energy": "grid.meter.sens_pv_energy",
        "sens_grid_energy_import": "grid.meter.sens_grid_energy_import",
        "sens_grid_energy_export": "grid.meter.sens_grid_energy_export",
    }

    def _read(qid: str) -> float | None:
        table = {
            "grid.meter.sens_pv_energy": 10.5,
            "grid.meter.sens_grid_energy_import": 100.25,
            "grid.meter.sens_grid_energy_export": 20.05,
        }
        return table.get(qid)

    monkeypatch.setattr(
        "integrations.ha_push_read.read_push_energy_kwh", _read
    )
    readings = read_plant_energy_readings(adapter)
    assert readings["pv"]["total"] == pytest.approx(10.5)
    assert readings["grid"]["total"] == pytest.approx(100.25)
    assert readings["grid"]["total_neg"] == pytest.approx(20.05)


def test_overlay_matches_loxone_math_from_ha_readings():
    open_r = {
        "pv": {"total": 10.0},
        "grid": {"total": 100.0, "total_neg": 20.0},
    }
    end_r = {
        "pv": {"total": 10.5},
        "grid": {"total": 100.25, "total_neg": 20.05},
    }
    closed = {
        "pv_kw": 9.0,
        "grid_kw": 9.0,
        "battery_kw": -0.5,
        "flex_kw": {},
    }
    out = overlay_counter_on_closed(
        closed, open_readings=open_r, end_readings=end_r, dt_h=0.25
    )
    assert out["ist_power_source"]["pv"] == "counter"
    assert out["ist_power_source"]["grid"] == "counter"
    assert out["pv_kw"] == pytest.approx(2.0)
    assert out["grid_kw"] == pytest.approx(0.8)


def test_read_ha_plant_energy_none_when_not_ha_backend(monkeypatch):
    monkeypatch.setattr(
        "integrations.ehal_live.is_ha_backend", lambda: False
    )
    assert read_ha_plant_energy() is None
