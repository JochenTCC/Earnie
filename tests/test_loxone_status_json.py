"""Tests for Pattern B status.json payload builder."""
from __future__ import annotations

from integrations.loxone_status_json import build_loxone_status_payload


def test_status_payload_defaults_plant_keys() -> None:
    payload = build_loxone_status_payload(
        loxone_sent={},
        consumers=[],
        plant_io_index={},
        now_ts=1_700_000_000.9,
    )
    assert payload["heartbeat_ts"] == 1_700_000_000
    assert payload["set_ess_active_power"] == 0.0
    assert payload["set_ess_charge_power_limit"] == 0.0
    assert payload["set_ess_discharge_power_limit"] == 0.0
    assert payload["set_ess_mode"] == 0.0


def test_status_payload_maps_plant_merker_to_ehal_kw() -> None:
    payload = build_loxone_status_payload(
        loxone_sent={
            "Earnie_Batterie_Sollleistung": -2.5,
            "Earnie_LadeLeistungs-Limit": 5.0,
            "Earnie_EntladeLeistungs-Limit": 4.0,
            "Earnie_Steuerbefehl": 1.0,
        },
        consumers=[],
        plant_io_index={
            "Earnie_Batterie_Sollleistung": "set_ess_active_power",
            "Earnie_LadeLeistungs-Limit": "set_ess_charge_power_limit",
            "Earnie_EntladeLeistungs-Limit": "set_ess_discharge_power_limit",
            "Earnie_Steuerbefehl": "set_ess_mode",
        },
        now_ts=100.0,
    )
    assert payload["set_ess_active_power"] == -2.5
    assert payload["set_ess_charge_power_limit"] == 5.0
    assert payload["set_ess_discharge_power_limit"] == 4.0
    assert payload["set_ess_mode"] == 1.0


def test_status_payload_ev_and_flex_namespaced_keys() -> None:
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
            "loxone_outputs": {
                "enable_name": "Earnie_Verbraucher_Waschmaschine_Freigabe",
                "power_setpoint_name": "Earnie_Verbraucher_Waschmaschine_Ziel_kW",
            },
        },
        {
            "id": "waermepumpe",
            "type": "thermal_annual",
            "loxone_outputs": {"enable_name": "Earnie_Waermepumpe_Freigabe"},
        },
    ]
    payload = build_loxone_status_payload(
        loxone_sent={
            "Earnie_EAuto_Soll_A": 16.0,
            "Earnie_EAuto_Modus": 2.0,
            "Earnie_Verbraucher_Waschmaschine_Freigabe": 1.0,
            "Earnie_Verbraucher_Waschmaschine_Ziel_kW": 2.0,
            "Earnie_Waermepumpe_Freigabe": 1.0,
            "Earnie_Pool_Freigabe": 0.0,
            "Earnie_Pool_Filter_Freigabe": 1.0,
        },
        consumers=consumers,
        plant_io_index={},
        now_ts=50.0,
    )
    assert payload["ev.garage.Earnie_EAuto_Soll_A"] == 16.0
    assert payload["ev.garage.Earnie_EAuto_Modus"] == 2.0
    assert payload["flex.waschmaschine.Earnie_Verbraucher_Freigabe"] == 1.0
    assert payload["flex.waschmaschine.Earnie_Verbraucher_Ziel_kW"] == 2.0
    assert payload["flex.waermepumpe.Earnie_Waermepumpe_Freigabe"] == 1.0
    assert payload["Earnie_Pool_Freigabe"] == 0.0
    assert payload["Earnie_Pool_Filter_Freigabe"] == 1.0
