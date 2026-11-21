"""Writers that touch components.json and backtesting_scenarios.json in one action.

A reinit between the two writes resolves the Live scenario against the stale file
and fails (review ui slice 2, finding 2a-1); a powerstation rename must move the
consumer links along (2a-6).
"""
from __future__ import annotations

import json

import pytest

from tests.test_entity_id_lock import components_env  # noqa: F401 — fixture
from ui.house_config_entities_io import (
    delete_battery,
    delete_pv_system,
    upsert_battery,
    upsert_pv_system,
)


def _consistency_reinit(env, calls: list):
    """Stand-in for ``config.reinit_config``: fails like the real one on a scenario id
    that components.json does not hold (both files read from disk)."""

    def _reinit() -> None:
        comp = json.loads(env["components"].read_text(encoding="utf-8"))
        scen = json.loads(env["scenarios"].read_text(encoding="utf-8"))
        pv_ids = {p["id"] for p in comp.get("pv_systems") or []}
        bat_ids = {b["id"] for b in comp.get("batteries") or []}
        for item in scen["scenarios"]:
            settings = item.get("settings") or {}
            missing = (set(settings.get("pv_system_ids") or []) - pv_ids) | (
                set(settings.get("battery_ids") or []) - bat_ids
            )
            if missing:
                raise ValueError(f"Unbekannte IDs: {sorted(missing)}")
        calls.append(1)

    return _reinit


def _use_consistency_reinit(env, monkeypatch) -> list:
    import config as cfg_mod

    calls: list = []
    monkeypatch.setattr(cfg_mod, "reinit_config", _consistency_reinit(env, calls))
    return calls


def _set_live_ids(key: str, ids: list[str]) -> None:
    from ui import house_config_io as io

    scen = io.load_backtesting_scenarios_raw()
    scen["scenarios"][0]["settings"][key] = ids
    io.save_backtesting_scenarios(scen)


def _live_settings() -> dict:
    from ui import house_config_io as io

    return io.load_backtesting_scenarios_raw()["scenarios"][0]["settings"]


def _pv_spec(label: str, **extra) -> dict:
    return {
        "label": label,
        "kwp": 8.0,
        "pv_tilt": 20.0,
        "pv_azimuth": 0.0,
        "inverter_id": "wr_main",
        **extra,
    }


def _house_battery_spec(label: str, **extra) -> dict:
    return {
        "label": label,
        "battery_capacity_kwh": 10.0,
        "battery_max_charge_power_kw": 5.0,
        "battery_max_discharge_power_kw": 5.0,
        "battery_efficiency": 0.97,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "inverter_id": "wr_main",
        "regulates_on": "grid",
        "battery_wear": {"enabled": False},
        **extra,
    }


def test_pv_rename_in_live_scenario_reinits_once(components_env, monkeypatch):
    old_id = upsert_pv_system(
        _pv_spec("Dach copy", id_provisional_label="Dach copy"), stable_id=""
    )
    _set_live_ids("pv_system_ids", [old_id])
    calls = _use_consistency_reinit(components_env, monkeypatch)
    new_id = upsert_pv_system(_pv_spec("Dach Ost"), stable_id=old_id)
    assert new_id == "dach_ost"
    assert calls == [1]
    assert _live_settings()["pv_system_ids"] == ["dach_ost"]


def test_pv_delete_in_live_scenario_reinits_once(components_env, monkeypatch):
    from house_config.components_store import load_components_document

    pv_id = upsert_pv_system(_pv_spec("Dach"), stable_id="")
    _set_live_ids("pv_system_ids", [pv_id])
    calls = _use_consistency_reinit(components_env, monkeypatch)
    delete_pv_system(pv_id)
    assert calls == [1]
    assert load_components_document(str(components_env["components"]))["pv_systems"] == []
    assert "pv_system_ids" not in _live_settings()


def test_battery_rename_in_live_scenario_reinits_once(components_env, monkeypatch):
    old_id = upsert_battery(
        _house_battery_spec("Speicher copy", id_provisional_label="Speicher copy"),
        stable_id="",
    )
    _set_live_ids("battery_ids", [old_id])
    calls = _use_consistency_reinit(components_env, monkeypatch)
    new_id = upsert_battery(_house_battery_spec("Keller"), stable_id=old_id)
    assert new_id == "keller"
    assert calls == [1]
    assert _live_settings()["battery_ids"] == ["keller"]


def test_battery_delete_in_live_scenario_reinits_once(components_env, monkeypatch):
    bat_id = upsert_battery(_house_battery_spec("Keller"), stable_id="")
    _set_live_ids("battery_ids", [bat_id])
    calls = _use_consistency_reinit(components_env, monkeypatch)
    delete_battery(bat_id)
    assert calls == [1]
    assert _live_settings()["battery_ids"] == []


def test_refused_battery_delete_leaves_scenarios_untouched(components_env):
    before = components_env["scenarios"].read_bytes()
    with pytest.raises(ValueError, match="Unbekannte Batterie"):
        delete_battery("gibt_es_nicht")
    assert components_env["scenarios"].read_bytes() == before


def test_deferred_reinit_runs_once_and_also_after_a_failure(monkeypatch):
    import config as cfg_mod
    from ui import house_config_io as io

    calls: list = []
    monkeypatch.setattr(cfg_mod, "reinit_config", lambda: calls.append(1))
    with io.deferred_reinit():
        io.reinit_after_write()
        with io.deferred_reinit():
            io.reinit_after_write()
        assert calls == []
    assert calls == [1]
    with pytest.raises(RuntimeError, match="boom"):
        with io.deferred_reinit():
            io.reinit_after_write()
            raise RuntimeError("boom")
    assert calls == [1, 1]
    with pytest.raises(RuntimeError, match="nothing written"):
        with io.deferred_reinit():
            raise RuntimeError("nothing written")
    assert calls == [1, 1]
    io.reinit_after_write()
    assert calls == [1, 1, 1]


def test_powerstation_rename_moves_consumer_link(components_env, monkeypatch):
    from house_config.profiles_store import (
        load_house_profiles_document,
        save_house_profiles_document,
    )
    from tests.config_fixtures import copy_fixture_grid_fees

    cfg = components_env["components"].parent
    copy_fixture_grid_fees(cfg)
    profiles = cfg / "house_profiles.json"
    monkeypatch.setenv("EARNIE_HOUSE_PROFILES_PATH", str(profiles))
    save_house_profiles_document(
        str(profiles),
        {
            "profiles": [
                {
                    "id": "home",
                    "label": "Home",
                    "annual_consumption_kwh": 1000.0,
                    "netznutzung": {"area_id": "user_no_grid_fee"},
                    "consumers": [
                        {
                            "id": "wm",
                            "label": "WM",
                            "type": "generic",
                            "earnie_role": "manual",
                            "nominal_power_kw": 1.0,
                            "schedule": {
                                "runs_per_week": 1,
                                "duration_h": 1.0,
                                "start_hour": 8,
                                "start_shift_h": 0.0,
                            },
                            "appliance_recommendation": {
                                "mode": "advice",
                                "power_source": "manual",
                                "default_power_kw": 1.0,
                                "default_runtime_h": 1.0,
                            },
                        }
                    ],
                }
            ]
        },
    )
    ps_spec = {
        "label": "PS copy",
        "id_provisional_label": "PS copy",
        "type": "powerstation",
        "backing": "virtual",
        "role": "single_use",
        "battery_capacity_kwh": 1.0,
        "battery_max_charge_power_kw": 1.0,
        "battery_max_discharge_power_kw": 0.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": 0.0,
        "battery_max_soc": 100.0,
        "attached_consumer_ids": ["wm"],
    }

    def _rec() -> dict:
        doc = load_house_profiles_document(str(profiles))
        return doc["profiles"]["home"]["consumers"][0]["appliance_recommendation"]

    # A virtual Powerstation needs a house battery as carve-out base (refused otherwise).
    upsert_battery(_house_battery_spec("Keller"), stable_id="")
    old_id = upsert_battery(ps_spec, stable_id="")
    assert _rec()["powerstation_id"] == old_id

    new_id = upsert_battery({**ps_spec, "label": "Garage PS"}, stable_id=old_id)
    assert new_id == "garage_ps"
    assert _rec()["mode"] == "reserve"
    assert _rec()["powerstation_id"] == "garage_ps"
