"""Loxone debug / device / live pages — regressions from ui/ review slice 1c."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from integrations.loxone_connectivity_base import LoxoneCheck
from runtime_store.ehal_push_inbox import STATE_ZERO_HELD

_TZ = ZoneInfo("Europe/Vienna")


# --- Geräte: Plan-Häkchen (1c-3) ------------------------------------------------------


def _rec(starts: list[datetime]):
    from optimizer.appliance_recommendation import ApplianceRecommendation, StartOption

    options = [
        StartOption(start_datetime=s, cost_eur=1.0, stars=3, savings_vs_now_eur=0.0)
        for s in starts
    ]
    return ApplianceRecommendation(
        options=options, cheapest=options[0], immediate=options[0], skipped_start_slots=0
    )


def test_plan_tick_follows_the_stored_schedule_when_options_shift(monkeypatch):
    from ui.pages import page_devices

    state: dict = {}
    monkeypatch.setattr(page_devices.st, "session_state", state)
    monkeypatch.setattr(
        page_devices,
        "_schedule_matches_option",
        lambda schedule, start: datetime.fromisoformat(schedule["start_at"]) == start,
    )
    t18 = datetime(2026, 7, 8, 18, 0, tzinfo=_TZ)
    schedule = {"start_at": t18.isoformat()}
    step = timedelta(minutes=30)

    page_devices._sync_plan_checkbox_state("wm", _rec([t18 - step, t18, t18 + step]), schedule)
    assert [state[page_devices._plan_checkbox_key("wm", i)] for i in range(3)] == [
        False,
        True,
        False,
    ]
    # 30 min later the list starts one slot further: 18:00 is now index 0.
    page_devices._sync_plan_checkbox_state("wm", _rec([t18, t18 + step, t18 + 2 * step]), schedule)
    assert [state[page_devices._plan_checkbox_key("wm", i)] for i in range(3)] == [
        True,
        False,
        False,
    ]
    # Schedule gone (removed or expired) -> no tick left behind.
    page_devices._sync_plan_checkbox_state("wm", _rec([t18, t18 + step]), None)
    assert not any(state[page_devices._plan_checkbox_key("wm", i)] for i in range(2))


# --- Live-Modus (1c-7) ------------------------------------------------------------------


def test_opt_in_soc_null_in_run_state_uses_live_soc():
    from ui.live_mode import _opt_in_initial_soc

    assert _opt_in_initial_soc({"soc_percent": None}, 42.0) == 42.0
    assert _opt_in_initial_soc({}, 42.0) == 42.0
    assert _opt_in_initial_soc(None, 42.0) == 42.0
    assert _opt_in_initial_soc({"soc_percent": 55}, 42.0) == 55.0


# --- Loxone-Debug (1c-5, 1c-6) ----------------------------------------------------------


def test_push_field_never_received_is_not_shown_as_just_read(monkeypatch):
    import ui.loxone_debug  # noqa: F401 — loads loxone_debug_rows in the app's import order
    from ui import loxone_debug_rows

    monkeypatch.setattr(loxone_debug_rows, "_inbox_last_read_local", lambda _eid: "")
    item = LoxoneCheck(
        "sens_grid_power_active",
        "sens_grid_power_active",
        True,
        "Wert=0.0",
        state=STATE_ZERO_HELD,
    )
    row = loxone_debug_rows._read_row_from_check(
        "sens_grid_power_active", item, mapping="sens_grid_power_active", read_at="12:00:00"
    )
    assert row["Zuletzt gelesen"] == "—"
    # A pull read (no push state) keeps the read time.
    pulled = LoxoneCheck("sens_grid_power_active", "sens_grid_power_active", True, "Wert=1.0")
    row = loxone_debug_rows._read_row_from_check(
        "sens_grid_power_active", pulled, mapping="sens_grid_power_active", read_at="12:00:00"
    )
    assert row["Zuletzt gelesen"] == "12:00:00"


@pytest.mark.parametrize(
    ("silent_run", "expect_info", "expect_warning"),
    [(True, True, False), (False, False, True)],
)
def test_missing_ehal_writes_is_only_called_silent_when_the_run_was(
    monkeypatch, silent_run, expect_info, expect_warning
):
    from ui import loxone_debug

    seen: dict[str, list[str]] = {"info": [], "warning": []}
    monkeypatch.setattr(loxone_debug, "_render_hub_write_failure", lambda: None)
    monkeypatch.setattr(loxone_debug, "has_produktiv_run", lambda _s: True)
    monkeypatch.setattr(loxone_debug, "_render_write_table", lambda _rows: None)
    monkeypatch.setattr(loxone_debug, "build_ehal_write_rows", lambda _w: [])
    monkeypatch.setattr(loxone_debug.st, "info", lambda msg, **_k: seen["info"].append(msg))
    monkeypatch.setattr(
        loxone_debug.st, "warning", lambda msg, **_k: seen["warning"].append(msg)
    )
    loxone_debug._render_ehal_writes(
        {"completed_at": "x"},
        silent_run=silent_run,
        completed_at="x",
        loxone_sent={},
        ehal_writes=None,
    )
    assert bool(seen["info"]) is expect_info
    assert bool(seen["warning"]) is expect_warning
    if expect_warning:
        assert "nicht im Silent-Modus" in seen["warning"][0]
