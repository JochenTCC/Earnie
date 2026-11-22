"""AppTest: Manuelle Geräte with appliances, a planning snapshot and reserve devices.

The page smoke (test_page_devices_apptest.py) only covers the empty state. Here
``config.get_appliances`` and the persisted main.py snapshot are replaced so the
recommendation table, the plan checkbox and the reserve trigger buttons render.
Schedules and reserve states are written to the isolated runtime dir (conftest).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

import config
from optimizer.appliance_recommendation import recommend_start_times
from runtime_store import appliance_schedules
from runtime_store.live_display_loader import planning_matrix_from_snapshot
from runtime_store.powerstation_reserves import load_reserve_states
from tests.apptest.helpers import assert_clean, messages
from ui.pages import page_devices

_SCRIPT = Path(__file__).parent / "scripts" / "run_cov_devices.py"
_TIMEOUT = 30

_WM = {
    "id": "wm",
    "name": "Waschmaschine",
    "default_power_kw": 2.0,
    "default_runtime_h": 1.0,
    "recommendation_horizon_h": 4,
    "power_source": "loxone",
    "loxone_inputs": {"power_name": "WM_Power"},
}
_DISH = {"id": "dish", "name": "Spüler", "default_power_kw": 1.0, "default_runtime_h": 1.0}
_NO_POWER = {"id": "dryer", "name": "Trockner", "default_power_kw": 0.0, "default_runtime_h": 1.0}
_TOO_LONG = {"id": "long", "name": "Langläufer", "default_power_kw": 1.0, "default_runtime_h": 10.0}
_RESERVE = {
    "id": "tool",
    "name": "Akkuwerkzeug",
    "mode": "reserve",
    "powerstation_id": "ps1",
    "default_power_kw": 1.0,
    "default_runtime_h": 2.0,
    "loxone_power_name": "PS_Power",
}
_RESERVE_NO_PS = {"id": "lamp", "name": "Lampe", "mode": "reserve", "default_power_kw": 0.5}


def _matrix_start() -> datetime:
    tz = ZoneInfo(config.get_planning_timezone())
    return datetime.now(tz).replace(minute=0, second=0, microsecond=0)


def _matrix(slots: int = 24) -> list[dict]:
    """Quarter-hour matrix from the current full hour; slots 8..11 (+2 h) are cheap."""
    start = _matrix_start()
    return [
        {
            "slot_datetime": (start + timedelta(minutes=15 * i)).isoformat(),
            "k_act": 10.0 if 8 <= i <= 11 else 30.0,
            "k_push_act": 8.0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
        }
        for i in range(slots)
    ]


def _snapshot(*, age: timedelta = timedelta(minutes=5), matrix: list | None = None) -> dict:
    # Naive local time, as runtime_store.live_optimization_debug writes it.
    completed = datetime.now() - age
    return {
        "completed_at": completed.isoformat(timespec="seconds"),
        "planning_matrix": _matrix() if matrix is None else matrix,
    }


@pytest.fixture
def page(monkeypatch):
    """Configure appliances and snapshot; returns a setter for both."""

    def _set(appliances: list[dict], snapshot: dict | None = None) -> AppTest:
        monkeypatch.setattr(page_devices.config, "get_appliances", lambda: list(appliances))
        monkeypatch.setattr(page_devices, "load_live_display_snapshot", lambda: snapshot)
        return AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT).run()

    return _set


def _markdown(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_no_snapshot_waits_for_first_main_run(page):
    at = page([_WM])
    assert_clean(at)
    assert any("Warte auf ersten main.py-Durchlauf" in i for i in messages(at)["info"])
    assert not any(s.value == "Start-Empfehlung" for s in at.subheader)


def test_snapshot_without_matrix_warns(page):
    at = page([_WM], {"completed_at": datetime.now().isoformat(timespec="seconds")})
    assert_clean(at)
    assert any("keine Planungsmatrix" in w for w in messages(at)["warning"])


def test_stale_snapshot_warns_but_still_recommends(page):
    at = page([_WM], _snapshot(age=timedelta(days=2)))
    assert_clean(at)
    assert any("Daten veraltet" in w for w in messages(at)["warning"])
    assert any(s.value == "Start-Empfehlung" for s in at.subheader)


def test_fresh_snapshot_shows_age_caption_and_star_settings(page):
    at = page([_WM], _snapshot())
    assert_clean(at)
    assert any("Planungsdaten vom letzten main.py-Lauf" in c for c in messages(at)["caption"])
    assert any(e.label == "Sterne-Schwellen" for e in at.expander)


def test_recommendation_renders_cheapest_start_table_and_captions(page):
    at = page([_WM], _snapshot())
    assert_clean(at)
    md = _markdown(at)
    captions = messages(at)["caption"]
    assert "#### Waschmaschine" in md
    assert any("Empfehlungshorizont: **4 h**" in c for c in captions)
    assert any("Loxone-Merker: `WM_Power`" in c for c in captions)

    cheapest = (_matrix_start() + timedelta(hours=2)).strftime("%H:%M")
    caption = next(m for m in md if m.startswith("Günstigste Startzeit"))
    assert f"**{cheapest} Uhr**" in caption
    # Immediate start is more expensive than the cheapest → red (positive) delta.
    assert "Delta (sofort)" in caption and "+" in caption

    # Table: header + one row per half-hour start in the 4 h horizon (8 starts).
    assert "**Startzeit**" in md and "**Ranking**" in md and "**Delta**" in md
    plan_boxes = [c for c in at.checkbox if str(c.key).startswith("appliance_plan_wm_")]
    assert len(plan_boxes) == 8
    assert not any(c.value for c in plan_boxes)
    assert f"**{cheapest}**" in md
    assert any(m.startswith("★★★★★") for m in md)
    # Layout CSS for the table is injected once per table.
    css = [m for m in md if m.lstrip().startswith("<style>")]
    assert css and "st-key-appliance_rec_table_" in css[0]


def test_plan_checkbox_saves_and_unticking_removes_schedule(page):
    at = page([_WM], _snapshot())
    rec = recommend_start_times(
        planning_matrix_from_snapshot(_snapshot()),
        2.0,
        1.0,
        horizon_h=4,
    )
    target_index = 4  # start = +2 h, the cheapest option
    at.checkbox(key=f"appliance_plan_wm_{target_index}").check().run()
    assert_clean(at)
    stored = appliance_schedules.load_schedules()["wm"]
    assert datetime.fromisoformat(stored["start_at"]) == rec.options[target_index].start_datetime
    assert stored["power_kw"] == 2.0
    # Stored schedule is the truth: exactly the matching option stays ticked.
    ticked = [c.key for c in at.checkbox if c.value]
    assert ticked == [f"appliance_plan_wm_{target_index}"]
    assert any("Aktiver Optimierungsplan bis" in c for c in messages(at)["caption"])

    at.checkbox(key=f"appliance_plan_wm_{target_index}").uncheck().run()
    assert_clean(at)
    assert "wm" not in appliance_schedules.load_schedules()
    assert not any("Aktiver Optimierungsplan" in c for c in messages(at)["caption"])


def test_invalid_power_and_too_long_runtime_and_skipped_starts(page):
    at = page([_NO_POWER, _TOO_LONG, _DISH], _snapshot())
    assert_clean(at)
    warnings = messages(at)["warning"]
    assert any("Keine gültige Leistung" in w for w in warnings)
    assert any("keine Empfehlung möglich" in w for w in warnings)
    # Spüler: default horizon 6 h over a 6 h matrix → last start cannot finish.
    assert any("1 spätere Startstunde(n) entfallen" in c for c in messages(at)["caption"])
    assert any("Empfehlungshorizont: **6 h**" in c for c in messages(at)["caption"])


def test_advice_without_matrix_still_renders_reserve_section(page):
    at = page([_WM, _RESERVE], None)
    assert_clean(at)
    assert [s.value for s in at.subheader] == ["Energiereserve"]


def test_reserve_appliance_status_and_trigger_buttons(page):
    at = page([_RESERVE, _RESERVE_NO_PS])
    assert_clean(at)
    captions = messages(at)["caption"]
    status = next(c for c in captions if c.startswith("Powerstation: `ps1`"))
    assert "Ziel: **2" in status and "Status: **empty**" in status
    assert any("Nachladen preisoptimal" in c for c in captions)
    assert any("Leistungsmerker: `PS_Power`" in c for c in captions)
    assert any("Keine Powerstation verknüpft" in e for e in messages(at)["error"])
    # Device without powerstation has no trigger buttons.
    keys = {b.key for b in at.button}
    assert "reserve_trigger_on_tool" in keys and "reserve_trigger_on_lamp" not in keys

    at.button(key="reserve_trigger_on_tool").click().run()
    assert_clean(at)
    entry = load_reserve_states()["ps1"]
    assert entry["state"] == "discharging" and entry["trigger_active"] is True
    captions = messages(at)["caption"]
    assert any("Status: **discharging**" in c for c in captions)
    assert not any("Nachladen preisoptimal" in c for c in captions)

    at.button(key="reserve_trigger_off_tool").click().run()
    assert_clean(at)
    entry = load_reserve_states()["ps1"]
    assert entry["state"] == "empty" and entry["trigger_active"] is False
    assert any("Status: **empty**" in c for c in messages(at)["caption"])
