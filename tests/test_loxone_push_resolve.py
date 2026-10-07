"""Zero rule + 5 min last-known for the push-only read path."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime_store import loxone_push_inbox as inbox


def _now() -> datetime:
    return datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def _row(value: float | None, age_s: float, *, parse_ok: bool = True) -> dict:
    last = _now() - timedelta(seconds=age_s)
    return {
        "value": value,
        "raw": str(value),
        "parse_ok": parse_ok,
        "last_ts": last.isoformat(),
        "count": 3,
    }


def _resolve(ehal_id, row, *, link, last=None, max_s=300.0):
    return inbox.resolve_push_read(
        ehal_id,
        row,
        link=link,
        now=_now(),
        last_known=last,
        last_known_max_s=max_s,
        repeat_s=10.0,
    )


def test_power_silence_link_alive_assumes_zero() -> None:
    state, value = _resolve("sens_grid_power_active", _row(1.2, 40), link=True)
    assert (state, value) == (inbox.STATE_ZERO_ASSUMED_SILENT, 0.0)


def test_power_silence_link_dead_uses_last_known_then_error() -> None:
    held = (1.2, _now() - timedelta(seconds=60))
    state, value = _resolve(
        "sens_grid_power_active", _row(1.2, 40), link=False, last=held
    )
    assert (state, value) == (inbox.STATE_LAST_KNOWN, 1.2)
    held_old = (1.2, _now() - timedelta(seconds=400))
    state, value = _resolve(
        "sens_grid_power_active", _row(1.2, 40), link=False, last=held_old
    )
    assert (state, value) == (inbox.STATE_READ_ERROR, None)


def test_digital_holds_and_never_sent_is_zero_when_link_alive() -> None:
    state, value = _resolve("sens_evcs_connected", _row(1.0, 900), link=True)
    assert (state, value) == (inbox.STATE_DIGITAL_HELD, 1.0)
    state, value = _resolve("sens_absent_mode", None, link=True)
    assert (state, value) == (inbox.STATE_ZERO_ASSUMED_NEVER, 0.0)


def test_soc_never_assumes_zero_uses_last_known() -> None:
    held = (55.0, _now() - timedelta(seconds=60))
    state, value = _resolve("sens_ess_soc", _row(55.0, 40), link=True, last=held)
    assert (state, value) == (inbox.STATE_LAST_KNOWN, 55.0)
    state, value = _resolve("sens_ess_soc", None, link=True, last=None)
    assert (state, value) == (inbox.STATE_READ_ERROR, None)


def test_temperature_stale_last_known_window() -> None:
    held = (42.0, _now() - timedelta(minutes=4))
    state, value = _resolve(
        "heatpump.wp.sens_temperature_heat_storage",
        _row(42.0, 60),
        link=True,
        last=held,
    )
    assert (state, value) == (inbox.STATE_LAST_KNOWN, 42.0)
    held_old = (42.0, _now() - timedelta(minutes=6))
    state, value = _resolve(
        "heatpump.wp.sens_temperature_heat_storage",
        _row(42.0, 60),
        link=True,
        last=held_old,
    )
    assert (state, value) == (inbox.STATE_READ_ERROR, None)


def test_fresh_ok() -> None:
    assert _resolve("sens_ess_soc", _row(61.0, 5), link=True) == (inbox.STATE_OK, 61.0)


def test_read_push_value_uses_memory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    t0 = _now()
    inbox.record_push("heartbeat", "1", now=t0)
    inbox.record_push("sens_grid_power_active", "0.8", now=t0)
    value, state = inbox.read_push_value("sens_grid_power_active", now=t0 + timedelta(seconds=5))
    assert (value, state) == (0.8, inbox.STATE_OK)
    # Keep heartbeat fresh so the link stays alive while the power signal goes silent.
    inbox.record_push("heartbeat", "1", now=t0 + timedelta(seconds=40))
    value, state = inbox.read_push_value(
        "sens_grid_power_active", now=t0 + timedelta(seconds=40)
    )
    assert (value, state) == (0.0, inbox.STATE_ZERO_ASSUMED_SILENT)
