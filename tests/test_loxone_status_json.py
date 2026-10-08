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


def test_status_payload_export_limit_defaults_to_unconstrained(monkeypatch) -> None:
    """Nothing sent yet must not read as 0 kW (= Einspeisesperre) on the VI."""
    monkeypatch.setattr(
        "optimizer.live_export_limit.live_unconstrained_export_kw", lambda: 15.0
    )
    payload = build_loxone_status_payload(
        loxone_sent={}, consumers=[], plant_io_index={}, now_ts=100.0
    )
    assert payload["set_grid_export_power_limit"] == 15.0


def test_status_payload_export_limit_fallback_when_plant_unknown(monkeypatch) -> None:
    def _boom() -> float:
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(
        "optimizer.live_export_limit.live_unconstrained_export_kw", _boom
    )
    payload = build_loxone_status_payload(
        loxone_sent={}, consumers=[], plant_io_index={}, now_ts=100.0
    )
    assert payload["set_grid_export_power_limit"] == 1000.0


def test_status_payload_export_limit_sent_value_wins(monkeypatch) -> None:
    monkeypatch.setattr(
        "optimizer.live_export_limit.live_unconstrained_export_kw", lambda: 15.0
    )
    payload = build_loxone_status_payload(
        loxone_sent={"Earnie_EinspeiseLeistungs-Limit": 0.0},
        consumers=[],
        plant_io_index={
            "Earnie_EinspeiseLeistungs-Limit": "set_grid_export_power_limit"
        },
        now_ts=100.0,
    )
    assert payload["set_grid_export_power_limit"] == 0.0


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
            "Earnie_EAuto_Soll_A": 16.0,
            "Earnie_EAuto_Modus": 2.0,
            "Earnie_Verbraucher_Waschmaschine_Freigabe": 1.0,
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
    assert "flex.waschmaschine.Earnie_Verbraucher_Ziel_kW" not in payload
    assert payload["flex.waermepumpe.Earnie_Waermepumpe_Freigabe"] == 1.0
    assert payload["Earnie_Pool_Freigabe"] == 0.0
    assert payload["Earnie_Pool_Filter_Freigabe"] == 1.0


def test_status_payload_maps_legacy_swimspa_enable_to_pool_keys() -> None:
    consumers = [
        {
            "id": "swimspa",
            "type": "thermal_rc",
            "ehal_bindings": {
                "flex.swimspa.set_enable": "Earnie_SwimSpa_Freigabe",
            },
        },
        {
            "id": "pool_filter",
            "daily_target_source": "loxone_remaining_hours",
            "ehal_bindings": {
                "flex.pool_filter.set_enable": "Earnie_Swimspa_Filter_Freigabe",
            },
        },
    ]
    payload = build_loxone_status_payload(
        loxone_sent={
            "Earnie_SwimSpa_Freigabe": 1.0,
            "Earnie_Swimspa_Filter_Freigabe": 0.0,
        },
        consumers=consumers,
        plant_io_index={},
        now_ts=50.0,
    )
    assert payload["Earnie_Pool_Freigabe"] == 1.0
    assert payload["Earnie_Pool_Filter_Freigabe"] == 0.0
    assert "flex.pool_filter.Earnie_Verbraucher_Freigabe" not in payload
    assert "flex.swimspa.Earnie_Verbraucher_Freigabe" not in payload


def test_status_payload_greenfield_pool_uses_configured_enable_only() -> None:
    """Only the configured Freigabe name is read — no SwimSpa alias remap."""
    consumers = [
        {
            "id": "pool_swimspa",
            "type": "thermal_rc",
            "ehal_bindings": {"flex.pool_swimspa.set_enable": "Earnie_Pool_Freigabe"},
        },
        {
            "id": "pool_filter",
            "type": "generic",
            "ehal_bindings": {"flex.pool_filter.set_enable": "Earnie_Pool_Filter_Freigabe"},
        },
    ]
    payload = build_loxone_status_payload(
        loxone_sent={
            "Earnie_Pool_Freigabe": 1.0,
            "Earnie_Swimspa_Filter_Freigabe": 0.0,
        },
        consumers=consumers,
        plant_io_index={},
        now_ts=50.0,
    )
    assert payload["Earnie_Pool_Freigabe"] == 1.0
    assert "Earnie_Pool_Filter_Freigabe" not in payload


def _clear_powerstation_cache():
    from optimizer import powerstation_live as psl

    psl._last_powerstation_sent.clear()
    return psl


def test_powerstation_values_use_pattern_b_keys_and_leave_house_keys_alone() -> None:
    """A powerstation write must not overwrite the house battery's flat status keys."""
    psl = _clear_powerstation_cache()
    psl._last_powerstation_sent["ess.ecoflow_delta_3.set_ess_charge_power_limit"] = 0.0
    psl._last_powerstation_sent["ess.ecoflow_delta_3.set_ess_mode"] = 1.0
    try:
        payload = build_loxone_status_payload(
            loxone_sent={"Earnie_LadeLeistungs-Limit": 5.0, "Earnie_Steuerbefehl": 2.0},
            consumers=[],
            plant_io_index={
                "Earnie_LadeLeistungs-Limit": "set_ess_charge_power_limit",
                "Earnie_Steuerbefehl": "set_ess_mode",
            },
            now_ts=100.0,
        )
    finally:
        psl._last_powerstation_sent.clear()
    assert payload["set_ess_charge_power_limit"] == 5.0  # house battery, not the pack's 0.0
    assert payload["set_ess_mode"] == 2.0
    assert payload["ess.ecoflow_delta_3.set_ess_charge_power_limit"] == 0.0
    assert payload["ess.ecoflow_delta_3.set_ess_mode"] == 1.0


def test_shared_quellenwahl_stays_flat() -> None:
    psl = _clear_powerstation_cache()
    psl._last_powerstation_sent["set_ess_source_select"] = 1.0
    try:
        payload = build_loxone_status_payload(
            loxone_sent={}, consumers=[], plant_io_index={}, now_ts=100.0
        )
    finally:
        psl._last_powerstation_sent.clear()
    assert payload["set_ess_source_select"] == 1.0


def test_two_powerstations_do_not_collide() -> None:
    psl = _clear_powerstation_cache()
    psl._last_powerstation_sent["ess.pack_a.set_ess_charge_power_limit"] = 1.5
    psl._last_powerstation_sent["ess.pack_b.set_ess_charge_power_limit"] = 0.0
    try:
        payload = build_loxone_status_payload(
            loxone_sent={}, consumers=[], plant_io_index={}, now_ts=100.0
        )
    finally:
        psl._last_powerstation_sent.clear()
    assert payload["ess.pack_a.set_ess_charge_power_limit"] == 1.5
    assert payload["ess.pack_b.set_ess_charge_power_limit"] == 0.0
    assert payload["set_ess_charge_power_limit"] == 0.0  # untouched plant default


def test_write_path_caches_pattern_b_key_not_flat_kind(monkeypatch) -> None:
    """End to end: ``_write_powerstation_loxone`` → status payload."""
    from unittest.mock import MagicMock

    psl = _clear_powerstation_cache()
    field = "ess.ecoflow_delta_3.set_ess_charge_power_limit"
    monkeypatch.setattr(
        psl, "_resolve_marker", lambda key: ("set_ess_charge_power_limit", "Earnie_Delta3_LadeLeistungs-Limit")
    )
    monkeypatch.setattr(
        "integrations.loxone_client._send_loxone_value_traced",
        lambda name, value: MagicMock(success=True),
    )
    try:
        psl._write_powerstation_loxone({field: 2000.0})  # W → 2.0 kW
        payload = build_loxone_status_payload(
            loxone_sent={"Earnie_LadeLeistungs-Limit": 5.0},
            consumers=[],
            plant_io_index={"Earnie_LadeLeistungs-Limit": "set_ess_charge_power_limit"},
            now_ts=100.0,
        )
    finally:
        psl._last_powerstation_sent.clear()
    assert payload[field] == 2.0
    assert payload["set_ess_charge_power_limit"] == 5.0
