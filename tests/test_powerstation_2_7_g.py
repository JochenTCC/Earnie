"""2.7.g — advice XOR reserve, powerstation model, virtual carve-out."""
from __future__ import annotations

import pytest

from house_config.entity_resolution import (
    normalize_battery,
    resolve_battery_into_settings,
)
from house_config.powerstation import (
    MODE_ADVICE,
    MODE_RESERVE,
    consumer_assist_mode,
    is_powerstation,
    scenario_selectable_batteries,
)
from optimizer.powerstation_reserve import (
    apply_virtual_reserve_floor,
    learn_energy_from_series,
    protected_kwh_from_state,
    reserve_target_kwh,
)
from settings.appliances import (
    advice_appliances_from_profile,
    normalize_appliance_recommendation_block,
    recommendation_appliances_from_profile,
    reserve_appliances_from_profile,
)


def test_assist_mode_defaults_to_advice():
    assert consumer_assist_mode({}) == MODE_ADVICE
    assert consumer_assist_mode({"appliance_recommendation": {}}) == MODE_ADVICE


def test_normalize_recommendation_mode_advice_default():
    out = normalize_appliance_recommendation_block(
        {"power_source": "manual", "default_power_kw": 1.0, "default_runtime_h": 2.0},
        consumer_id="wm",
        nominal_power_kw=1.0,
    )
    assert out["mode"] == MODE_ADVICE
    assert "powerstation_id" not in out


def test_normalize_recommendation_reserve_requires_powerstation_id():
    with pytest.raises(ValueError, match="powerstation_id"):
        normalize_appliance_recommendation_block(
            {
                "mode": "reserve",
                "power_source": "manual",
                "default_power_kw": 1.0,
                "default_runtime_h": 2.0,
            },
            consumer_id="wm",
            nominal_power_kw=1.0,
        )


def test_normalize_recommendation_reserve_ok():
    out = normalize_appliance_recommendation_block(
        {
            "mode": "reserve",
            "powerstation_id": "ps_wm",
            "power_source": "manual",
            "default_power_kw": 1.0,
            "default_runtime_h": 2.0,
        },
        consumer_id="wm",
        nominal_power_kw=1.0,
    )
    assert out["mode"] == MODE_RESERVE
    assert out["powerstation_id"] == "ps_wm"


def _house_battery(**overrides):
    base = {
        "id": "home",
        "label": "Home",
        "battery_capacity_kwh": 10.0,
        "battery_max_charge_power_kw": 5.0,
        "battery_max_discharge_power_kw": 5.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "battery_wear": {"enabled": False},
    }
    base.update(overrides)
    return base


def _powerstation(**overrides):
    base = {
        "id": "ps_wm",
        "label": "PS WM",
        "type": "powerstation",
        "backing": "virtual",
        "role": "single_use",
        "attached_consumer_id": "wm",
        "battery_capacity_kwh": 2.0,
        "battery_max_charge_power_kw": 1.2,
        "battery_max_discharge_power_kw": 0.0,
        "battery_efficiency": 0.88,
        "battery_min_soc": 0.0,
        "battery_max_soc": 100.0,
        "battery_wear": {"enabled": False},
        "control": "limits_only",
    }
    base.update(overrides)
    return base


def test_normalize_powerstation_allows_zero_discharge():
    bat = normalize_battery(_powerstation(), 0)
    assert is_powerstation(bat)
    assert bat["backing"] == "virtual"
    assert bat["battery_max_discharge_power_kw"] == 0.0


def test_virtual_ps_inherits_from_primary_house():
    from house_config.powerstation import apply_virtual_powerstation_inheritance

    house = _house_battery(
        battery_max_charge_power_kw=4.0,
        battery_efficiency=0.91,
        battery_min_soc=12.0,
        battery_max_soc=98.0,
        threshold_power=0.08,
    )
    raw = _powerstation(
        battery_max_charge_power_kw=9.0,
        battery_efficiency=0.5,
        battery_min_soc=50.0,
        battery_wear={"enabled": True, "replacement_cost_euro": 1.0},
        control="full",
    )
    out = apply_virtual_powerstation_inheritance(raw, [house, raw])
    assert out["battery_max_charge_power_kw"] == 4.0
    assert out["battery_max_discharge_power_kw"] == 0.0
    assert out["battery_efficiency"] == 0.91
    assert out["battery_min_soc"] == 12.0
    assert out["battery_max_soc"] == 98.0
    assert out["threshold_power"] == 0.08
    assert out["standby_power_kw"] == 0.0
    assert out["limits_from_live"] is False
    assert out["control"] == "limits_only"
    assert out["battery_wear"] == {"enabled": False}


def test_virtual_ps_defaults_without_house():
    from house_config.powerstation import apply_virtual_powerstation_inheritance

    raw = _powerstation(battery_capacity_kwh=2.0, battery_efficiency=0.5)
    out = apply_virtual_powerstation_inheritance(raw, [raw])
    assert out["battery_max_charge_power_kw"] == 1.0
    assert out["battery_efficiency"] == 0.95
    assert out["battery_min_soc"] == 0.0
    assert out["battery_max_soc"] == 100.0


def test_physical_ps_not_inherited():
    from house_config.powerstation import apply_virtual_powerstation_inheritance

    house = _house_battery(battery_efficiency=0.91)
    raw = _powerstation(backing="physical", battery_efficiency=0.88)
    out = apply_virtual_powerstation_inheritance(raw, [house, raw])
    assert out["battery_efficiency"] == 0.88


def test_normalize_components_inherits_virtual_ps():
    from house_config.components_store import normalize_components_document

    doc = normalize_components_document(
        {
            "batteries": [
                _house_battery(battery_efficiency=0.93, battery_max_charge_power_kw=3.5),
                _powerstation(battery_efficiency=0.5, battery_max_charge_power_kw=9.0),
            ],
            "pv_systems": [],
        }
    )
    ps = next(b for b in doc["batteries"] if b["id"] == "ps_wm")
    assert ps["battery_efficiency"] == 0.93
    assert ps["battery_max_charge_power_kw"] == 3.5
    assert ps["battery_max_discharge_power_kw"] == 0.0
    assert ps["control"] == "limits_only"


def test_normalize_powerstation_allows_empty_attached_consumer():
    bat = normalize_battery(
        _powerstation(attached_consumer_id=""),
        0,
    )
    assert is_powerstation(bat)
    assert bat["attached_consumer_id"] == ""
    assert bat["attached_consumer_ids"] == []


def test_normalize_powerstation_attached_consumer_ids_list():
    bat = normalize_battery(
        _powerstation(
            attached_consumer_id="wm",
            attached_consumer_ids=["dryer", "wm"],
        ),
        0,
    )
    assert bat["attached_consumer_ids"] == ["dryer", "wm"]
    assert bat["attached_consumer_id"] == "dryer"


def test_normalize_physical_powerstation_keeps_one_attached():
    bat = normalize_battery(
        _powerstation(
            backing="physical",
            attached_consumer_ids=["wm", "dryer"],
        ),
        0,
    )
    assert bat["attached_consumer_ids"] == ["wm"]
    assert bat["attached_consumer_id"] == "wm"


def test_reserve_links_from_consumers():
    from house_config.powerstation import reserve_links_from_consumers

    links = reserve_links_from_consumers(
        [
            {
                "id": "wm",
                "appliance_recommendation": {
                    "mode": "reserve",
                    "powerstation_id": "ps_wm",
                },
            },
            {
                "id": "dryer",
                "appliance_recommendation": {
                    "mode": "reserve",
                    "powerstation_id": "ps_wm",
                },
            },
            {
                "id": "other",
                "appliance_recommendation": {"mode": "advice"},
            },
        ]
    )
    assert links == {"ps_wm": ["wm", "dryer"]}


def test_collect_active_reserves_shares_virtual_pool(monkeypatch, tmp_path):
    from optimizer import powerstation_reserve as ps_reserve
    from runtime_store import powerstation_reserves as ps_store

    monkeypatch.setattr(ps_store, "_path", lambda: str(tmp_path / "reserves.json"))
    appliances = [
        {
            "id": "wm",
            "mode": "reserve",
            "powerstation_id": "ps_wm",
            "default_power_kw": 1.0,
            "default_runtime_h": 2.0,
        },
        {
            "id": "dryer",
            "mode": "reserve",
            "powerstation_id": "ps_wm",
            "default_power_kw": 1.5,
            "default_runtime_h": 1.0,
        },
    ]
    powerstations = [normalize_battery(_powerstation(battery_capacity_kwh=10.0), 0)]
    active = ps_reserve.collect_active_reserves(
        appliances=appliances,
        powerstations=powerstations,
    )
    assert len(active) == 1
    assert active[0]["appliance_ids"] == ["wm", "dryer"]
    assert active[0]["target_kwh"] == 3.5  # 2.0 + 1.5


def test_scenario_selectable_batteries_excludes_virtual_and_physical_ps():
    """Regression: Scenario-Config must not offer powerstations as battery picks."""
    items = [
        _house_battery(id="home", label="Home"),
        _powerstation(id="ps_v", label="Virtual PS", backing="virtual"),
        _powerstation(id="ps_p", label="Physical PS", backing="physical"),
        {"label": "orphan without id"},
    ]
    selectable = scenario_selectable_batteries(items)
    assert [b["id"] for b in selectable] == ["home"]


def test_resolve_skips_powerstation_in_battery_ids():
    batteries = {
        "home": normalize_battery(_house_battery(), 0),
        "ps_wm": normalize_battery(_powerstation(), 1),
    }
    resolved = resolve_battery_into_settings(
        {"battery_ids": ["home", "ps_wm"]},
        batteries,
    )
    assert [b["id"] for b in resolved["_planning_batteries"]] == ["home"]
    assert len(resolved["_planning_powerstations"]) == 1


def test_resolve_powerstation_only_battery_ids_yields_empty_house_fleet():
    batteries = {
        "ps_wm": normalize_battery(_powerstation(), 0),
    }
    resolved = resolve_battery_into_settings({"battery_ids": ["ps_wm"]}, batteries)
    assert resolved["_planning_batteries"] == []
    assert resolved["battery_capacity_kwh"] == 0.0


def test_resolve_lists_powerstations_separately():
    batteries = {
        "home": normalize_battery(_house_battery(), 0),
        "ps_wm": normalize_battery(_powerstation(), 1),
    }
    resolved = resolve_battery_into_settings({"battery_ids": ["home"]}, batteries)
    assert len(resolved["_planning_batteries"]) == 1
    assert resolved["_planning_batteries"][0]["id"] == "home"
    assert len(resolved["_planning_powerstations"]) == 1
    assert resolved["_planning_powerstations"][0]["id"] == "ps_wm"


def test_advice_vs_reserve_appliance_split():
    profile = {
        "consumers": [
            {
                "id": "wm",
                "label": "WM",
                "type": "generic",
                "earnie_role": "manual",
                "nominal_power_kw": 1.8,
                "schedule": {
                    "runs_per_week": 2,
                    "duration_h": 1.0,
                    "start_hour": 8,
                    "start_shift_h": 6,
                },
                "appliance_recommendation": {
                    "mode": "advice",
                    "power_source": "manual",
                    "default_power_kw": 1.8,
                    "default_runtime_h": 1.0,
                },
            },
            {
                "id": "dryer",
                "label": "Dryer",
                "type": "generic",
                "earnie_role": "manual",
                "nominal_power_kw": 2.0,
                "schedule": {
                    "runs_per_week": 2,
                    "duration_h": 1.0,
                    "start_hour": 10,
                    "start_shift_h": 6,
                },
                "appliance_recommendation": {
                    "mode": "reserve",
                    "powerstation_id": "ps_dryer",
                    "power_source": "manual",
                    "default_power_kw": 2.0,
                    "default_runtime_h": 1.0,
                },
            },
        ]
    }
    all_apps = recommendation_appliances_from_profile(profile)
    advice = advice_appliances_from_profile(profile)
    reserve = reserve_appliances_from_profile(profile)
    assert len(all_apps) == 2
    assert [a["id"] for a in advice] == ["wm"]
    assert [a["id"] for a in reserve] == ["dryer"]
    assert advice[0]["mode"] == MODE_ADVICE
    assert reserve[0]["mode"] == MODE_RESERVE


def test_virtual_floor_raises_min_soc():
    params = {
        "id": "home",
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
    }
    out = apply_virtual_reserve_floor(params, protected_kwh=2.0, asap_charge_kwh=1.0)
    # 10% of 10 kWh = 1 kWh base; +2 → 3 kWh → 30%
    assert out["min_soc"] == pytest.approx(30.0)
    assert out["_virtual_reserve_asap_kwh"] == pytest.approx(1.0)


def test_protected_kwh_standby_vs_discharging():
    assert protected_kwh_from_state(
        {"state": "standby", "stored_kwh": 2.0, "target_kwh": 2.0}
    ) == pytest.approx(2.0)
    assert (
        protected_kwh_from_state(
            {"state": "discharging", "stored_kwh": 2.0, "target_kwh": 2.0}
        )
        == 0.0
    )


def test_reserve_target_and_learning():
    assert reserve_target_kwh(default_power_kw=2.0, default_runtime_h=1.5) == pytest.approx(
        3.0
    )
    assert reserve_target_kwh(
        default_power_kw=2.0, default_runtime_h=1.5, learned_kwh=2.2
    ) == pytest.approx(2.2)
    learned = learn_energy_from_series([0.0, 1.0, 1.0, 0.0], dt_h=0.25)
    assert learned == pytest.approx(0.5)


def test_physical_excluded_from_export_unconstrained(monkeypatch):
    import config
    from optimizer.live_export_limit import live_unconstrained_export_kw

    monkeypatch.setattr(
        config,
        "get_battery_params_list",
        lambda: [
            {
                "id": "home",
                "control": "full",
                "type": "house",
                "max_discharge_power_kw": 5.0,
            },
            {
                "id": "ps",
                "control": "full",
                "type": "powerstation",
                "backing": "physical",
                "max_discharge_power_kw": 0.8,
            },
        ],
    )
    monkeypatch.setattr(
        config,
        "get",
        lambda name, default=None, cast=None: 9.8 if name == "PV_KWP" else default,
    )
    assert live_unconstrained_export_kw() == pytest.approx(14.8)


def _minimal_powerstation(battery_id: str = "ps1", *, attached: list[str]) -> dict:
    return {
        "id": battery_id,
        "label": battery_id,
        "type": "powerstation",
        "backing": "virtual",
        "role": "single_use",
        "battery_capacity_kwh": 1.0,
        "battery_max_charge_power_kw": 1.0,
        "battery_max_discharge_power_kw": 0.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": 0.0,
        "battery_max_soc": 100.0,
        "threshold_power": 0.05,
        "attached_consumer_ids": list(attached),
        "attached_consumer_id": attached[0] if attached else "",
    }


def test_sync_consumers_from_powerstation_attached_detach(monkeypatch, tmp_path):
    """Battery detach must clear consumer powerstation_id (no silent restore)."""
    import json

    from house_config.components_store import save_components_document
    from house_config.profiles_store import save_house_profiles_document
    from ui import house_config_entities_io as entities_io
    from ui import house_config_io as hc_io

    components = tmp_path / "components.json"
    profiles = tmp_path / "house_profiles.json"
    save_components_document(
        str(components),
        {"batteries": [_minimal_powerstation(attached=["wm"])], "pv_systems": []},
    )
    save_house_profiles_document(
        str(profiles),
        {
            "profiles": [
                {
                    "id": "home",
                    "label": "Home",
                    "annual_consumption_kwh": 1000.0,
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
                                "mode": "reserve",
                                "power_source": "manual",
                                "default_power_kw": 1.0,
                                "default_runtime_h": 1.0,
                                "powerstation_id": "ps1",
                            },
                        }
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(
        entities_io, "resolve_components_json_path", lambda: str(components)
    )
    monkeypatch.setattr(entities_io.config, "reinit_config", lambda: None)
    monkeypatch.setattr(hc_io, "resolve_house_profiles_json_path", lambda: str(profiles))
    entities_io.sync_consumers_from_powerstation_attached("ps1", [])
    saved = json.loads(profiles.read_text(encoding="utf-8"))
    rec = saved["profiles"][0]["consumers"][0]["appliance_recommendation"]
    assert rec["mode"] == MODE_ADVICE
    assert "powerstation_id" not in rec


def test_sync_from_consumers_clears_powerstation_without_links(
    monkeypatch, tmp_path
):
    from house_config.components_store import (
        load_components_document,
        save_components_document,
    )
    from ui import house_config_entities_io as entities_io

    components = tmp_path / "components.json"
    save_components_document(
        str(components),
        {"batteries": [_minimal_powerstation(attached=["wm"])], "pv_systems": []},
    )
    monkeypatch.setattr(
        entities_io, "resolve_components_json_path", lambda: str(components)
    )
    monkeypatch.setattr(entities_io.config, "reinit_config", lambda: None)
    entities_io.sync_powerstation_attached_from_consumers(
        [{"id": "wm", "appliance_recommendation": {"mode": "advice"}}]
    )
    bat = load_components_document(str(components))["batteries"][0]
    assert bat["attached_consumer_ids"] == []
    assert bat["attached_consumer_id"] == ""
