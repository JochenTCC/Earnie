"""2.7.q Q1 gate: pin today's Loxone write decisions and status.json keys.

Thin characterization so Q8 qualified-only status.json keys cannot silently
change ESS modes, flex enable, EV current/mode, powerstation wire/status keys,
or the mixed legacy status.json payload shape.

Deferred (Shadow future undecided; minimize q.A):
- Shadow would-write old-vs-new comparison (``shadow_writes.jsonl``)
- Silent publish gate so planned setpoints never actuate via status.json
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from integrations.loxone_status_json import build_loxone_status_payload
from integrations.loxone_writes import (
    _flexible_consumer_output_values,
    build_sent_loxone_snapshot,
    flex_consumer_enable_value,
    map_ess_setpoints,
)
from optimizer.powerstation_live import _loxone_ps_wire_value, _status_key


# ---------------------------------------------------------------------------
# ESS modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "target", "max_c", "max_d", "active", "charge", "discharge", "hint"),
    [
        (0, 2.0, 5.0, 5.0, None, 5.0, 5.0, 0),
        (1, 2.5, 5.0, 5.0, -2.5, 5.0, 0.0, 1),
        (2, 1.0, 5.0, 5.0, None, 5.0, 0.0, 1),
        (3, 1.8, 5.0, 5.0, 1.8, 0.0, 5.0, 2),
        # asymmetric charge ≠ discharge (2.7.j)
        (0, 1.0, 5.0, 3.0, None, 5.0, 3.0, 0),
        (3, 2.0, 5.0, 3.0, 2.0, 0.0, 3.0, 2),
    ],
)
def test_char_map_ess_setpoints(
    mode, target, max_c, max_d, active, charge, discharge, hint
) -> None:
    assert map_ess_setpoints(mode, target, max_c, max_d) == (
        active,
        charge,
        discharge,
        hint,
    )


def test_char_ess_active_sticky_zero_when_none() -> None:
    """Automatik (mode 0): active_kw is None → snapshot writes sticky 0.0."""
    import integrations.loxone_writes as lw

    config_map = {
        "LOXONE_TARGET_ACTIVE_POWER_NAME": "Earnie_Batterie_Sollleistung",
        "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_LadeLeistungs-Limit",
        "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_EntladeLeistungs-Limit",
        "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
    }
    with (
        patch.object(lw.config, "get", side_effect=lambda name, **kw: config_map.get(name)),
        patch.object(
            lw.config,
            "get_battery_params",
            return_value={"max_charge_power_kw": 5.0, "max_discharge_power_kw": 4.0},
        ),
        patch.object(lw.config, "get_flexible_consumers", return_value=[]),
    ):
        snap = build_sent_loxone_snapshot(
            mode=0,
            target_power_kw=2.0,
            target_soc=50.0,
            consumer_powers={},
            charging_contexts={},
        )
    assert snap["Earnie_Batterie_Sollleistung"] == 0.0
    assert snap["Earnie_LadeLeistungs-Limit"] == 5.0
    assert snap["Earnie_EntladeLeistungs-Limit"] == 4.0
    assert snap["Earnie_Steuerbefehl"] == 0.0


# ---------------------------------------------------------------------------
# Flex enable
# ---------------------------------------------------------------------------


def _flex_consumer() -> dict:
    return {
        "id": "waschmaschine",
        "name": "Waschmaschine",
        "nominal_power_kw": 2.0,
        "ehal_bindings": {
            "flex.waschmaschine.set_enable": "Earnie_Verbraucher_Waschmaschine_Freigabe",
        },
    }


def test_char_flex_enable_on_when_power_positive() -> None:
    assert flex_consumer_enable_value(_flex_consumer(), {"waschmaschine": 1.2}, {}) == 1


def test_char_flex_enable_off_when_inactive_context() -> None:
    ctx = {"waschmaschine": {"active": False}}
    assert (
        flex_consumer_enable_value(_flex_consumer(), {"waschmaschine": 2.0}, ctx) == 0
    )


def test_char_flex_enable_status_key_shape() -> None:
    from integrations.ehal_write import clear_published_for_tests

    clear_published_for_tests()
    consumers = [
        {
            "id": "waschmaschine",
            "type": "generic",
            "ehal_bindings": {
                "flex.waschmaschine.set_enable": "Earnie_Verbraucher_Waschmaschine_Freigabe",
            },
        },
        {
            "id": "waermepumpe",
            "type": "thermal_annual",
            "ehal_bindings": {
                "flex.waermepumpe.set_enable": "Earnie_Waermepumpe_Freigabe",
            },
        },
    ]
    payload = build_loxone_status_payload(
        loxone_sent={
            "Earnie_Verbraucher_Waschmaschine_Freigabe": 1.0,
            "Earnie_Waermepumpe_Freigabe": 0.0,
            "Earnie_Pool_Freigabe": 1.0,
            "Earnie_Pool_Filter_Freigabe": 0.0,
        },
        consumers=consumers,
        plant_io_index={},
        now_ts=50.0,
    )
    # Q8: qualified Check keys only (legacy peers removed)
    assert "flex.waschmaschine.Earnie_Verbraucher_Freigabe" not in payload
    assert "Earnie_Pool_Freigabe" not in payload
    assert payload["consumer.waschmaschine.set_enable"] == 1.0
    assert payload["heatpump.waermepumpe.set_enable"] == 0.0
    assert payload["pool.pool_filter.set_enable"] == 0.0


# ---------------------------------------------------------------------------
# EV current / mode
# ---------------------------------------------------------------------------


def _ev_consumer() -> dict:
    return {
        "id": "garage",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "ehal_bindings": {
            "set_evcs_max_current": "Earnie_EAuto_Soll_A",
            "set_evcs_mode": "Earnie_EAuto_Modus",
        },
    }


def test_char_ev_charging_amps_and_mode_now() -> None:
    values = _flexible_consumer_output_values(
        _ev_consumer(), {"garage": 2.5}, {}, {"garage": 0}
    )
    assert values["Earnie_EAuto_Soll_A"] == pytest.approx(2.5 * 1000.0 / 230.0, abs=1e-3)
    assert values["Earnie_EAuto_Modus"] == 2.0  # now


def test_char_ev_pv_follow_pmax_amps_and_mode_pv() -> None:
    values = _flexible_consumer_output_values(
        _ev_consumer(), {"garage": 2.1}, {}, {"garage": 1}
    )
    assert values["Earnie_EAuto_Soll_A"] == pytest.approx(3.5 * 1000.0 / 230.0, abs=1e-3)
    assert values["Earnie_EAuto_Modus"] == 1.0  # pv


def test_char_ev_off_when_no_power() -> None:
    values = _flexible_consumer_output_values(
        _ev_consumer(), {"garage": 0.0}, {}, {"garage": 0}
    )
    assert values["Earnie_EAuto_Soll_A"] == pytest.approx(0.0)
    assert values["Earnie_EAuto_Modus"] == 0.0  # off


def test_char_ev_sofort_mode_only() -> None:
    ctx = {"garage": {"skip_loxone_output": True}}
    assert _flexible_consumer_output_values(_ev_consumer(), {"garage": 3.5}, ctx) == {
        "Earnie_EAuto_Modus": 2.0,
    }


def test_char_ev_status_keys() -> None:
    from integrations.ehal_write import clear_published_for_tests

    clear_published_for_tests()
    payload = build_loxone_status_payload(
        loxone_sent={"Earnie_EAuto_Soll_A": 16.0, "Earnie_EAuto_Modus": 1.0},
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
        now_ts=50.0,
    )
    assert "ev.garage.Earnie_EAuto_Soll_A" not in payload
    assert payload["evcs.garage.set_evcs_max_current"] == 16.0
    assert payload["evcs.garage.set_evcs_mode"] == 1.0


# ---------------------------------------------------------------------------
# Powerstation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value_w", "wire"),
    [
        ("set_ess_charge_power_limit", 2000.0, 2.0),
        ("set_ess_discharge_power_limit", 1500.0, 1.5),
        ("set_ess_active_power", 1500.0, 1.5),
        ("set_ess_mode", 1.0, 1.0),
    ],
)
def test_char_ps_wire_w_to_kw(kind: str, value_w: float, wire: float) -> None:
    assert _loxone_ps_wire_value(kind, value_w) == pytest.approx(wire)


def test_char_ps_status_key_pattern_b_not_flat() -> None:
    field = "ess.ecoflow_delta_3.set_ess_charge_power_limit"
    assert _status_key(field, "set_ess_charge_power_limit") == field
    src = "ess.ecoflow_delta_3.set_ess_source_select"
    assert _status_key(src, "set_ess_source_select") == src


def test_char_ps_status_does_not_overwrite_house_flat() -> None:
    from optimizer import powerstation_live as psl

    psl._last_powerstation_sent.clear()
    psl._last_powerstation_sent["ess.ecoflow_delta_3.set_ess_charge_power_limit"] = 0.0
    psl._last_powerstation_sent["ess.ecoflow_delta_3.set_ess_mode"] = 1.0
    try:
        payload = build_loxone_status_payload(
            loxone_sent={
                "Earnie_LadeLeistungs-Limit": 5.0,
                "Earnie_Steuerbefehl": 2.0,
            },
            consumers=[],
            plant_io_index={
                "Earnie_LadeLeistungs-Limit": "set_ess_charge_power_limit",
                "Earnie_Steuerbefehl": "set_ess_mode",
            },
            now_ts=100.0,
        )
    finally:
        psl._last_powerstation_sent.clear()
    assert payload["set_ess_charge_power_limit"] == 5.0
    assert payload["set_ess_mode"] == 2.0
    assert payload["ess.ecoflow_delta_3.set_ess_charge_power_limit"] == 0.0
    assert payload["ess.ecoflow_delta_3.set_ess_mode"] == 1.0


# ---------------------------------------------------------------------------
# status.json frozen snapshot (legacy mixed keys)
# ---------------------------------------------------------------------------


def test_char_status_json_legacy_payload_snapshot(monkeypatch) -> None:
    from integrations.ehal_write import clear_published_for_tests
    from optimizer import powerstation_live as psl

    clear_published_for_tests()
    monkeypatch.setattr(
        "optimizer.live_export_limit.live_unconstrained_export_kw", lambda: 15.0
    )
    psl._last_powerstation_sent.clear()
    psl._last_powerstation_sent["ess.ecoflow_delta_3.set_ess_charge_power_limit"] = 1.5
    consumers = [
        {
            "id": "garage",
            "type": "ev",
            "ehal_bindings": {
                "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                "set_evcs_mode": "Earnie_EAuto_Modus",
            },
        },
        {
            "id": "waschmaschine",
            "type": "generic",
            "ehal_bindings": {
                "flex.waschmaschine.set_enable": "Earnie_Verbraucher_Waschmaschine_Freigabe",
            },
        },
    ]
    try:
        payload = build_loxone_status_payload(
            loxone_sent={
                "Earnie_Batterie_Sollleistung": -2.5,
                "Earnie_LadeLeistungs-Limit": 5.0,
                "Earnie_EntladeLeistungs-Limit": 4.0,
                "Earnie_Steuerbefehl": 1.0,
                "Earnie_EAuto_Soll_A": 16.0,
                "Earnie_EAuto_Modus": 2.0,
                "Earnie_Verbraucher_Waschmaschine_Freigabe": 1.0,
                "Earnie_Pool_Freigabe": 0.0,
            },
            consumers=consumers,
            plant_io_index={
                "Earnie_Batterie_Sollleistung": "set_ess_active_power",
                "Earnie_LadeLeistungs-Limit": "set_ess_charge_power_limit",
                "Earnie_EntladeLeistungs-Limit": "set_ess_discharge_power_limit",
                "Earnie_Steuerbefehl": "set_ess_mode",
            },
            now_ts=1_700_000_000.9,
        )
    finally:
        psl._last_powerstation_sent.clear()

    assert payload["heartbeat_ts"] == 1_700_000_000
    assert payload["set_ess_active_power"] == -2.5
    assert payload["set_ess_charge_power_limit"] == 5.0
    assert payload["set_ess_discharge_power_limit"] == 4.0
    assert payload["set_ess_mode"] == 1.0
    assert payload["grid.meter.set_grid_export_power_limit"] == 15.0  # unconstrained ≠ 0
    assert "set_grid_export_power_limit" not in payload
    assert "ev.garage.Earnie_EAuto_Soll_A" not in payload
    assert "flex.waschmaschine.Earnie_Verbraucher_Freigabe" not in payload
    assert "Earnie_Pool_Freigabe" not in payload
    assert payload["ess.ecoflow_delta_3.set_ess_charge_power_limit"] == 1.5
    assert payload["evcs.garage.set_evcs_max_current"] == 16.0
    assert payload["evcs.garage.set_evcs_mode"] == 2.0
    assert payload["consumer.waschmaschine.set_enable"] == 1.0


# ---------------------------------------------------------------------------
# Silent / Shadow × status.json (current behaviour only; no new gate)
# ---------------------------------------------------------------------------


def test_char_shadow_does_not_start_status_listener(monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    from integrations.loxone_request_http import start_loxone_request_http

    assert start_loxone_request_http(18541) is None


def test_char_silent_status_json_still_serves_planned_setpoints() -> None:
    """Known risk until push-only cutover / optional silent publish gate.

    Plain silent skips direct ``/dev/sps/io`` writes but still builds
    ``loxone_sent``; ``status.json`` mirrors those planned values if the
    listener is running (Prod). No silent publish gate in q.A.
    """
    payload = build_loxone_status_payload(
        loxone_sent={
            "Earnie_Batterie_Sollleistung": -1.5,
            "Earnie_Steuerbefehl": 1.0,
        },
        consumers=[],
        plant_io_index={
            "Earnie_Batterie_Sollleistung": "set_ess_active_power",
            "Earnie_Steuerbefehl": "set_ess_mode",
        },
        now_ts=100.0,
    )
    assert payload["set_ess_active_power"] == -1.5
    assert payload["set_ess_mode"] == 1.0
