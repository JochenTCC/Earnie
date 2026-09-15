"""Tests for Loxone Meter energy (ΔkWh) helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.loxone_meter_energy import (
    bind_plant_meter_energy,
    channel_delta_kwh,
    controls_by_name,
    energy_from_io_all,
    meter_has_energy_states,
    meter_is_bidirectional,
    mono_delta_kwh,
    overlay_counter_on_closed,
    plant_energy_meter_names,
)


FIXTURE = Path(__file__).parent / "fixtures" / "loxapp3_greenfield.json"


def test_energy_from_io_all_parses_total_and_total_neg():
    ll = {
        "Code": "200",
        "0": {"name": "actual", "value": "1.2"},
        "1": {"name": "total", "value": "123.4 kWh"},
        "2": {"name": "totalNeg", "value": "45,6"},
    }
    energy = energy_from_io_all(ll)
    assert energy == {"total": 123.4, "total_neg": 45.6}


def test_energy_from_io_all_parses_http_meter_abbreviations():
    """Live /jdev/sps/io/{Meter}/all uses Pf/Mr/Mrc/Mrd, not total/totalNeg."""
    uni = {
        "Code": "200",
        "output0": {"name": "Pf", "value": 1.2},
        "output1": {"name": "Mr", "value": 24120.12},
    }
    assert energy_from_io_all(uni) == {"total": 24120.12}
    bipolar = {
        "Code": "200",
        "output0": {"name": "Pf", "value": -0.02},
        "output1": {"name": "Mrc", "value": 541.422},
        "output8": {"name": "Mrd", "value": 481.076},
    }
    assert energy_from_io_all(bipolar) == {
        "total": 541.422,
        "total_neg": 481.076,
    }


def test_greenfield_meters_expose_energy_states():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    by_name = controls_by_name(doc)
    grid = by_name["zähler netz"]
    pv = by_name["zähler pv-anlage"]
    assert meter_has_energy_states(grid)
    assert meter_is_bidirectional(grid)
    assert meter_has_energy_states(pv)
    assert not meter_is_bidirectional(pv)


def test_channel_delta_grid_bipolar_and_reset():
    assert mono_delta_kwh(10.0, 10.5) == pytest.approx(0.5)
    assert mono_delta_kwh(10.0, 9.0) is None
    start = {"total": 100.0, "total_neg": 50.0}
    end = {"total": 100.25, "total_neg": 50.1}
    assert channel_delta_kwh(start, end, bipolar=True) == pytest.approx(0.15)
    assert channel_delta_kwh(
        {"total": 1.0}, {"total": 1.5}, bipolar=False
    ) == pytest.approx(0.5)


def test_overlay_counter_on_closed_prefers_delta():
    closed = {
        "pv_kw": 4.0,
        "grid_kw": 1.0,
        "pv_energy_kwh": 1.0,
        "grid_energy_kwh": 0.25,
    }
    out = overlay_counter_on_closed(
        closed,
        open_readings={
            "pv": {"total": 10.0},
            "grid": {"total": 100.0, "total_neg": 20.0},
        },
        end_readings={
            "pv": {"total": 10.5},
            "grid": {"total": 100.1, "total_neg": 20.2},
        },
        dt_h=0.25,
    )
    assert out["pv_energy_kwh"] == pytest.approx(0.5)
    assert out["pv_kw"] == pytest.approx(2.0)
    assert out["grid_energy_kwh"] == pytest.approx(-0.1)
    assert out["grid_kw"] == pytest.approx(-0.4)
    assert out["ist_power_source"]["pv"] == "counter"
    assert out["ist_power_source"]["grid"] == "counter"
    assert out["ist_power_source"]["battery"] == "mean"


def test_plant_energy_meter_names_prefer_loxone_meter_energy():
    plant = {
        "ehal_bindings": {"sens_pv_production_active": "Merker PV"},
        "loxone_meter_energy": {
            "sens_pv_production_active": {
                "name": "Zähler PV-Anlage",
                "bidirectional": False,
            },
            "sens_grid_power_active": "Zähler Netz",
        },
    }
    names = plant_energy_meter_names(plant=plant)
    assert names["pv"] == "Zähler PV-Anlage"
    assert names["grid"] == "Zähler Netz"


def test_bind_plant_meter_energy():
    plant: dict = {}
    bind_plant_meter_energy(
        plant,
        ehal_field="sens_grid_power_active",
        meter_name="Zähler Netz",
        bidirectional=True,
    )
    assert plant["loxone_meter_energy"]["sens_grid_power_active"]["name"] == "Zähler Netz"
