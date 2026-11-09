"""AppTest: Monitor section „Wallboxen“ of the dynamic EV assignment (multi-EV M3)."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from runtime_store import ev_assignments as store


def _panel_app():
    from ui.ev_assignment_panel import render_ev_assignment_panel

    render_ev_assignment_panel()


def _dynamic_evs() -> list[dict]:
    from house_config.wallboxes import normalize_wallbox, resolve_dynamic_ev_view

    wallboxes = {
        wid: normalize_wallbox(
            {
                "id": wid,
                "label": label,
                "voltage_v": 230,
                "phases": 3,
                "min_current_a": 6,
                "max_current_a": 16,
                "unknown_vehicle": "immediate",
                "ehal_bindings": {f"evcs.{wid}.sens_evcs_connected": ""},
            },
            index=0,
        )
        for wid, label in (("lp1", "Garage"), ("lp2", "Carport"))
    }
    evs = []
    for ev_id, name in (("car_a", "Kombi"), ("car_c", "Kleinwagen")):
        spec = {
            "id": ev_id,
            "name": name,
            "type": "ev",
            "phases": 3,
            "min_current_a": 6.0,
            "max_current_a": 16.0,
            "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["lp1", "lp2"]},
            "charging_schedule": {"forecast_when_absent": False},
            "ehal_bindings": (
                {"ev.car_a.sens_ev_charge_power": ""} if ev_id == "car_a" else {}
            ),
        }
        resolve_dynamic_ev_view(spec, wallboxes, label=ev_id)
        evs.append(spec)
    return evs


def _patch_consumers(monkeypatch, evs: list[dict]) -> None:
    import config

    monkeypatch.setattr(
        config,
        "get_flexible_consumers",
        lambda optimizer_only=False, *, raw_dynamic=False: [dict(e) for e in evs],
    )


def _snapshot() -> None:
    store.write_assignments_snapshot(
        [
            {
                "wallbox_id": "lp1",
                "status": "assigned",
                "ev_id": "car_a",
                "evidence": "test_charge",
                "since": "2026-11-09T18:05:00",
                "session": "2026-11-09T18:00:00",
                "note": "",
                "candidates": ["car_a", "car_c"],
            },
            {
                "wallbox_id": "lp2",
                "status": "plugged_unknown",
                "ev_id": None,
                "evidence": None,
                "since": "2026-11-09T18:10:00",
                "session": "2026-11-09T18:10:00",
                "note": "Probeladung nicht möglich (kein Auto mit Ladeleistungs-Sensor)",
                "candidates": ["car_c"],
            },
        ],
        updated_at="2026-11-09T18:10:05",
    )


def test_panel_shows_assignment_policy_and_sensor_hint(monkeypatch):
    _patch_consumers(monkeypatch, _dynamic_evs())
    _snapshot()
    at = AppTest.from_function(_panel_app).run()
    assert not at.exception
    texts = [m.value for m in at.markdown]
    assert "**Garage:** Kombi (Probeladung)" in texts
    assert any(
        t.startswith("**Carport:** Auto angesteckt, noch nicht erkannt — lädt sofort") for t in texts
    )
    captions = [c.value for c in at.caption]
    assert any("Kleinwagen" in c and "Probeladung" in c for c in captions)


def test_pick_writes_a_request_for_the_plug_session(monkeypatch):
    from runtime_store import optimize_request

    _patch_consumers(monkeypatch, _dynamic_evs())
    monkeypatch.setattr(optimize_request, "request_optimize", lambda **_kw: None)
    _snapshot()
    at = AppTest.from_function(_panel_app).run()
    at.selectbox(key="ev_assign_pick_lp2").set_value("car_c")
    at.button(key="ev_assign_pick_btn_lp2").click().run()
    assert not at.exception
    picks = store.consume_picks()
    assert [(p["wallbox_id"], p["ev_id"], p["session"]) for p in picks] == [
        ("lp2", "car_c", "2026-11-09T18:10:00")
    ]


def test_panel_is_silent_without_dynamic_evs(monkeypatch):
    _patch_consumers(monkeypatch, [])
    at = AppTest.from_function(_panel_app).run()
    assert not at.exception
    assert not at.subheader
