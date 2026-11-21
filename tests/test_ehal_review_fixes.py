"""Fixes from the code review of ``ehal/`` (2026-11-21)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ehal.loxone_push_source import build_ehal_index
from ehal.push_signals import write_signals_from_docs
from ehal.signal_catalog import iter_catalog_entries, set_binding_activation
from ehal.signal_list import _read_match, _write_match, signals_for_export
from house_config.control_capability import (
    control_capability_warnings,
    inverter_control_capability_warnings,
)
from house_config.profiles_store import normalize_house_profiles_document

_WALLBOX = {
    "id": "garage",
    "min_current_a": 6,
    "max_current_a": 16,
    "voltage_v": 230,
    "phases": 3,
    "ehal_bindings": {"set_evcs_max_current": "", "sens_evcs_active_power": ""},
}


def _fixed_ev_docs() -> tuple[dict, dict]:
    """EV ``tesla`` at the fixed wallbox ``garage`` (loader view: wallbox bindings merged)."""
    ev = {
        "id": "tesla",
        "type": "ev",
        "charger_id": "garage",
        "wallbox_assignment": {"mode": "fixed", "wallbox_id": "garage"},
        "ehal_bindings": {
            "evcs.garage.set_evcs_max_current": "",
            "evcs.garage.sens_evcs_active_power": "",
            "sens_evcs_soc_act": "",
        },
    }
    house = {"plant": {"ehal_bindings": {}}, "profiles": {"live": {"consumers": [ev]}}}
    return house, {"wallboxes": [dict(_WALLBOX)]}


def _iso(delta_s: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat()


# --- Signal list: charger signals belong to the wallbox ---------------------------------


def test_catalog_lists_charger_signals_under_the_wallbox() -> None:
    house, components = _fixed_ev_docs()
    entries = {e.ehal_id: e for e in iter_catalog_entries(house, components)}

    assert not [i for i in entries if i.startswith("evcs.tesla.")]
    current = entries["evcs.garage.set_evcs_max_current"]
    assert (current.component_kind, current.entity_id) == ("wallbox", "garage")
    assert current.is_required and current.is_activated
    assert entries["evcs.garage.sens_evcs_active_power"].is_activated
    assert not entries["evcs.garage.sens_evcs_connected"].is_activated
    # The vehicle side stays with the EV.
    assert entries["ev.tesla.sens_evcs_soc_act"].is_activated


def test_export_matches_the_inbox_index_and_the_write_path() -> None:
    house, components = _fixed_ev_docs()
    reads, writes = signals_for_export(house, components, mode="needed")

    read_ids = {s.ehal_id for s in reads} - {"heartbeat_smarthome"}
    write_ids = {s.ehal_id for s in writes} - {"heartbeat_earnie"}
    assert read_ids == set(build_ehal_index(house, components))
    assert write_ids == {s.ehal_id for s in write_signals_from_docs(house, components)}


def test_wallbox_of_a_dynamic_ev_is_listed_with_required_plug_signal() -> None:
    ev = {
        "id": "tesla",
        "type": "ev",
        "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["garage"]},
    }
    house = {"plant": {}, "profiles": {"live": {"consumers": [ev]}}}
    entries = {e.ehal_id: e for e in iter_catalog_entries(house, {"wallboxes": [dict(_WALLBOX)]})}

    assert entries["evcs.garage.sens_evcs_connected"].is_required
    assert not [i for i in entries if i.startswith("evcs.tesla.")]


def test_unused_wallbox_is_not_listed() -> None:
    house = {"plant": {}, "profiles": {"live": {"consumers": []}}}
    entries = iter_catalog_entries(house, {"wallboxes": [dict(_WALLBOX)]})
    assert not [e for e in entries if e.component_kind == "wallbox"]


def test_wallbox_toggle_writes_the_wallbox_and_keeps_one_key_per_kind() -> None:
    house, components = _fixed_ev_docs()
    _h, on = set_binding_activation(
        house,
        components,
        component_kind="wallbox",
        entity_id="garage",
        binding_key="evcs.garage.sens_evcs_connected",
        activated=True,
    )
    assert on["wallboxes"][0]["ehal_bindings"]["evcs.garage.sens_evcs_connected"] == ""

    # Stored bare: the qualified toggle key finds it, adds no twin and removes it.
    _h, same = set_binding_activation(
        house,
        components,
        component_kind="wallbox",
        entity_id="garage",
        binding_key="evcs.garage.sens_evcs_active_power",
        activated=True,
    )
    assert same["wallboxes"][0]["ehal_bindings"] == _WALLBOX["ehal_bindings"]
    _h, off = set_binding_activation(
        house,
        components,
        component_kind="wallbox",
        entity_id="garage",
        binding_key="evcs.garage.sens_evcs_active_power",
        activated=False,
    )
    assert off["wallboxes"][0]["ehal_bindings"] == {"set_evcs_max_current": ""}


# --- Signal list: match status ----------------------------------------------------------


def test_write_published_after_the_last_fetch_awaits_the_hub() -> None:
    qid = "ess.b1.set_ess_charge_power_limit"
    published = {qid: {"published_at": _iso(-60)}}

    assert _write_match(qid, published, _iso(-3600))[0] == "awaiting_fetch"
    assert _write_match(qid, published, _iso(-5))[0] == "published"


def test_digital_read_is_not_stale_without_an_edge() -> None:
    ts = _iso(-8 * 3600)
    digital = "pool.spa.sens_heating_active"
    analog = "pool.spa.sens_temperature_water"

    assert _read_match(digital, {digital: {"last_ts": ts}})[0] == "ok"
    assert _read_match(analog, {analog: {"last_ts": ts}})[0] == "stale"


# --- Export: IDs the inbox would refuse -------------------------------------------------


def test_export_rejects_an_id_the_inbox_refuses() -> None:
    house = {"plant": {"ehal_bindings": {}}, "profiles": {}}
    components = {
        "batteries": [{"id": "BYD-1", "ehal_bindings": {"ess.BYD-1.sens_ess_soc": ""}}]
    }
    with pytest.raises(ValueError, match="BYD-1"):
        signals_for_export(house, components, mode="needed")


# --- Control capability: activation flags next to a kept hub address --------------------


def test_activation_flags_count_next_to_a_kept_address() -> None:
    battery = {
        "ess.b1.sens_ess_soc": "Batterie_SoC",
        "ess.b1.set_ess_charge_power_limit": "",
        "ess.b1.set_ess_discharge_power_limit": "",
    }
    assert control_capability_warnings(control="limits_only", ehal_map=battery) == []
    assert control_capability_warnings(control="full", ehal_map=battery) != []

    inverter = {"inv.wr.sens_inv_power_pv": "PV_Leistung", "inv.wr.set_inv_ac_power_limit": ""}
    assert inverter_control_capability_warnings(control="full", ehal_map=inverter) == []


# --- House profile: one EHAL Kennung for two consumers ----------------------------------


def _generic(consumer_id: str) -> dict:
    return {
        "id": consumer_id,
        "type": "generic",
        "nominal_power_kw": 2.0,
        "schedule": {"runs_per_week": 7, "duration_h": 1.0, "start_hour": 19, "start_shift_h": 0.0},
    }


def _profile_doc(*consumer_ids: str) -> dict:
    return {
        "profiles": [
            {
                "id": "p1",
                "annual_kwh": 1000,
                "netznutzung": {"area_id": "user_no_grid_fee"},
                "consumers": [_generic(cid) for cid in consumer_ids],
            }
        ]
    }


def test_zaehler_prefix_twin_is_rejected() -> None:
    with pytest.raises(ValueError, match="dieselbe EHAL-Kennung 'consumer.sauna'"):
        normalize_house_profiles_document(_profile_doc("zaehler_sauna", "sauna"))


def test_distinct_kennungen_load() -> None:
    doc = normalize_house_profiles_document(_profile_doc("zaehler_sauna", "kochen"))
    assert [c["id"] for c in doc["profiles"]["p1"]["consumers"]] == ["zaehler_sauna", "kochen"]


# --- Functions: fields of one device type sit on one entity -----------------------------


def test_limits_of_two_batteries_are_not_one_function() -> None:
    from ehal.functions import available_functions, function_statuses

    split = {"ess.a.set_ess_charge_power_limit": "x", "ess.b.set_ess_discharge_power_limit": "y"}
    assert "ess_limits" not in available_functions(split)
    status = {s.function.id: s for s in function_statuses(split)}["ess_limits"]
    assert status.state == "incomplete" and len(status.missing) == 1

    # A second battery without limits is no gap; flat keys count as before.
    both = {
        "ess.a.set_ess_charge_power_limit": "x",
        "ess.a.set_ess_discharge_power_limit": "y",
        "ess.b.sens_ess_soc": "z",
    }
    assert "ess_limits" in available_functions(both)
    flat = {"set_ess_charge_power_limit": "x", "set_ess_discharge_power_limit": "y"}
    assert "ess_limits" in available_functions(flat)


# --- Consumer bindings: an address is never replaced by an empty flag -------------------


def test_address_wins_over_an_empty_stub_in_either_order() -> None:
    from ehal.flex_fields import canonicalize_consumer_bindings

    expected = {"consumer.x.sens_power_act": "Merker_X"}
    stub_first = {"flex.power_name": "", "consumer.x.sens_power_act": "Merker_X"}
    stub_last = {"consumer.x.sens_power_act": "Merker_X", "flex.power_name": ""}
    assert canonicalize_consumer_bindings(stub_first, "x", "generic") == expected
    assert canonicalize_consumer_bindings(stub_last, "x", "generic") == expected
    # Two addresses: the first one stays.
    two = {"flex.power_name": "A", "consumer.x.sens_power_act": "B"}
    assert canonicalize_consumer_bindings(two, "x", "generic") == {"consumer.x.sens_power_act": "A"}


# --- Push binding index: a failed build is not kept as the answer -----------------------


def test_failed_index_build_keeps_the_last_good_index_and_retries(monkeypatch) -> None:
    import ehal.loxone_push_source as src

    house = {"plant": {"ehal_bindings": {"sens_grid_power_active": "Netz_kW"}}, "profiles": {}}
    state = {"fail": False, "mtime": (1.0, 1.0)}

    def _load() -> tuple[dict, dict]:
        if state["fail"]:
            raise ValueError("config not readable")
        return house, {}

    monkeypatch.setattr(src, "_load_house_components", _load)
    monkeypatch.setattr(src, "_house_components_mtime_key", lambda: state["mtime"])
    src.clear_source_caches()
    try:
        assert src.resolve_push_binding("Netz_kW") is not None

        # The file changes and does not load: the last good index answers.
        state.update(fail=True, mtime=(2.0, 1.0))
        assert src.resolve_push_binding("Netz_kW") is not None

        # No index yet and the build fails: empty, but the next read builds it.
        src.clear_source_caches()
        assert src.resolve_push_binding("Netz_kW") is None
        state["fail"] = False
        assert src.resolve_push_binding("Netz_kW") is not None
    finally:
        src.clear_source_caches()
