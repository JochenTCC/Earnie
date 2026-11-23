"""Tests for Loxone Meter energy (ΔkWh) helpers — VO push / inbox (Q6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.loxone_meter_energy import (
    FIELD_CONSUMER_TOTAL,
    FIELD_GRID_EXPORT,
    FIELD_GRID_IMPORT,
    FIELD_PV_ENERGY,
    activate_consumer_energy_bindings,
    activate_plant_energy_bindings,
    channel_delta_kwh,
    controls_by_name,
    flex_energy_meter_config,
    meter_has_energy_states,
    meter_is_bidirectional,
    mono_delta_kwh,
    overlay_counter_on_closed,
    read_flex_energy_readings,
    read_plant_energy_readings,
)


FIXTURE = Path(__file__).parent / "fixtures" / "loxapp3_greenfield.json"


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
            "pv": {"total": 10.012},
            "grid": {"total": 100.012, "total_neg": 20.012},
        },
        end_readings={
            "pv": {"total": 10.512},
            "grid": {"total": 100.112, "total_neg": 20.212},
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
    assert out["ist_power_source"]["flex"] == {}


def test_overlay_counter_on_closed_flex_meter():
    closed = {
        "flex_kw": {"ev": 3.0, "wp": 1.0},
    }
    out = overlay_counter_on_closed(
        closed,
        open_readings={
            "flex": {
                "ev": {"total": 20.0},
                "wp": {"total": 5.012},
            }
        },
        end_readings={
            "flex": {
                "ev": {"total": 20.75},
                "wp": {"total": 4.012},
            }
        },
        dt_h=0.25,
    )
    assert out["flex_kw"]["ev"] == pytest.approx(3.0)
    assert out["flex_energy_kwh"]["ev"] == pytest.approx(0.75)
    assert out["flex_kw"]["wp"] == pytest.approx(1.0)
    assert out["ist_power_source"]["flex"]["ev"] == "counter"
    assert out["ist_power_source"]["flex"]["wp"] == "mean"


def test_activate_plant_energy_bindings():
    plant: dict = {"ehal_bindings": {"sens_grid_power_active": "Zähler Netz"}}
    activate_plant_energy_bindings(plant, grid=True, bidirectional=True)
    bindings = plant["ehal_bindings"]
    assert FIELD_GRID_IMPORT in bindings
    assert FIELD_GRID_EXPORT in bindings
    assert bindings["sens_grid_power_active"] == "Zähler Netz"


def test_activate_consumer_energy_bindings_mono_only():
    consumer: dict = {"id": "ev"}
    activate_consumer_energy_bindings(consumer)
    assert FIELD_CONSUMER_TOTAL in consumer["ehal_bindings"]
    assert "sens_energy_export" not in consumer["ehal_bindings"]


def test_activate_battery_energy_bindings_bipolar():
    from ehal.ess_fields import ess_field
    from integrations.loxone_meter_energy import (
        FIELD_ESS_CHARGE,
        FIELD_ESS_DISCHARGE,
        activate_battery_energy_bindings,
    )

    battery: dict = {"id": "15_kwh_speicher"}
    activate_battery_energy_bindings(battery, bidirectional=True)
    assert ess_field("15_kwh_speicher", FIELD_ESS_CHARGE) in battery["ehal_bindings"]
    assert ess_field("15_kwh_speicher", FIELD_ESS_DISCHARGE) in battery["ehal_bindings"]


def test_read_plant_energy_from_inbox_counters():
    from ehal.qualified_ids import qualified_plant_id

    plant = {
        "ehal_bindings": {
            FIELD_PV_ENERGY: "",
            FIELD_GRID_IMPORT: "",
            FIELD_GRID_EXPORT: "",
        }
    }
    inbox = {
        FIELD_PV_ENERGY: 10.5,
        qualified_plant_id(FIELD_GRID_IMPORT): 100.0,
        qualified_plant_id(FIELD_GRID_EXPORT): 20.0,
    }

    def read_counter(ehal_id: str, **_kwargs):
        return inbox.get(ehal_id)

    readings = read_plant_energy_readings(plant, read_counter=read_counter)
    assert readings["pv"] == {"total": 10.5}
    assert readings["grid"] == {"total": 100.0, "total_neg": 20.0}


def test_read_plant_energy_omits_stale_or_missing():
    plant = {"ehal_bindings": {FIELD_PV_ENERGY: ""}}

    def read_counter(_ehal_id: str, **_kwargs):
        return None

    assert read_plant_energy_readings(plant, read_counter=read_counter) == {}


def test_flex_energy_skips_shared_meter_and_reads_inbox():
    consumers = [
        {
            "id": "swimspa",
            "type": "thermal_rc",
            "ehal_bindings": {FIELD_CONSUMER_TOTAL: ""},
            "loxone_inputs": {"subtract_consumer_ids": ["pool_filter"]},
        },
        {
            "id": "kochen",
            "type": "generic",
            "ehal_bindings": {
                "flex.kochen.sens_power_act": "Zähler Kochen",
                FIELD_CONSUMER_TOTAL: "",
            },
        },
        {
            "id": "wallbox",
            "type": "ev",
            "ehal_bindings": {
                FIELD_CONSUMER_TOTAL: "",
            },
        },
    ]
    cfg = flex_energy_meter_config(consumers)
    assert "swimspa" not in cfg
    assert cfg["kochen"] == {}
    assert cfg["wallbox"] == {}

    inbox = {
        "consumer.kochen.sens_energy_total": 5.0,
        "ev.wallbox.sens_energy_total": 12.0,
        "ev.wallbox.sens_energy_export": 1.5,
    }

    def read_counter(ehal_id: str, **_kwargs):
        return inbox.get(ehal_id)

    readings = read_flex_energy_readings(consumers, read_counter=read_counter)
    assert "swimspa" not in readings
    assert readings["kochen"] == {"total": 5.0}
    assert readings["wallbox"] == {"total": 12.0}


def test_flex_energy_accepts_the_qualified_key_the_mapping_page_stores():
    """Bug: the mapping page stores ``consumer.<id>.sens_energy_total``; the reader only
    looked for the bare kind, so no consumer counter was ever used (all Ist from power)."""
    consumers = [
        {
            "id": "kochen",
            "type": "generic",
            "ehal_bindings": {"consumer.kochen.sens_energy_total": ""},
        },
        {
            "id": "waermepumpe",
            "type": "thermal_annual",
            "ehal_bindings": {"heatpump.waermepumpe.sens_energy_total": ""},
        },
        {
            # A qualified key of another consumer does not activate this one.
            "id": "tv",
            "type": "generic",
            "ehal_bindings": {"consumer.kochen.sens_energy_total": ""},
        },
    ]
    assert flex_energy_meter_config(consumers) == {"kochen": {}, "waermepumpe": {}}

    inbox = {
        "consumer.kochen.sens_energy_total": 156.5,
        "heatpump.waermepumpe.sens_energy_total": 103.858,
        "consumer.tv.sens_energy_total": 3774.0,
    }
    readings = read_flex_energy_readings(
        consumers, read_counter=lambda ehal_id, **_k: inbox.get(ehal_id)
    )
    assert readings == {"kochen": {"total": 156.5}, "waermepumpe": {"total": 103.858}}


def test_whole_kwh_counter_keeps_the_sample_mean(caplog, monkeypatch):
    """Bug (production 2026-11-23): the Loxone PV meter pushes whole kWh (``40240``). The
    counter overlay turned 0.3 kW of real PV into 0.0 kW for most slots and into
    1 kWh / 0.25 h = 4.0 kW for the slot where the counter stepped — Chart 1 showed
    lone 4 kW PV bars with matching feed-in, even at 18:00 in November."""
    import integrations.loxone_meter_energy as lme

    monkeypatch.setattr(lme, "_warned_coarse_channels", set())
    closed = {
        "pv_kw": 0.3,
        "pv_energy_kwh": 0.075,
        "grid_kw": 0.6,
        "flex_kw": {"trockner": 0.0},
    }
    with caplog.at_level("WARNING"):
        out = overlay_counter_on_closed(
            closed,
            open_readings={
                "pv": {"total": 40240.0},
                "grid": {"total": 2122.956, "total_neg": 594.318},
                "flex": {"trockner": {"total": 923.0}},
            },
            end_readings={
                "pv": {"total": 40241.0},
                "grid": {"total": 2123.106, "total_neg": 594.318},
                "flex": {"trockner": {"total": 924.0}},
            },
            dt_h=0.25,
        )
    assert out["pv_kw"] == pytest.approx(0.3)
    assert out["pv_energy_kwh"] == pytest.approx(0.075)
    assert out["ist_power_source"]["pv"] == "mean"
    assert out["flex_kw"]["trockner"] == pytest.approx(0.0)
    assert out["ist_power_source"]["flex"]["trockner"] == "mean"
    # The fine grid counter is still used.
    assert out["ist_power_source"]["grid"] == "counter"
    assert out["grid_kw"] == pytest.approx(0.6)
    assert out["coarse_counters"] == ["pv", "flex:trockner"]
    assert "zu grob" in caplog.text


@pytest.mark.parametrize(
    ("values", "coarse"),
    [
        ((40240.0, 40241.0), True),
        ((10.0, 10.5), True),
        ((923.0, None), True),
        ((40240.0, 40240.012), False),
        ((2122.956, 2123.0), False),
        ((100.0, 100.29), False),
        ((None, None), False),
    ],
)
def test_counter_readings_too_coarse(values, coarse):
    from integrations.loxone_meter_energy import counter_readings_too_coarse

    assert counter_readings_too_coarse(*values) is coarse


def test_rescaled_flex_counter_keeps_the_sample_mean(monkeypatch, caplog):
    """Bug (production 2026-11-23): a dryer counter rescaled in Loxone (923.0 -> 9233.11 kWh)
    booked 8310 kWh into one quarter hour. A jump no house can draw keeps the sample mean."""
    import integrations.loxone_meter_energy as lme

    monkeypatch.setattr(lme, "_warned_coarse_channels", set())
    out = overlay_counter_on_closed(
        {"flex_kw": {"trockner": 0.0, "tv": 0.1}},
        open_readings={"flex": {"trockner": {"total": 923.0}, "tv": {"total": 3775.792}}},
        end_readings={"flex": {"trockner": {"total": 9233.11}, "tv": {"total": 3775.825}}},
        dt_h=0.25,
    )
    assert out["flex_kw"]["trockner"] == pytest.approx(0.0)
    assert "trockner" not in out.get("flex_energy_kwh", {})
    assert out["ist_power_source"]["flex"]["trockner"] == "mean"
    assert out["ist_power_source"]["flex"]["tv"] == "counter"
    assert out["implausible_counters"] == ["flex:trockner"]
    assert "flex:trockner" in caplog.text


@pytest.mark.parametrize("channel", ["pv", "grid"])
def test_rescaled_plant_counter_keeps_the_sample_mean(channel):
    open_r = {"pv": {"total": 40239.96}, "grid": {"total": 2129.281, "total_neg": 594.318}}
    end_r = {"pv": {"total": 40240.01}, "grid": {"total": 2129.381, "total_neg": 594.318}}
    end_r[channel] = dict(end_r[channel], total=open_r[channel]["total"] * 10)
    out = overlay_counter_on_closed(
        {"pv_kw": 0.2, "grid_kw": 0.4}, open_readings=open_r, end_readings=end_r, dt_h=0.25
    )
    assert out["ist_power_source"][channel] == "mean"
    assert out[f"{channel}_kw"] == pytest.approx(0.2 if channel == "pv" else 0.4)
    assert out["implausible_counters"] == [channel]


def test_counter_delta_limit_follows_the_window():
    from integrations.loxone_meter_energy import COUNTER_MAX_POWER_KW, counter_delta_implausible

    limit = COUNTER_MAX_POWER_KW * 0.25
    assert not counter_delta_implausible(limit - 0.1, dt_h=0.25)
    assert counter_delta_implausible(limit + 0.1, dt_h=0.25)
    assert counter_delta_implausible(-(limit + 0.1), dt_h=0.25)
    assert not counter_delta_implausible(None, dt_h=0.25)
