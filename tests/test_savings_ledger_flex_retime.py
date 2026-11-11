"""Savings ledger v2, Ledger P9b: reference timing of flex consumers for one SA-day."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data.profile_manager import FlexProfileReadError, load_flexible_consumer_slot_profiles_strict
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_flex as slf

DT = 0.25
DAY_LOCAL = datetime(2026, 7, 14, 6, 0)  # Tuesday
N = 96


def _starts() -> list[datetime]:
    return [DAY_LOCAL + timedelta(minutes=15 * i) for i in range(N)]


def _rows(delivered_kw: dict[str, dict[int, float]], *, skipped: set[int] = frozenset(), meters: set[str] | None = None):
    """Slot rows as ``LedgerState.slots`` holds them; ``delivered_kw`` per consumer and slot index."""
    meters = set(delivered_kw) if meters is None else meters
    rows = []
    for i in range(N):
        if i in skipped:
            rows.append({"slot_start": str(i), "counted": False, "skip_reason": sl.SKIP_FEW_SAMPLES})
            continue
        rows.append(
            {
                "slot_start": str(i),
                "counted": True,
                "skip_reason": None,
                "flex_delivered_kwh": {cid: delivered_kw[cid].get(i, 0.0) * DT for cid in meters},
            }
        )
    return rows


def _no_windows(*cids: str) -> dict[str, slf.ConsumerWindows]:
    return {cid: slf.ConsumerWindows(enable_slots=None, native_slots=None) for cid in cids}


def _energy(result: slf.FlexRetiming, cid: str) -> float:
    return sum(slot.get(cid, 0.0) for slot in result.per_slot_kw) * DT


def _logged_energy(rows, cid: str) -> float:
    return sum(r["flex_delivered_kwh"].get(cid, 0.0) for r in rows if r["counted"])


HP = {"id": "wp", "nominal_power_kw": 3.0, "daily_target_source": "thermal_annual"}


def _evening_profile() -> list[float]:
    """1 kW 18:00–21:00 local (slots 48–59), else 0."""
    return [1.0 if 48 <= i < 60 else 0.0 for i in range(N)]


def test_energy_parity_full_coverage_follows_profile():
    # Earnie ran the heat pump at noon (PV); the profile puts it into the evening.
    rows = _rows({"wp": {i: 2.0 for i in range(24, 32)}})
    result = slf.retime_flex_day(rows, [HP], {"wp": _evening_profile()}, _no_windows("wp"), dt_h=DT)
    assert result.timing == {"wp": slf.TIMING_PROFILE}
    assert result.logged_reasons == {}
    assert _energy(result, "wp") == pytest.approx(4.0)
    assert result.delivered_kwh["wp"] == pytest.approx(4.0)
    assert all(result.per_slot_kw[i]["wp"] == 0.0 for i in range(24, 32))
    assert result.per_slot_kw[50]["wp"] == pytest.approx(4.0 / (12 * DT))


def test_energy_parity_partial_coverage_places_only_counted_slots():
    skipped = set(range(48, 54)) | {10, 11}
    rows = _rows({"wp": {i: 2.0 for i in range(24, 32)}}, skipped=skipped)
    result = slf.retime_flex_day(rows, [HP], {"wp": _evening_profile()}, _no_windows("wp"), dt_h=DT)
    assert _energy(result, "wp") == pytest.approx(_logged_energy(rows, "wp"))
    for i in skipped:
        assert result.per_slot_kw[i]["wp"] == 0.0
    # the energy goes into the six counted profile slots 54–59
    assert result.per_slot_kw[55]["wp"] == pytest.approx(4.0 / (6 * DT))


def test_cap_at_nominal_power_spills_to_next_eligible_slots():
    # 6 kWh into a 3-slot profile at 3 kW nominal: 0.75 h · 3 kW = 2.25 kWh fit, the rest spills on.
    profile = [1.0 if 48 <= i < 51 else 0.0 for i in range(N)]
    rows = _rows({"wp": {i: 3.0 for i in range(24, 32)}})
    result = slf.retime_flex_day(rows, [HP], {"wp": profile}, _no_windows("wp"), dt_h=DT)
    assert result.timing["wp"] == slf.TIMING_PROFILE
    assert max(slot["wp"] for slot in result.per_slot_kw) <= 3.0 + 1e-9
    assert _energy(result, "wp") == pytest.approx(6.0)
    assert result.per_slot_kw[51]["wp"] == pytest.approx(3.0)


def test_consumer_without_shape_uses_enable_window_flat():
    slots = frozenset(range(8, 16))
    windows = {"wp": slf.ConsumerWindows(enable_slots=slots, native_slots=None)}
    rows = _rows({"wp": {i: 2.0 for i in range(40, 44)}})
    result = slf.retime_flex_day(rows, [HP], {}, windows, dt_h=DT)
    assert result.timing["wp"] == slf.TIMING_ENABLE_WINDOW
    assert _energy(result, "wp") == pytest.approx(2.0)
    for i in range(N):
        expected = 2.0 / (8 * DT) if i in slots else 0.0
        assert result.per_slot_kw[i]["wp"] == pytest.approx(expected)


def test_profile_without_energy_in_window_falls_to_flat_window():
    windows = {"wp": slf.ConsumerWindows(enable_slots=frozenset(range(8, 16)), native_slots=None)}
    rows = _rows({"wp": {i: 2.0 for i in range(40, 44)}})
    result = slf.retime_flex_day(rows, [HP], {"wp": _evening_profile()}, windows, dt_h=DT)
    assert result.timing["wp"] == slf.TIMING_ENABLE_WINDOW


def test_filter_without_profile_uses_native_window_and_spills_after_it():
    flt = {
        "id": "pool",
        "nominal_power_kw": 0.2,
        "filter_schedule": {"enabled": True, "config_fallback": {"native_start_hour": 10, "native_duration_hours": 2}},
    }
    windows = {"pool": slf.consumer_windows(flt, _starts(), logged_native=None)}
    assert windows["pool"].native_slots == frozenset(range(16, 24))  # 10:00–12:00
    assert windows["pool"].native_source == slf.NATIVE_SOURCE_CONFIG
    # 0.6 kWh: the native window holds 8 · 0.25 · 0.2 = 0.4 kWh, the rest follows from 12:00.
    rows = _rows({"pool": {i: 0.2 for i in range(60, 72)}})
    result = slf.retime_flex_day(rows, [flt], {}, windows, dt_h=DT)
    assert result.timing["pool"] == slf.TIMING_NATIVE_WINDOW
    assert _energy(result, "pool") == pytest.approx(0.6)
    assert all(result.per_slot_kw[i]["pool"] == pytest.approx(0.2) for i in range(16, 28))
    assert result.per_slot_kw[28]["pool"] == pytest.approx(0.0, abs=1e-9)


def test_no_shape_and_no_window_keeps_logged_timing_with_reason():
    rows = _rows({"wp": {i: 2.0 for i in range(24, 32)}})
    result = slf.retime_flex_day(rows, [HP], {}, _no_windows("wp"), dt_h=DT)
    assert result.timing["wp"] == slf.TIMING_LOGGED
    assert result.logged_reasons == {"wp": slf.REASON_NO_SHAPE_NO_WINDOW}
    assert [slot["wp"] for slot in result.per_slot_kw] == [2.0 if 24 <= i < 32 else 0.0 for i in range(N)]


def test_energy_beyond_eligible_slots_keeps_logged_timing_with_reason():
    windows = {"wp": slf.ConsumerWindows(enable_slots=frozenset(range(8, 10)), native_slots=None)}
    rows = _rows({"wp": {i: 3.0 for i in range(24, 32)}})  # 6 kWh, window holds 1.5 kWh
    result = slf.retime_flex_day(rows, [HP], {"wp": [1.0] * N}, windows, dt_h=DT)
    assert result.timing["wp"] == slf.TIMING_LOGGED
    assert result.logged_reasons == {"wp": slf.REASON_EXCEEDS_ELIGIBLE}
    assert _energy(result, "wp") == pytest.approx(6.0)
    assert result.per_slot_kw[24]["wp"] == pytest.approx(3.0)


def test_consumer_without_meter_keeps_logged_timing():
    dryer = {"id": "trockner", "nominal_power_kw": 2.0, "generic_flex_window": {"start_hour": 10, "duration_h": 2}}
    rows = _rows({"wp": {i: 2.0 for i in range(24, 32)}})
    windows = _no_windows("wp") | {"trockner": slf.consumer_windows(dryer, _starts(), logged_native=None)}
    result = slf.retime_flex_day(rows, [HP, dryer], {"wp": _evening_profile(), "trockner": [1.0] * N}, windows, dt_h=DT)
    assert result.timing == {"wp": slf.TIMING_PROFILE, "trockner": slf.TIMING_LOGGED_NO_METER}
    assert "trockner" not in result.logged_reasons
    assert all(slot["trockner"] == 0.0 for slot in result.per_slot_kw)


def test_unconfigured_consumer_and_ev_keep_logged_timing():
    ev = {"id": "wallbox", "type": "ev", "nominal_power_kw": 11.0}
    rows = _rows({"wallbox": {i: 11.0 for i in range(80, 84)}, "alt": {5: 1.0}})
    result = slf.retime_flex_day(rows, [ev], {"wallbox": [1.0] * N}, _no_windows("wallbox"), dt_h=DT)
    assert result.timing == {"wallbox": slf.TIMING_LOGGED, "alt": slf.TIMING_LOGGED}
    assert result.logged_reasons == {"wallbox": slf.REASON_EV_RULE_MISSING, "alt": slf.REASON_NOT_CONFIGURED}
    assert _energy(result, "wallbox") == pytest.approx(11.0)
    assert _energy(result, "alt") == pytest.approx(0.25)


def test_metered_consumer_without_energy_is_no_energy():
    rows = _rows({"wp": {}})
    result = slf.retime_flex_day(rows, [HP], {"wp": _evening_profile()}, _no_windows("wp"), dt_h=DT)
    assert result.timing["wp"] == slf.TIMING_NO_ENERGY
    assert _energy(result, "wp") == 0.0


def test_missing_windows_or_wrong_profile_length_raise():
    rows = _rows({"wp": {30: 1.0}})
    with pytest.raises(ValueError, match="no windows"):
        slf.retime_flex_day(rows, [HP], {}, {}, dt_h=DT)
    with pytest.raises(ValueError, match="profile"):
        slf.retime_flex_day(rows, [HP], {"wp": [1.0] * 4}, _no_windows("wp"), dt_h=DT)


def test_consumer_windows_thermal_and_generic():
    hp = HP | {"thermal_flex_window": {"start_hour": 22, "duration_h": 4}}
    windows = slf.consumer_windows(hp, _starts(), logged_native=None)
    # 22:00 + 4 h: the MILP's window rule keeps the run inside the calendar day
    # (``generic_allowed_slot_hours``), so only 22:00–24:00 = slots 64–71 of a day from 06:00.
    assert windows.enable_slots == frozenset(range(64, 72))
    assert windows.native_slots is None
    generic = {"id": "spuel", "nominal_power_kw": 2.0, "generic_flex_window": {"start_hour": 12, "start_shift_h": 1, "duration_h": 1}}
    assert slf.consumer_windows(generic, _starts(), logged_native=None).enable_slots == frozenset(range(20, 32))
    with pytest.raises(ValueError, match="naive"):
        slf.consumer_windows(generic, [DAY_LOCAL.replace(tzinfo=timezone.utc)], logged_native=None)


def test_logged_native_window_wins_over_the_configured_one():
    flt = {
        "id": "pool",
        "nominal_power_kw": 0.2,
        "filter_schedule": {"enabled": True, "config_fallback": {"native_start_hour": 10, "native_duration_hours": 2}},
    }
    logged = {"native_start_hour": 14.0, "native_duration_hours": 1.0}
    windows = slf.consumer_windows(flt, _starts(), logged_native=logged)
    assert windows.native_slots == frozenset(range(32, 36))  # 14:00–15:00
    assert windows.native_source == slf.NATIVE_SOURCE_LOG
    assert slf.consumer_windows(HP, _starts(), logged_native=None).native_source is None


# --- slot rows carry pv_kwh and k_push_cent ----------------------------------


def _closed(pv_kw: float) -> dict:
    return {
        "sample_count": 30,
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
        "pv_kw": pv_kw,
        "grid_kw": 0.5,
        "battery_kw": 0.0,
        "house_kw": pv_kw + 0.5,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
        "flex_kw": {"wp": 1.0},
    }


def test_slot_rows_carry_pv_and_sell_price():
    tz = timezone(timedelta(hours=2))
    start = datetime(2026, 7, 14, 12, 0, tzinfo=tz)
    battery = {
        "battery_capacity_kwh": 10.0,
        "efficiency": 0.95,
        "min_soc": 5.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
    }

    def bounds(moment):
        return start.replace(hour=6), start.replace(hour=6) + timedelta(days=1)

    inp = sl.LedgerInput(start, _closed(2.0), k_act_cent=30.0, k_push_cent=8.0)
    state = sl.start_chain(inp, bounds, reason=sl.CHAIN_FIRST_RUN)
    state, _ = sl.advance(state, inp, battery, bounds, app_version="t", dt_h=DT)
    counted = state.slots[-1]
    assert counted["pv_kwh"] == pytest.approx(0.5)
    assert counted["k_push_cent"] == 8.0
    no_price = sl.LedgerInput(start + timedelta(minutes=15), _closed(2.0), None, None)
    state, _ = sl.advance(state, no_price, battery, bounds, app_version="t", dt_h=DT)
    assert state.slots[-1]["pv_kwh"] == 0.0
    assert state.slots[-1]["k_push_cent"] is None
    state = sl.record_error_slot(state, start + timedelta(minutes=30))
    assert state.slots[-1]["pv_kwh"] == 0.0
    assert state.slots[-1]["k_push_cent"] is None


def test_state_without_new_slot_fields_still_loads():
    """A state file written before P9b has slot rows without ``pv_kwh`` / ``k_push_cent``."""
    raw = {
        "savings_v": 1,
        "chain_start": "2026-07-14T06:00:00+02:00",
        "chain_start_reason": "first_run",
        "shadow_soc": 50.0,
        "day_start": "2026-07-14T06:00:00+02:00",
        "day_end": "2026-07-15T06:00:00+02:00",
        "last_slot_start": "2026-07-14T06:00:00+02:00",
        "soc_actual_end": 50.0,
        "prev_correction_eur": None,
        "slots": [
            {
                "slot_start": "2026-07-14T06:00:00+02:00",
                "counted": True,
                "skip_reason": None,
                "cost_with_eur": 0.1,
                "cost_without_eur": 0.1,
                "import_kwh_with": 0.3,
                "import_kwh_without": 0.3,
                "export_kwh_with": 0.0,
                "export_kwh_without": 0.0,
                "k_act_cent": 30.0,
                "shadow_soc_end": 50.0,
                "house_kwh": 0.3,
            }
        ],
        "days_closed": 0,
    }
    state = sl.LedgerState.from_dict(raw)
    assert "pv_kwh" not in state.slots[0]
    assert sl.day_slots_record(state)["slots"][0]["house_kwh"] == 0.3


# --- strict profile read -------------------------------------------------------


def test_strict_profile_read_repeats_hour_over_its_slots(tmp_path):
    path = tmp_path / "flexible_consumer_profiles.csv"
    pd.DataFrame({"Month": [7, 7], "Weekday": [1, 1], "Hour": [10, 11], "wp": [0.5, 1.5]}).to_csv(
        path, sep=";", index=False
    )
    slots = [datetime(2026, 7, 14, 10, 0) + timedelta(minutes=15 * i) for i in range(8)]
    profiles = load_flexible_consumer_slot_profiles_strict(
        slots, [{"id": "wp"}, {"id": "ohne"}], profile_path=str(path)
    )
    assert profiles == {"wp": [0.5] * 4 + [1.5] * 4}


def test_strict_profile_read_missing_file_means_no_profiles(tmp_path):
    profiles = load_flexible_consumer_slot_profiles_strict(
        [datetime(2026, 7, 14, 10, 0)], [{"id": "wp"}], profile_path=str(tmp_path / "missing.csv")
    )
    assert profiles == {}


@pytest.mark.parametrize(
    "content",
    [
        "Month;Weekday;Hour;wp\n7;1;10;abc\n",  # non-numeric
        "Month;Weekday;wp\n7;1;0.5\n",  # no Hour column
        "Month;Weekday;Hour;wp\n7;1;10;\n",  # empty value
        "Month;Weekday;Hour;wp\n7;1;10;0.5\n7;1;10;0.6\n",  # repeated key row
        "Month;Weekday;Hour;wp\n7;1;9;0.5\n",  # no row for hour 10
    ],
)
def test_strict_profile_read_raises_on_broken_file(tmp_path, content):
    path = tmp_path / "flexible_consumer_profiles.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(FlexProfileReadError):
        load_flexible_consumer_slot_profiles_strict(
            [datetime(2026, 7, 14, 10, 0)], [{"id": "wp"}], profile_path=str(path)
        )


def test_strict_profile_read_rejects_aware_times(tmp_path):
    with pytest.raises(ValueError, match="naive"):
        load_flexible_consumer_slot_profiles_strict(
            [datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)], [{"id": "wp"}], profile_path=str(tmp_path / "x.csv")
        )
