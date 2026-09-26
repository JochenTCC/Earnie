"""HA plant energy side channel for slot-Ist ΔkWh (2.6.c)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from integrations.ha_meter_energy import (
    parse_ha_energy_kwh,
    plant_energy_entity_ids,
    read_ha_plant_energy,
    read_plant_energy_readings,
)
from integrations.loxone_meter_energy import overlay_counter_on_closed
from runtime_store import power_interval_sampler as sampler


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


def test_plant_energy_entity_ids_omits_empty():
    assert plant_energy_entity_ids(
        {
            "sens_pv_energy": "sensor.pv_e",
            "sens_grid_energy_import": "",
            "sens_grid_power_active": "sensor.grid_p",
        }
    ) == {"sens_pv_energy": "sensor.pv_e"}


def test_read_plant_energy_readings_bipolar_shape():
    adapter = MagicMock()
    adapter.cfg.entities = {
        "sens_pv_energy": "sensor.pv_e",
        "sens_grid_energy_import": "sensor.grid_imp",
        "sens_grid_energy_export": "sensor.grid_exp",
    }

    def _state(entity_id: str) -> dict[str, Any]:
        values = {
            "sensor.pv_e": ("10.5", "kWh"),
            "sensor.grid_imp": ("100250", "Wh"),
            "sensor.grid_exp": ("20.05", "kWh"),
        }
        state, unit = values[entity_id]
        return {
            "entity_id": entity_id,
            "state": state,
            "attributes": {"unit_of_measurement": unit},
        }

    adapter.read_state.side_effect = _state
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


def _plant(*, pv: float, grid: float) -> dict[str, float]:
    return {"pv": pv, "house": 1.0, "grid": grid, "battery": -0.5}


def test_sampler_ha_energy_overlay(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 9, 14, 14, 0, 0)
    readings = {
        "open": {
            "pv": {"total": 10.0},
            "grid": {"total": 100.0, "total_neg": 20.0},
        },
        "close": {
            "pv": {"total": 10.5},
            "grid": {"total": 100.25, "total_neg": 20.05},
        },
    }
    phase = {"n": 0}

    def read_energy():
        phase["n"] += 1
        return readings["open"] if phase["n"] == 1 else readings["close"]

    for offset in (30, 60, 90):
        assert sampler.tick(
            now=start + timedelta(seconds=offset),
            force=True,
            state_path=str(state),
            read_plant=lambda: _plant(pv=9.0, grid=9.0),
            read_soc=lambda: 50.0,
            read_flex_chart=lambda: {},
            read_energy=read_energy,
        )
    closed = sampler.finalize_closed_interval(
        start, state_path=str(state), read_energy=read_energy
    )
    assert closed is not None
    assert closed["ist_power_source"]["pv"] == "counter"
    assert closed["ist_power_source"]["grid"] == "counter"
    assert closed["pv_kw"] == pytest.approx(2.0)


def test_sampler_without_energy_map_stays_mean(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 9, 14, 14, 0, 0)

    def read_energy():
        return None

    for offset in (30, 60, 90):
        assert sampler.tick(
            now=start + timedelta(seconds=offset),
            force=True,
            state_path=str(state),
            read_plant=lambda: _plant(pv=2.0, grid=1.0),
            read_soc=lambda: 50.0,
            read_flex_chart=lambda: {},
            read_energy=read_energy,
        )
    closed = sampler.finalize_closed_interval(
        start, state_path=str(state), read_energy=read_energy
    )
    assert closed is not None
    assert closed["ist_power_source"]["pv"] == "mean"
    assert closed["ist_power_source"]["grid"] == "mean"
    assert closed["pv_kw"] == pytest.approx(2.0)
