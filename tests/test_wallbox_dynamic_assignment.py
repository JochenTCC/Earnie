"""Schema, loader view and live overlay of dynamic EVs (multi-EV M3)."""
from __future__ import annotations

import pytest

from house_config.wallboxes import (
    VIEW_CHARGER_ID_KEY,
    VIEW_DYNAMIC_KEY,
    _route_one_ev,
    assigned_dynamic_ev_view,
    assigned_wallbox_id,
    dynamic_charger_consumers,
    normalize_wallbox,
    normalize_wallbox_assignment,
    reject_shared_fixed_wallboxes,
    resolve_dynamic_ev_view,
    serialize_wallbox,
)
from runtime_store import ev_assignments as store


def _wallbox(wallbox_id: str, *, max_a: float = 16.0, phases: int = 3, **extra) -> dict:
    raw = {
        "id": wallbox_id,
        "voltage_v": 230,
        "phases": phases,
        "min_current_a": 6,
        "max_current_a": max_a,
        "unknown_vehicle": "off",
        "ehal_bindings": {
            f"evcs.{wallbox_id}.set_evcs_max_current": "",
            f"evcs.{wallbox_id}.sens_evcs_connected": "",
        },
    }
    raw.update(extra)
    return normalize_wallbox(raw, index=0)


def _ev(**extra) -> dict:
    spec = {
        "id": "car_a",
        "type": "ev",
        "phases": 3,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["wb_big", "wb_small"]},
        "charging_schedule": {"forecast_when_absent": False},
    }
    spec.update(extra)
    return spec


WALLBOXES = {"wb_big": _wallbox("wb_big"), "wb_small": _wallbox("wb_small", max_a=10.0)}


def test_dynamic_assignment_normalizes() -> None:
    raw = {"mode": "dynamic", "wallbox_ids": [" wb_1 ", "wb_2"]}
    assert normalize_wallbox_assignment(raw, label="x") == {
        "mode": "dynamic",
        "wallbox_ids": ["wb_1", "wb_2"],
    }


@pytest.mark.parametrize("ids", [[], None, ["wb_1", "wb_1"], ["wb_1", ""]])
def test_dynamic_assignment_needs_distinct_wallboxes(ids) -> None:
    with pytest.raises(ValueError, match="wallbox_ids"):
        normalize_wallbox_assignment({"mode": "dynamic", "wallbox_ids": ids}, label="x")


def test_unknown_vehicle_policy_round_trips() -> None:
    wallbox = _wallbox("wb_1", unknown_vehicle="immediate")
    assert serialize_wallbox(wallbox)["unknown_vehicle"] == "immediate"
    assert "unknown_vehicle" not in serialize_wallbox(
        normalize_wallbox({**serialize_wallbox(wallbox), "unknown_vehicle": None}, index=0)
    )


def test_unknown_vehicle_policy_is_checked() -> None:
    with pytest.raises(ValueError, match="unknown_vehicle muss"):
        _wallbox("wb_1", unknown_vehicle="sometimes")
    with pytest.raises(ValueError, match="set_evcs_mode"):
        _wallbox("wb_1", unknown_vehicle="pv_only")
    wallbox = _wallbox(
        "wb_1",
        unknown_vehicle="pv_only",
        ehal_bindings={"evcs.wb_1.set_evcs_mode": ""},
    )
    assert wallbox["unknown_vehicle"] == "pv_only"


def test_loader_view_uses_the_smallest_wallbox_and_no_charger_bindings() -> None:
    spec = _ev()
    resolve_dynamic_ev_view(spec, WALLBOXES, label="car_a")
    assert spec["nominal_power_kw"] == pytest.approx(10 * 230 * 3 / 1000)
    assert [w["id"] for w in spec[VIEW_DYNAMIC_KEY]] == ["wb_big", "wb_small"]
    assert "ehal_bindings" not in spec
    assert assigned_wallbox_id(spec) == ""


def test_loader_view_rejects_what_m3_cannot_do() -> None:
    with pytest.raises(ValueError, match="forecast_when_absent"):
        resolve_dynamic_ev_view(
            _ev(charging_schedule={"forecast_when_absent": True}), WALLBOXES, label="car_a"
        )
    with pytest.raises(ValueError, match="Lade-Bindings"):
        resolve_dynamic_ev_view(
            _ev(ehal_bindings={"set_evcs_max_current": ""}), WALLBOXES, label="car_a"
        )
    no_policy = dict(WALLBOXES, wb_small={**WALLBOXES["wb_small"]})
    no_policy["wb_small"].pop("unknown_vehicle")
    with pytest.raises(ValueError, match="unknown_vehicle fehlt"):
        resolve_dynamic_ev_view(_ev(), no_policy, label="car_a")
    with pytest.raises(ValueError, match="fehlt in components.json"):
        resolve_dynamic_ev_view(_ev(), {"wb_big": WALLBOXES["wb_big"]}, label="car_a")


def test_assigned_view_uses_the_pair_and_the_wallbox_kennung() -> None:
    spec = _ev(ehal_bindings={"ev.car_a.sens_ev_connected": ""})
    resolve_dynamic_ev_view(spec, WALLBOXES, label="car_a")
    view = assigned_dynamic_ev_view(spec, "wb_big")
    assert view["nominal_power_kw"] == pytest.approx(16 * 230 * 3 / 1000)
    assert view[VIEW_CHARGER_ID_KEY] == "wb_big"
    assert view["ehal_bindings"] == {
        "evcs.wb_big.set_evcs_max_current": "",
        "evcs.wb_big.sens_evcs_connected": "",
        "ev.car_a.sens_ev_connected": "",
    }
    # The loader view is not changed.
    assert spec["nominal_power_kw"] == pytest.approx(10 * 230 * 3 / 1000)
    with pytest.raises(ValueError, match="nicht nutzen"):
        assigned_dynamic_ev_view(spec, "wb_other")


def test_a_wallbox_is_fixed_or_dynamic_in_one_profile() -> None:
    fixed = {"id": "car_b", "type": "ev", "wallbox_assignment": {"mode": "fixed", "wallbox_id": "wb_big"}}
    with pytest.raises(ValueError, match="entweder fest oder dynamisch"):
        reject_shared_fixed_wallboxes([_ev(), fixed], profile_id="p")
    other = {**fixed, "wallbox_assignment": {"mode": "fixed", "wallbox_id": "wb_x"}}
    reject_shared_fixed_wallboxes([_ev(), other], profile_id="p")


def test_save_drops_the_view_of_a_dynamic_ev() -> None:
    spec = _ev(ehal_bindings={"ev.car_a.sens_ev_connected": ""})
    resolve_dynamic_ev_view(spec, WALLBOXES, label="car_a")
    stored = _route_one_ev(spec, {}, [])
    assert VIEW_DYNAMIC_KEY not in stored
    assert "nominal_power_kw" not in stored and "min_power_kw" not in stored
    assert stored["wallbox_assignment"]["mode"] == "dynamic"
    with pytest.raises(ValueError, match="gehören an die Wallboxen"):
        _route_one_ev(_ev(ehal_bindings={"evcs.car_a.set_evcs_max_current": ""}), {}, [])


def test_dynamic_charger_consumers_from_file_shape() -> None:
    house = {"profiles": {"p": {"consumers": [_ev()]}}}
    components = {"wallboxes": [serialize_wallbox(w) for w in WALLBOXES.values()]}
    chargers = dynamic_charger_consumers(house, components)
    assert [(c["id"], c["type"]) for c in chargers] == [("wb_big", "ev"), ("wb_small", "ev")]
    with pytest.raises(ValueError, match="fehlt in components.json"):
        dynamic_charger_consumers(house, {"wallboxes": []})


def test_overlay_plans_only_assigned_dynamic_evs() -> None:
    spec = _ev(name="car_a")
    resolve_dynamic_ev_view(spec, WALLBOXES, label="car_a")
    fixed = {"id": "car_b", "type": "ev"}
    try:
        store.set_live_assignments(None)
        assert store.apply_live_assignments([spec, fixed]) == [spec, fixed]
        store.set_live_assignments({})
        assert store.apply_live_assignments([spec, fixed]) == [fixed]
        store.set_live_assignments({"car_a": "wb_big"})
        planned = store.apply_live_assignments([spec, fixed])
        assert [c.get(VIEW_CHARGER_ID_KEY) for c in planned] == ["wb_big", None]
    finally:
        store.set_live_assignments(None)


def test_pick_requests_are_consumed_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    store.request_pick("wb_big", "car_a", "2026-11-09T18:00:00")
    picks = store.consume_picks()
    assert [(p["wallbox_id"], p["ev_id"], p["session"]) for p in picks] == [
        ("wb_big", "car_a", "2026-11-09T18:00:00")
    ]
    assert store.consume_picks() == []


def test_simulation_rejects_dynamic_evs() -> None:
    from simulation.engine_scenario import _reject_dynamic_evs

    with pytest.raises(ValueError, match="dynamischer Wallbox-Zuordnung"):
        _reject_dynamic_evs([_ev()])
    assert _reject_dynamic_evs([{"id": "car_b", "type": "ev"}]) == [{"id": "car_b", "type": "ev"}]
