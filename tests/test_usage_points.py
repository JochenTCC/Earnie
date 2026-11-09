"""Live-plant Earnie-Points resolution + usage-ping state (docs/workflow/earnie-points.md §4)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from house_config.components_store import clear_components_doc_cache
from runtime_store import usage_ping as up
from runtime_store import usage_points as pts
from tests.fixtures.ev_wallbox import ev_fields, wallbox_entry

# 16 A × 230 V × 3 phases ≈ 11 kW
_WALLBOX = wallbox_entry("wallbox", max_current_a=16.0, phases=3)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    # mtime granularity on some filesystems: force a distinct stamp per rewrite
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def _components() -> dict:
    wr = {"inverter_id": "wr_main"}
    return {
        "inverters": [
            {
                "id": "wr_main",
                "label": "Wechselrichter",
                "type": "hybrid",
                "ac_connection": "grid_tied",
                "control": "full",
                "efficiency": 0.97,
            }
        ],
        "pv_systems": [
            {"id": "pv_main", "label": "Dach", "kwp": 8.0, "tilt": 30, "azimuth": 0, **wr},
            {"id": "pv_alt", "label": "Alternative", "kwp": 20.0, "tilt": 30, "azimuth": 0, **wr},
        ],
        "wallboxes": [_WALLBOX],
        "batteries": [
            {
                "id": "bat_main",
                "label": "Speicher",
                "battery_capacity_kwh": 9.0,
                "regulates_on": "grid",
                **wr,
            },
            {
                "id": "bat_alt",
                "label": "Alternative",
                "battery_capacity_kwh": 30.0,
                "regulates_on": "grid",
                **wr,
            },
        ],
    }


def _profiles(bidirectional: bool = False) -> dict:
    return {
        "profiles": [
            {
                "id": "home",
                "label": "Haus",
                "annual_kwh": 4000,
                "latitude": 48.0,
                "longitude": 14.0,
                "netznutzung": {"area_id": "user_no_grid_fee"},
                "consumers": [
                    {
                        "id": "wallbox",
                        "label": "Wallbox",
                        "type": "ev",
                        **ev_fields("wallbox", max_current_a=16.0),
                        "battery_capacity_kwh": 60.0,
                        "bidirectional": bidirectional,
                        "charging_schedule": {
                            "weekday": {
                                "car_available_from_hour": 18,
                                "ready_by_hour": 7,
                                "daily_rest_soc": 40.0,
                            },
                        },
                    }
                ],
            }
        ]
    }


def _scenarios(**settings: Any) -> dict:
    base = {
        "pv_system_ids": ["pv_main"],
        "battery_ids": ["bat_main"],
        "house_profile_id": "home",
    }
    base.update(settings)
    return {"scenarios": [{"id": "live", "settings": base}]}


@pytest.fixture
def plant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env = tmp_path / "earnie_env"
    runtime = env / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    for name in (
        "EARNIE_CONFIG_PATH",
        "EARNIE_COMPONENTS_PATH",
        "EARNIE_HOUSE_PROFILES_PATH",
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        "EARNIE_USAGE_PING",
        "EARNIE_SHADOW",
    ):
        monkeypatch.delenv(name, raising=False)
    # Pin both roots so xdist cannot fall through to the developer's earnie_env
    # (consent=on there makes test_refresh_requires_consent flake).
    monkeypatch.setenv("EARNIE_ENV_PATH", str(env))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(runtime))
    cfg = env / "config"
    _write(cfg / "config.json", {"live_scenario_id": "live"})
    _write(cfg / "components.json", _components())
    _write(cfg / "house_profiles.json", _profiles())
    _write(cfg / "backtesting_scenarios.json", _scenarios())
    clear_components_doc_cache()
    # Avoid set_consent → refresh_points POSTing to the live HTTPS SERVER_BASE.
    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: False)
    up.reset_send_in_flight_for_tests()
    return cfg


@pytest.fixture
def spawns(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: calls.append(1) or True)
    return calls


def test_compute_live_points_uses_live_scenario_selection_only(plant: Path) -> None:
    result = pts.compute_live_points()
    # pv_main 8 kWp -> 1 (8/7), bat_main 9 kWh -> 2 (8/5 + 1/2.5), wallbox -> 2;
    # alternatives ignored.
    assert result == {
        "total": 5, "pv": 1, "storage": 2, "wallbox": 2, "heat": 0, "heating_rod": 0, "other": 0
    }


def test_powerstations_are_always_counted(plant: Path) -> None:
    doc = _components()
    doc["batteries"].append(
        {
            "id": "ps",
            "label": "Powerstation",
            "type": "powerstation",
            "backing": "virtual",
            "battery_capacity_kwh": 2.0,
        }
    )
    _write(plant / "components.json", doc)
    clear_components_doc_cache()
    assert pts.compute_live_points()["storage"] == 3  # 11 kWh: 8/5 + 3/2.5 = 2.8


def test_unknown_pv_reference_raises(plant: Path) -> None:
    _write(plant / "backtesting_scenarios.json", _scenarios(pv_system_ids=["gone"]))
    with pytest.raises(ValueError, match="unbekannte pv_systems: gone"):
        pts.compute_live_points()


def test_unknown_profile_raises_without_first_profile_fallback(plant: Path) -> None:
    _write(plant / "backtesting_scenarios.json", _scenarios(house_profile_id="other"))
    with pytest.raises(ValueError, match="unbekanntes house_profile_id 'other'"):
        pts.compute_live_points()


def test_refresh_requires_consent(plant: Path, spawns: list[int]) -> None:
    assert pts.refresh_points() is False
    assert "points" not in up.load_state()
    assert spawns == []


def test_set_consent_on_refreshes_points_without_live_cycle(
    plant: Path, spawns: list[int]
) -> None:
    """Opt-in computes Earnie-Points from config; no optimiser cycle required."""
    state = up.set_consent("on")
    assert state["points"] == 5
    assert state["points_v"] == 2
    assert state["stage"] == "explorer"
    assert state["points_stamp"] == pts.config_stamp()
    assert spawns == [1]
    # Wire schema stays v1 until stage is live.
    assert up.build_payload(state)["v"] == 1
    assert "points" not in up.build_payload(state)


def test_set_consent_on_with_live_stage_yields_payload_v2(
    plant: Path, spawns: list[int]
) -> None:
    up.save_state({"consent": "unset", "stage": "live"})
    state = up.set_consent("on")
    assert state["stage"] == "live"
    assert state["points"] == 5
    payload = up.build_payload(state)
    assert payload["v"] == 2
    assert payload["points"] == 5
    assert spawns == [1]


def test_refresh_stores_points_and_triggers_resend(plant: Path, spawns: list[int]) -> None:
    # Manual consent so the first refresh is under test (set_consent also refreshes).
    up.save_state(
        {
            "consent": "on",
            "install_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "stage": "explorer",
            "consent_at": "2026-10-16",
            "last_sent_date": "2026-10-16",
            "last_attempt_at": "2026-10-16T10:00:00+00:00",
        }
    )

    assert pts.refresh_points() is True
    state = up.load_state()
    assert state["points"] == 5
    assert state["points_v"] == 2
    assert state["points_stamp"] == pts.config_stamp()
    assert "last_sent_date" not in state
    assert "last_attempt_at" not in state
    assert spawns == [1]


def test_refresh_skips_when_stamp_unchanged(
    plant: Path, spawns: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    up.set_consent("on")
    assert spawns == [1]

    def _boom() -> dict:
        raise AssertionError("must not recompute for an unchanged stamp")

    monkeypatch.setattr(pts, "compute_live_points", _boom)
    assert pts.refresh_points() is False
    assert spawns == [1]


def test_refresh_recomputes_on_config_change(plant: Path, spawns: list[int]) -> None:
    up.set_consent("on")
    _write(plant / "house_profiles.json", _profiles(bidirectional=True))
    assert pts.refresh_points() is True
    # Car 60 kWh at a quarter: storage 9 + 15 kWh -> 8 points, 6 more than without the car.
    assert up.load_state()["points"] == 11
    assert spawns == [1, 1]


def test_changed_config_with_same_total_does_not_resend(plant: Path, spawns: list[int]) -> None:
    up.set_consent("on")
    _write(plant / "config.json", {"live_scenario_id": "live", "note": "touch"})
    assert pts.refresh_points() is False
    assert up.load_state()["points"] == 5
    assert spawns == [1]


def test_error_clears_points_and_warns_once_per_stamp(
    plant: Path, spawns: list[int], caplog: pytest.LogCaptureFixture
) -> None:
    up.set_consent("on")
    assert up.load_state()["points"] == 5

    _write(plant / "backtesting_scenarios.json", _scenarios(pv_system_ids=["gone"]))
    caplog.set_level("WARNING")
    assert pts.refresh_points() is True
    state = up.load_state()
    assert "points" not in state and "points_v" not in state
    assert any("nicht berechenbar" in rec.message for rec in caplog.records)
    assert spawns == [1]  # no resend for a removed value

    caplog.clear()
    assert pts.refresh_points() is False
    assert not caplog.records


def test_note_live_cycle_success_refreshes_points(plant: Path, spawns: list[int]) -> None:
    up.set_consent("on")
    up.note_live_cycle_success()
    state = up.load_state()
    assert state["stage"] == "live"
    assert state["points"] == 5


def test_note_live_cycle_success_skips_points_in_shadow(
    plant: Path, spawns: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Consent without set_consent auto-refresh so the live-cycle path is isolated.
    up.save_state(
        {
            "consent": "on",
            "install_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "stage": "explorer",
            "consent_at": "2026-10-16",
        }
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    up.note_live_cycle_success()
    assert "points" not in up.load_state()


def _with_heating(plant: Path) -> None:
    doc = _components()
    doc["heating_systems"] = [
        {
            "id": "heating_home",
            "label": "Wärmepumpe",
            "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
            "heating_power_kw": 8.0,
        },
        {"id": "gas", "label": "Gas", "heat_source": {"type": "gas"}, "heating_power_kw": 3.0},
    ]
    _write(plant / "components.json", doc)
    profiles = _profiles()
    profiles["profiles"][0].update(
        {
            "heating_enabled": True,
            "persons": 2,
            "thermal": {"living_area_m2": 150.0, "building_class": 2, "hwb_kwh_m2": 40.0},
        }
    )
    profiles["profiles"][0]["consumers"].append(
        {
            "id": "heizung",
            "label": "Heizung",
            "type": "thermal_annual",
            "heating_system_id": "heating_home",
        }
    )
    _write(plant / "house_profiles.json", profiles)
    clear_components_doc_cache()


def test_live_points_use_the_scenario_heating_variant(plant: Path) -> None:
    _with_heating(plant)
    assert pts.compute_live_points()["heat"] == 1  # reference: heat pump
    _write(
        plant / "backtesting_scenarios.json",
        _scenarios(heating_system_ids={"heizung": "gas"}),
    )
    assert pts.compute_live_points()["heat"] == 0  # live variant: gas boiler
