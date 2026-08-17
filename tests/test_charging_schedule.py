"""Gezielte Unit-Tests für optimizer/charging_schedule.py.

Ergänzt tests/test_charging_context.py (das den Modul-Code primär über die
charging_context-Fassade abdeckt) um die bislang unabgedeckten Zweige der
reinen Hilfsfunktionen: Timezone-Alignment, Matrix-Zeitauflösung,
Loxone-Zeit-Parsing (Text/Zahl/Wochentag) und die MILP-Fenster-Helfer.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from optimizer import charging_schedule as cs


# ---------------------------------------------------------------------------
# _align_like
# ---------------------------------------------------------------------------

def test_align_like_naive_reference_strips_aware_dt():
    reference = datetime(2026, 1, 1, 12, 0)
    dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert cs._align_like(reference, dt) == datetime(2026, 1, 1, 12, 0)


def test_align_like_aware_reference_converts_differing_tz():
    tz_plus2 = timezone(timedelta(hours=2))
    reference = datetime(2026, 1, 1, 12, 0, tzinfo=tz_plus2)
    dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    result = cs._align_like(reference, dt)
    assert result.tzinfo == tz_plus2
    assert result == datetime(2026, 1, 1, 14, 0, tzinfo=tz_plus2)


def test_align_like_aware_reference_same_tz_passthrough():
    reference = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    dt = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    assert cs._align_like(reference, dt) is dt


# ---------------------------------------------------------------------------
# matrix_slot_datetime
# ---------------------------------------------------------------------------

def test_matrix_slot_datetime_with_date_object():
    row = {"date": date(2026, 6, 1), "hour": 5}
    assert cs.matrix_slot_datetime([row], 0) == datetime(2026, 6, 1, 5, 0)


def test_matrix_slot_datetime_with_datetime_date_field():
    row = {"date": datetime(2026, 6, 1, 9, 30), "hour": 5}
    assert cs.matrix_slot_datetime([row], 0) == datetime(2026, 6, 1, 5, 0)


def test_matrix_slot_datetime_without_date_falls_back_to_now():
    row = {"hour": 3}
    result = cs.matrix_slot_datetime([row], 0)
    assert result.hour == 3
    assert result.minute == 0 and result.second == 0 and result.microsecond == 0


# ---------------------------------------------------------------------------
# matrix_charging_anchor
# ---------------------------------------------------------------------------

def test_matrix_charging_anchor_empty_matrix():
    assert cs.matrix_charging_anchor([]) is None


def test_matrix_charging_anchor_missing_key():
    assert cs.matrix_charging_anchor([{"hour": 0}]) is None


def test_matrix_charging_anchor_present():
    anchor = datetime(2026, 6, 1, 20, 15, 30)
    result = cs.matrix_charging_anchor([{"charging_anchor": anchor}])
    assert result == datetime(2026, 6, 1, 20, 0)


# ---------------------------------------------------------------------------
# parse_loxone_time_hm
# ---------------------------------------------------------------------------

def test_parse_loxone_time_hm_with_seconds():
    assert cs.parse_loxone_time_hm("07:30:15") == cs.time(hour=7, minute=30)


def test_parse_loxone_time_hm_invalid_returns_none():
    assert cs.parse_loxone_time_hm("not-a-time") is None


# ---------------------------------------------------------------------------
# parse_loxone_relative_ready_by
# ---------------------------------------------------------------------------

def test_parse_loxone_relative_ready_by_no_comma():
    from_dt = datetime(2026, 6, 22, 10, 0)
    assert cs.parse_loxone_relative_ready_by("Heute 23:30", from_dt) is None


def test_parse_loxone_relative_ready_by_invalid_clock():
    from_dt = datetime(2026, 6, 22, 10, 0)
    assert cs.parse_loxone_relative_ready_by("Heute, garbage", from_dt) is None


def test_parse_loxone_relative_ready_by_weekday_found():
    # 2026-06-22 ist ein Montag.
    from_dt = datetime(2026, 6, 22, 10, 0)
    result = cs.parse_loxone_relative_ready_by("Mittwoch, 12:30", from_dt)
    assert result == datetime(2026, 6, 24, 12, 30)


def test_parse_loxone_relative_ready_by_unknown_label():
    from_dt = datetime(2026, 6, 22, 10, 0)
    assert cs.parse_loxone_relative_ready_by("Irgendwas, 12:30", from_dt) is None


# ---------------------------------------------------------------------------
# _strip_short_weekday_prefix
# ---------------------------------------------------------------------------

def test_strip_short_weekday_prefix_no_comma():
    assert cs._strip_short_weekday_prefix("12:30") == "12:30"


def test_strip_short_weekday_prefix_full_weekday_kept():
    text = "Montag, 12:30"
    assert cs._strip_short_weekday_prefix(text) == text


def test_strip_short_weekday_prefix_heute_kept():
    text = "heute, 12:30"
    assert cs._strip_short_weekday_prefix(text) == text


def test_strip_short_weekday_prefix_short_legacy_prefix_stripped():
    assert cs._strip_short_weekday_prefix("Mo, 12:30") == "12:30"


def test_strip_short_weekday_prefix_long_non_weekday_kept():
    text = "Freizeit, 12:30"
    assert cs._strip_short_weekday_prefix(text) == text


# ---------------------------------------------------------------------------
# _parse_loxone_ready_by_text (via parse_loxone_ready_by_time)
# ---------------------------------------------------------------------------

def test_parse_ready_by_time_absolute_date_format():
    from_dt = datetime(2026, 6, 1, 0, 0)
    result = cs.parse_loxone_ready_by_time("17.08.2026 10:00", from_dt)
    assert result == datetime(2026, 8, 17, 10, 0)


def test_parse_ready_by_time_unparseable_text_returns_none():
    from_dt = datetime(2026, 6, 1, 0, 0)
    assert cs.parse_loxone_ready_by_time("total garbage", from_dt) is None


# ---------------------------------------------------------------------------
# _parse_loxone_ready_by_number (via parse_loxone_ready_by_time)
# ---------------------------------------------------------------------------

def test_parse_ready_by_number_unix_timestamp():
    from_dt = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    unix_ts = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc).timestamp()
    result = cs.parse_loxone_ready_by_time(unix_ts, from_dt)
    assert result == datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)


def test_parse_ready_by_number_fractional_hour_same_day():
    from_dt = datetime(2026, 6, 1, 5, 0)
    result = cs.parse_loxone_ready_by_time(6.5, from_dt)
    assert result == datetime(2026, 6, 1, 6, 30)


def test_parse_ready_by_number_legacy_hhmm_format():
    from_dt = datetime(2026, 6, 1, 5, 0)
    result = cs.parse_loxone_ready_by_time(630, from_dt)
    assert result == datetime(2026, 6, 1, 6, 30)


def test_parse_ready_by_number_out_of_range_returns_none():
    from_dt = datetime(2026, 6, 1, 5, 0)
    assert cs.parse_loxone_ready_by_time(50_000, from_dt) is None


def test_parse_ready_by_number_past_hour_rolls_to_next_day():
    from_dt = datetime(2026, 6, 1, 5, 0)
    result = cs.parse_loxone_ready_by_time(4.0, from_dt)
    assert result == datetime(2026, 6, 2, 4, 0)


# ---------------------------------------------------------------------------
# deadline_from_ready_hour
# ---------------------------------------------------------------------------

def test_deadline_from_ready_hour_none_ready_hour():
    horizon_start = datetime(2026, 6, 22, 10, 0)
    assert cs.deadline_from_ready_hour(horizon_start, None) is None


def test_deadline_from_ready_hour_next_occurrence():
    horizon_start = datetime(2026, 6, 22, 10, 0)
    assert cs.deadline_from_ready_hour(horizon_start, 7) == datetime(2026, 6, 23, 7, 0)


# ---------------------------------------------------------------------------
# _loxone_ready_raw
# ---------------------------------------------------------------------------

def test_loxone_ready_raw_without_configured_marker(monkeypatch):
    monkeypatch.setattr(cs, "marker_get_evcs_ready_by_time", lambda consumer: None)
    assert cs._loxone_ready_raw({"id": "eauto"}) is None


def test_loxone_ready_raw_fetches_via_loxone_client(monkeypatch):
    monkeypatch.setattr(cs, "marker_get_evcs_ready_by_time", lambda consumer: "Ernie_FertigUm")
    monkeypatch.setattr(
        cs.loxone_client, "fetch_loxone_ready_by_time", lambda io_name: "Morgen, 06:00"
    )
    assert cs._loxone_ready_raw({"id": "eauto"}) == "Morgen, 06:00"


# ---------------------------------------------------------------------------
# _window_start_for_day
# ---------------------------------------------------------------------------

def test_window_start_for_day_no_schedule_returns_none():
    consumer = {"charging_schedule": {}}
    assert cs._window_start_for_day(consumer, date(2026, 6, 22)) is None


def test_window_start_for_day_without_reference_returns_unaligned():
    consumer = {
        "charging_schedule": {"weekday": {"car_available_from_hour": 19}}
    }
    result = cs._window_start_for_day(consumer, date(2026, 6, 22))
    assert result == datetime(2026, 6, 22, 19, 0)


# ---------------------------------------------------------------------------
# next_scheduled_availability
# ---------------------------------------------------------------------------

def test_next_scheduled_availability_no_schedule_returns_none():
    consumer = {"charging_schedule": {}}
    horizon_start = datetime(2026, 6, 22, 10, 0)
    assert cs.next_scheduled_availability(horizon_start, consumer) is None


# ---------------------------------------------------------------------------
# hour_in_charging_window
# ---------------------------------------------------------------------------

def test_hour_in_charging_window_equal_bounds_always_true():
    assert cs.hour_in_charging_window(3, 19, 19) is True


def test_hour_in_charging_window_normal_range():
    assert cs.hour_in_charging_window(20, 19, 23) is True
    assert cs.hour_in_charging_window(18, 19, 23) is False
    assert cs.hour_in_charging_window(23, 19, 23) is False


def test_hour_in_charging_window_wraps_midnight():
    assert cs.hour_in_charging_window(2, 22, 6) is True
    assert cs.hour_in_charging_window(10, 22, 6) is False


# ---------------------------------------------------------------------------
# consumer_charging_eligible_indices
# ---------------------------------------------------------------------------

def _matrix(start: datetime, hours: int = 6) -> list:
    return [
        {"slot_datetime": start + timedelta(hours=i)}
        for i in range(hours)
    ]


def test_eligible_indices_empty_schedule_indices():
    matrix = _matrix(datetime(2026, 6, 22, 0, 0))
    assert cs.consumer_charging_eligible_indices(matrix, {}, []) == []


def test_eligible_indices_inactive_context_returns_empty():
    matrix = _matrix(datetime(2026, 6, 22, 0, 0))
    ctx = {"active": False}
    assert cs.consumer_charging_eligible_indices(matrix, {}, [0, 1, 2], ctx) == []


def test_eligible_indices_no_context_schedule_disabled_returns_all():
    matrix = _matrix(datetime(2026, 6, 22, 0, 0))
    consumer = {"charging_schedule": {"enabled": False}}
    indices = [0, 1, 2]
    assert cs.consumer_charging_eligible_indices(matrix, consumer, indices) == indices


def test_eligible_indices_computes_deadline_from_config_when_missing():
    horizon_start = datetime(2026, 6, 22, 0, 0)
    matrix = _matrix(horizon_start, hours=10)
    consumer = {
        "charging_schedule": {
            "enabled": True,
            "weekday": {"ready_by_hour": 3},
            "weekend": {"ready_by_hour": 3},
        }
    }
    # deadline wird aus consumer["charging_schedule"] berechnet (ctx={} -> kein "deadline").
    result = cs.consumer_charging_eligible_indices(matrix, consumer, list(range(10)), {})
    # Slots vor der berechneten Deadline (nächstes 03:00 nach horizon_start) sind eligible.
    assert result == [0, 1, 2]


def test_eligible_indices_time_window_without_bounds_is_true():
    horizon_start = datetime(2026, 6, 22, 5, 0)
    matrix = _matrix(horizon_start, hours=1)
    consumer = {"charging_schedule": {}}
    ctx = {"use_time_window": True, "config_day_schedule": {}}
    assert cs.consumer_charging_eligible_indices(matrix, consumer, [0], ctx) == [0]


# ---------------------------------------------------------------------------
# apply_charging_window_constraints
# ---------------------------------------------------------------------------

class _FakeConstraint:
    def __init__(self, var, value):
        self.var = var
        self.value = value

    def __eq__(self, other):
        return (
            isinstance(other, _FakeConstraint)
            and self.var == other.var
            and self.value == other.value
        )


class _FakeVar:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return _FakeConstraint(self.name, other)


class _FakeProb:
    def __init__(self):
        self.constraints: list = []

    def __iadd__(self, constraint):
        self.constraints.append(constraint)
        return self


def test_apply_charging_window_constraints_blocks_ineligible_slots():
    horizon_start = datetime(2026, 6, 22, 0, 0)
    matrix = _matrix(horizon_start, hours=4)
    consumer = {
        "id": "eauto",
        "charging_schedule": {
            "enabled": True,
            "weekday": {"ready_by_hour": 2},
            "weekend": {"ready_by_hour": 2},
        },
    }
    schedule_indices = [0, 1, 2, 3]
    consumer_on = {"eauto": [_FakeVar(f"on_{i}") for i in schedule_indices]}
    power_vars = {"eauto": [_FakeVar(f"pw_{i}") for i in schedule_indices]}
    pv_follow_vars = {"eauto": [_FakeVar(f"pv_{i}") for i in schedule_indices]}
    prob = _FakeProb()

    eligible = cs.apply_charging_window_constraints(
        prob,
        consumer_on,
        matrix,
        consumer,
        schedule_indices,
        charging_context={},
        consumer_power_vars=power_vars,
        consumer_pv_follow_vars=pv_follow_vars,
    )

    assert eligible == [0, 1]
    blocked = {2, 3}
    # Für jeden blockierten Slot: on==0, power==0, pv_follow==0 (3 Constraints je Slot).
    assert len(prob.constraints) == len(blocked) * 3
    blocked_on_names = {c.var for c in prob.constraints if c.var.startswith("on_")}
    assert blocked_on_names == {"on_2", "on_3"}


def test_apply_charging_window_constraints_without_optional_vars():
    horizon_start = datetime(2026, 6, 22, 0, 0)
    matrix = _matrix(horizon_start, hours=2)
    consumer = {
        "id": "eauto",
        "charging_schedule": {"enabled": False},
    }
    schedule_indices = [0, 1]
    consumer_on = {"eauto": [_FakeVar("on_0"), _FakeVar("on_1")]}
    prob = _FakeProb()

    eligible = cs.apply_charging_window_constraints(
        prob, consumer_on, matrix, consumer, schedule_indices
    )

    # Schedule ist deaktiviert -> alle Slots eligible, keine Constraints.
    assert eligible == schedule_indices
    assert prob.constraints == []


# ---------------------------------------------------------------------------
# schedule_indices_for_consumer
# ---------------------------------------------------------------------------

def test_schedule_indices_for_consumer_inactive_returns_default():
    matrix = _matrix(datetime(2026, 6, 22, 0, 0))
    default_indices = [0, 1, 2, 3, 4, 5]
    result = cs.schedule_indices_for_consumer(
        matrix, 6, default_indices, {}, {"active": False, "deadline": datetime(2026, 6, 22, 3, 0)}
    )
    assert result == default_indices


def test_schedule_indices_for_consumer_no_deadline_returns_default():
    matrix = _matrix(datetime(2026, 6, 22, 0, 0))
    default_indices = [0, 1, 2, 3, 4, 5]
    result = cs.schedule_indices_for_consumer(matrix, 6, default_indices, {}, None)
    assert result == default_indices


def test_schedule_indices_for_consumer_uses_deadline_when_active():
    horizon_start = datetime(2026, 6, 22, 0, 0)
    matrix = _matrix(horizon_start, hours=6)
    default_indices = [0, 1, 2, 3, 4, 5]
    deadline = datetime(2026, 6, 22, 3, 0)
    result = cs.schedule_indices_for_consumer(
        matrix, 6, default_indices, {}, {"active": True, "deadline": deadline}
    )
    assert result == [0, 1, 2]
