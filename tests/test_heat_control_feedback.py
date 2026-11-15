"""HeatControl P1: level 3 feedback signals and the backend's store band in Live."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ehal.heat_fields import (
    HEAT_FEEDBACK_KINDS,
    HEAT_FIELD_LABELS_DE,
    HEAT_STORE_BAND_KINDS,
    THERMAL_ANNUAL_READ_KINDS,
)
from optimizer.thermal_live_band import (
    BAND_SOURCE_BACKEND,
    BAND_SOURCE_CONFIG,
    heat_storage_band_state,
    resolve_live_store_band,
)
from optimizer.thermal_live_store import (
    build_heat_storage_observability,
    plan_live_store_for_thermal_consumer,
)
from optimizer.thermal_model import ThermalBand

_SETPOINT = "get_temperature_heat_storage_setpoint"
_TOLERANCE = "get_temperature_heat_storage_tolerance"
_CONFIGURED = ThermalBand(setpoint_c=45.0, tolerance_c=5.0)


def _consumer(bindings: dict[str, str]) -> dict:
    return {
        "id": "wp_heating",
        "type": "thermal_annual",
        "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
        "nominal_power_kw": 3.0,
        "ehal_bindings": dict(bindings),
        "thermal": {
            "living_area_m2": 0.0,
            "heat_storage": {
                "volume_liters": 500.0,
                "heat_loss_kw_per_k": 0.02,
                "setpoint_c": _CONFIGURED.setpoint_c,
                "tolerance_c": _CONFIGURED.tolerance_c,
            },
        },
    }


def _hub(values: dict[str, float | None]):
    return patch(
        "integrations.loxone_client.fetch_loxone_generic_value",
        side_effect=lambda io_name: values.get(str(io_name)),
    )


def _plan(consumer: dict):
    return plan_live_store_for_thermal_consumer(
        consumer,
        house_profile={"consumers": [consumer]},
        ambient_forecast_c=[10.0] * 4,
        solar_forecast_kw=[0.0] * 4,
    )


def test_kind_lists_are_consistent():
    assert set(HEAT_STORE_BAND_KINDS) <= set(HEAT_FEEDBACK_KINDS)
    assert len(set(THERMAL_ANNUAL_READ_KINDS)) == len(THERMAL_ANNUAL_READ_KINDS)
    assert set(HEAT_FIELD_LABELS_DE) == set(THERMAL_ANNUAL_READ_KINDS)
    # The ready-by signals belong to HeatControl P8, not to P1.
    assert not any(
        "ready_by" in kind or kind.endswith("_ready") for kind in THERMAL_ANNUAL_READ_KINDS
    )


def test_band_unmapped_uses_configured_values():
    consumer = _consumer({"sens_temperature_heat_storage": "TempEq"})
    assert heat_storage_band_state(consumer)[0] == "not_configured"
    with _hub({"TempEq": 43.0}):
        plan = _plan(consumer)
    assert plan.band == _CONFIGURED
    assert plan.band_source == BAND_SOURCE_CONFIG


def test_band_both_mapped_uses_backend_values():
    consumer = _consumer(
        {"sens_temperature_heat_storage": "TempEq", _SETPOINT: "Soll", _TOLERANCE: "Tol"}
    )
    assert heat_storage_band_state(consumer) == ("available", ())
    with _hub({"TempEq": 43.0, "Soll": 52.5, "Tol": 2.5}):
        plan = _plan(consumer)
    assert plan.band == ThermalBand(setpoint_c=52.5, tolerance_c=2.5)
    assert plan.band_source == BAND_SOURCE_BACKEND
    # 43 °C is below the backend's band (50 … 52.5 °C) but inside the configured one.
    assert plan.forced_hour_flags[0]


def test_band_mapped_by_qualified_key():
    consumer = _consumer(
        {
            f"heatpump.wp_heating.{_SETPOINT}": "Soll",
            f"heatpump.wp_heating.{_TOLERANCE}": "Tol",
        }
    )
    with _hub({"Soll": 50.0, "Tol": 4.0}):
        live = resolve_live_store_band(consumer, _CONFIGURED)
    assert live.band == ThermalBand(50.0, 4.0)
    assert live.source == BAND_SOURCE_BACKEND


@pytest.mark.parametrize("mapped", [_SETPOINT, _TOLERANCE])
def test_band_only_one_mapped_keeps_configured_values(mapped, caplog):
    consumer = _consumer({mapped: "X"})
    state, missing = heat_storage_band_state(consumer)
    assert state == "incomplete"
    assert missing == tuple(k for k in HEAT_STORE_BAND_KINDS if k != mapped)
    with _hub({"X": 60.0}), caplog.at_level("WARNING"):
        live = resolve_live_store_band(consumer, _CONFIGURED)
    assert live.band == _CONFIGURED
    assert live.source == BAND_SOURCE_CONFIG
    assert "unvollständig gemappt" in caplog.text


def test_band_mapped_without_value_fails_loud():
    consumer = _consumer({_SETPOINT: "Soll", _TOLERANCE: "Tol"})
    with _hub({"Soll": 52.0, "Tol": None}):
        with pytest.raises(ValueError, match=_TOLERANCE):
            resolve_live_store_band(consumer, _CONFIGURED)


def test_band_negative_tolerance_fails_loud():
    consumer = _consumer({_SETPOINT: "Soll", _TOLERANCE: "Tol"})
    with _hub({"Soll": 52.0, "Tol": -1.0}):
        with pytest.raises(ValueError, match="negativ"):
            resolve_live_store_band(consumer, _CONFIGURED)


def test_fetch_heat_feedback_reads_mapped_kinds_in_ehal_units():
    from integrations.loxone_client import fetch_heat_feedback

    consumer = _consumer(
        {
            "sens_operating_mode": "Mode",
            "sens_heat_power": "Qth",
            "sens_temperature_source": "Sole",
            "sens_temperature_room": "Raum",
        }
    )
    with _hub({"Mode": 2.0, "Qth": 6.5, "Sole": 8.2}):
        values = fetch_heat_feedback(consumer)
    # Loxone reports kW, EHAL is W (role file); a mapped kind without a value is None.
    assert values == {
        "sens_operating_mode": 2.0,
        "sens_heat_power": 6500.0,
        "sens_temperature_source": 8.2,
        "sens_temperature_room": None,
    }


def test_observability_records_band_source_and_feedback():
    consumer = _consumer(
        {
            "sens_temperature_heat_storage": "TempEq",
            "sens_temperature_heat_storage_top": "TempTop",
            _SETPOINT: "Soll",
            _TOLERANCE: "Tol",
            "sens_operating_mode": "Mode",
        }
    )
    with _hub({"TempEq": 43.0, "TempTop": 51.0, "Soll": 52.0, "Tol": 3.0, "Mode": 1.0}):
        item = build_heat_storage_observability(
            consumer,
            house_profile={"consumers": [consumer]},
            ambient_forecast_c=[10.0] * 4,
            solar_forecast_kw=[0.0] * 4,
        )
    assert item["band_source"] == BAND_SOURCE_BACKEND
    assert item["readings_c"]["setpoint"] == 52.0
    assert item["readings_c"]["tolerance"] == 3.0
    assert item["feedback"] == {
        "sens_temperature_heat_storage_top": 51.0,
        _SETPOINT: 52.0,
        _TOLERANCE: 3.0,
        "sens_operating_mode": 1.0,
    }


def test_observability_unmapped_has_config_band_and_no_feedback():
    consumer = _consumer({"sens_temperature_heat_storage": "TempEq"})
    with _hub({"TempEq": 43.0}):
        item = build_heat_storage_observability(
            consumer,
            house_profile={"consumers": [consumer]},
            ambient_forecast_c=[10.0] * 4,
            solar_forecast_kw=[0.0] * 4,
        )
    assert item["band_source"] == BAND_SOURCE_CONFIG
    assert item["readings_c"]["setpoint"] == _CONFIGURED.setpoint_c
    assert item["feedback"] == {}


def test_live_lesen_lists_feedback_signals():
    from integrations import loxone_connectivity as lc
    from integrations.ehal_debug_mapping import consumer_live_read_kinds

    consumer = _consumer({_SETPOINT: "Soll", "sens_operating_mode": ""})
    assert set(HEAT_FEEDBACK_KINDS) <= set(consumer_live_read_kinds(consumer))
    with patch.object(lc.config, "get_flexible_consumers", return_value=[consumer]), patch.object(
        lc.config.CONFIG, "get_resolved_runtime_settings", return_value={}
    ):
        checks = lc.collect_read_checks()
    by_label = {label: io for label, io, _ in checks}
    assert by_label[f"heatpump.wp_heating.{_SETPOINT}"] == "Soll"
    # Activated without a hub address: read by its exchange ID from the push inbox.
    assert (
        by_label["heatpump.wp_heating.sens_operating_mode"]
        == "heatpump.wp_heating.sens_operating_mode"
    )
    assert f"heatpump.wp_heating.{_TOLERANCE}" not in by_label


def test_function_status_reports_incomplete_band_in_mapping_ui():
    from ehal.functions import incomplete_function_messages
    from house_config.ehal_bindings import THERMAL_ANNUAL_EHAL_FIELDS

    messages = incomplete_function_messages(
        {_SETPOINT: "Soll"}, fields=THERMAL_ANNUAL_EHAL_FIELDS
    )
    assert len(messages) == 1
    assert _TOLERANCE in messages[0]
    assert incomplete_function_messages({}, fields=THERMAL_ANNUAL_EHAL_FIELDS) == []


def test_configurator_note_states():
    from ui.house_config_live_band import live_band_override_note

    assert live_band_override_note(_consumer({})) is None
    level, text = live_band_override_note(_consumer({_SETPOINT: "Soll"}))
    assert level == "warning" and _TOLERANCE in text
    both = _consumer({_SETPOINT: "Soll", _TOLERANCE: "Tol"})
    with _hub({"Soll": 52.0, "Tol": 3.0}):
        level, text = live_band_override_note(both)
    assert level == "info"
    assert "52" in text and "3" in text and "Szenario-Explorer" in text
    with _hub({"Soll": 52.0}):
        level, text = live_band_override_note(both)
    assert level == "warning" and _TOLERANCE in text
