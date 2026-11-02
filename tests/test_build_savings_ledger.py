"""Ledger P6: backfill CLI ``scripts.build_savings_ledger``."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from scripts import build_savings_ledger as cli

BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 1.0,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}
ARCHIVE = "optimization_history.jsonl.2026-11-01_00-00-07"


def _day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr("config.get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr("config.get_battery_params_list", lambda: [dict(BATTERY)])
    monkeypatch.setattr(store, "sunrise_day_bounds", lambda *_a: _day_bounds)


def _entry(completed: datetime) -> dict:
    """Log entry of the cycle at ``completed``: prices for its slot, the previous slot closed."""
    closed_start = completed.replace(second=0) - timedelta(minutes=15)
    return {
        "completed_at": completed.isoformat(),
        "market_price_cent": 30.0,
        "epex_price_cent": 10.0,
        "k_push_act": 8.0,
        "delivery_compliance": {"wp": {"planned_kw": 0.4}},
        "forecast_pv_kw": 1.0,
        "closed_interval": {
            "interval_start": closed_start.isoformat(),
            "sample_count": 30,
            "pv_kw": 0.0,
            "grid_kw": 1.0,
            "battery_kw": 0.0,
            "house_kw": 1.0,
            "soc_start_percent": 50.0,
            "soc_end_percent": 50.0,
            "flex_kw": {},
            "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
        },
    }


def _write_history(runtime, start: datetime, end: datetime) -> None:
    """One entry per quarter hour; entries before 2026-11-01 go to the rotated month file."""
    archive, active = [], []
    moment = start
    while moment < end:
        entry = _entry(moment + timedelta(seconds=2))
        (archive if moment < datetime(2026, 11, 1) else active).append(json.dumps(entry))
        moment += timedelta(minutes=15)
    (runtime / ARCHIVE).write_text("\n".join(archive) + "\n", encoding="utf-8")
    (runtime / "optimization_history.jsonl").write_text("\n".join(active) + "\n", encoding="utf-8")


def _run(runtime, *args: str) -> int:
    return cli.main(["--since", "2026-10-31", "--runtime-dir", str(runtime), *args])


def test_backfill_replays_the_month_files_and_writes_rows_and_state(env, tmp_path, capsys):
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))

    assert _run(tmp_path) == 0

    rows = store.read_rows(str(tmp_path / cli.LEDGER_FILENAME))
    # chain from 2026-10-31 00:00: SA-days ending 31.10. 07:00, 1.11. 07:00 and 2.11. 07:00
    assert [r["day_end"][:16] for r in rows] == [
        "2026-10-31T07:00",
        "2026-11-01T07:00",
        "2026-11-02T07:00",
    ]
    assert rows[0]["chain_start"].startswith("2026-10-31T00:00")
    assert rows[0]["chain_start_reason"] == sl.CHAIN_BACKFILL
    # the day across the month rotation is complete: 96 slots, all priced
    assert rows[1]["slots_present"] == 96
    assert rows[1]["coverage"] == 1.0
    assert rows[1]["cost_with_eur"] == pytest.approx(96 * 0.25 * 0.30)

    state = store.load_state(str(tmp_path / cli.STATE_FILENAME)).state
    assert state.chain_start_reason == sl.CHAIN_BACKFILL
    assert state.day_start.isoformat().startswith("2026-11-02T07:00")
    # the newest entry's slot (08:45) keeps its prices for the daemon
    assert state.pending_slot["slot_start"].startswith("2026-11-02T08:45")

    out = capsys.readouterr().out
    assert "2 log file(s)" in out
    assert "2026-10-31" in out and "total" in out


def test_existing_ledger_is_not_replaced_without_rebuild(env, tmp_path, capsys):
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    ledger = tmp_path / cli.LEDGER_FILENAME
    ledger.write_text('{"live": true}\n', encoding="utf-8")

    assert _run(tmp_path) == 2
    assert ledger.read_text(encoding="utf-8") == '{"live": true}\n'
    assert not (tmp_path / cli.STATE_FILENAME).exists()
    assert "--rebuild" in capsys.readouterr().err

    assert _run(tmp_path, "--rebuild") == 0
    assert len(store.read_rows(str(ledger))) == 3


def test_existing_state_alone_also_blocks_writing(env, tmp_path):
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    (tmp_path / cli.STATE_FILENAME).write_text("{}", encoding="utf-8")

    assert _run(tmp_path) == 2
    assert not (tmp_path / cli.LEDGER_FILENAME).exists()


def test_dry_run_prints_the_table_and_writes_nothing(env, tmp_path, capsys):
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    (tmp_path / cli.LEDGER_FILENAME).write_text('{"live": true}\n', encoding="utf-8")

    assert _run(tmp_path, "--dry-run") == 0

    assert (tmp_path / cli.LEDGER_FILENAME).read_text(encoding="utf-8") == '{"live": true}\n'
    assert not (tmp_path / cli.STATE_FILENAME).exists()
    out = capsys.readouterr().out
    assert "dry run: nothing written" in out
    assert "2026-11-01" in out


def test_malformed_log_line_is_reported(env, tmp_path, capsys):
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    with open(tmp_path / ARCHIVE, "a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert _run(tmp_path, "--dry-run") == 0

    captured = capsys.readouterr()
    assert "1 malformed line(s)" in captured.out
    assert f"{ARCHIVE}:" in captured.err


def test_without_history_or_battery_the_cli_fails(env, tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, "--dry-run") == 1
    assert "No optimization_history.jsonl" in capsys.readouterr().err

    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [])
    assert _run(tmp_path, "--dry-run") == 1
    assert "No house battery" in capsys.readouterr().err
