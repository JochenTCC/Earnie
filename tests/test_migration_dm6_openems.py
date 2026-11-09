"""dm6.wallboxes, multi-EV M2: the OpenEMS EVCS component moves onto the wallbox."""
from __future__ import annotations

import copy

from runtime_store.migration.steps.wallboxes import apply, detect


def _ev(ev_id: str) -> dict:
    return {
        "id": ev_id,
        "label": ev_id,
        "type": "ev",
        "nominal_power_kw": 11.04,
        "min_power_kw": 4.14,
        "charging_schedule": {"nominal_power_voltage_v": 230.0, "nominal_power_phases": 3},
        "ehal_bindings": {"set_evcs_max_current": ""},
    }


def _docs(*, evs: list[dict], openems: dict | None, backend: str = "openems", model: int = 5):
    ehal: dict = {"backend": backend}
    if openems is not None:
        ehal["openems"] = openems
    return {
        "config.json": {"earnie_data_model": model, "ehal": ehal},
        "components.json": {"earnie_data_model": model, "wallboxes": []},
        "house_profiles.json": {
            "earnie_data_model": model,
            "profiles": [{"id": "home", "consumers": evs}],
        },
    }


def _wallbox(result, wallbox_id: str) -> dict:
    return next(
        w for w in result.docs["components.json"]["wallboxes"] if w["id"] == wallbox_id
    )


def test_explicit_component_moves_onto_the_one_wallbox():
    docs = _docs(evs=[_ev("e_auto")], openems={"base_url": "x", "evcs_component": "evcs3"})
    result = apply(docs, {})
    assert not result.blockers
    assert _wallbox(result, "e_auto")["ehal_bindings"]["set_evcs_max_current"] == (
        "evcs3/SetChargePowerLimit"
    )
    assert "evcs_component" not in result.docs["config.json"]["ehal"]["openems"]


def test_old_default_evcs0_is_kept_when_the_key_was_not_set():
    """Before data model 6 OpenEMS used ``evcs0`` without the key: the pack keeps it."""
    result = apply(_docs(evs=[_ev("e_auto")], openems={"base_url": "x"}), {})
    assert _wallbox(result, "e_auto")["ehal_bindings"]["set_evcs_max_current"] == (
        "evcs0/SetChargePowerLimit"
    )


def test_two_wallboxes_stop_the_step():
    docs = _docs(evs=[_ev("auto_a"), _ev("auto_b")], openems={"evcs_component": "evcs0"})
    result = apply(docs, {})
    assert result.blockers
    assert "2 Wallboxen" in result.blockers[0].message_de


def test_other_backends_only_drop_the_key():
    docs = _docs(evs=[_ev("e_auto")], openems={"evcs_component": "evcs3"}, backend="ha")
    result = apply(docs, {})
    assert not result.blockers
    assert _wallbox(result, "e_auto")["ehal_bindings"]["set_evcs_max_current"] == ""
    assert "evcs_component" not in result.docs["config.json"]["ehal"]["openems"]


def test_a_migrated_pack_with_the_key_left_is_detected_again():
    """A pack already on model 6 that still carries the key (migrated before M2)."""
    migrated = apply(_docs(evs=[_ev("e_auto")], openems={"base_url": "x"}, backend="ha"), {})
    docs = copy.deepcopy(migrated.docs)
    assert not detect(docs)
    docs["config.json"]["ehal"]["backend"] = "openems"
    docs["config.json"]["ehal"]["openems"]["evcs_component"] = "evcs1"
    assert detect(docs)
    result = apply(docs, {})
    assert _wallbox(result, "e_auto")["ehal_bindings"]["set_evcs_max_current"] == (
        "evcs1/SetChargePowerLimit"
    )
    assert not detect(result.docs)


def test_config_loader_rejects_the_old_key_with_a_migration_hint():
    import pytest

    from settings.config_loaders import load_ehal_params

    raw = {"ehal": {"backend": "openems", "openems": {"evcs_component": "evcs0"}}}
    with pytest.raises(ValueError, match="Konfigurations-Migration"):
        load_ehal_params(raw)
