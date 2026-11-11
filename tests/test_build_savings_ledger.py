"""Ledger P6: backfill CLI ``scripts.build_savings_ledger``."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_daemon as hook
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


def _history(runtime) -> None:
    _write_history(runtime, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))


def test_backfill_writes_slots_that_add_up_to_every_row(env, tmp_path):
    _history(tmp_path)

    assert _run(tmp_path) == 0

    rows = store.read_rows(str(tmp_path / cli.LEDGER_FILENAME))
    slots = store.closed_day_slots(rows, str(tmp_path / cli.SLOTS_FILENAME))
    assert list(slots) == [r["day_start"] for r in rows]
    assert len(slots[rows[1]["day_start"]]) == 96
    assert slots[rows[1]["day_start"]][0]["house_kwh"] == pytest.approx(0.25)


def test_backfill_and_daemon_write_the_same_rows(env, tmp_path, monkeypatch):
    backfill = tmp_path / "backfill"
    backfill.mkdir()
    _history(backfill)
    assert _run(backfill) == 0

    live = tmp_path / "live"
    monkeypatch.setattr(store, "savings_ledger_file", lambda: str(live / cli.LEDGER_FILENAME))
    monkeypatch.setattr(store, "savings_ledger_slots_file", lambda: str(live / cli.SLOTS_FILENAME))
    monkeypatch.setattr(store, "savings_ledger_state_file", lambda: str(live / cli.STATE_FILENAME))
    hook.reset()
    try:
        entries = []
        for path in (backfill / ARCHIVE, backfill / "optimization_history.jsonl"):
            entries += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        since = datetime(2026, 10, 31)
        for entry in entries:
            completed = datetime.fromisoformat(entry["completed_at"])
            if completed < since:
                continue
            # the replay starts with the slot from --since, so must the daemon
            closed = entry["closed_interval"] if completed >= since + timedelta(minutes=15) else None
            hook.on_cycle(closed, entry, now=completed)
    finally:
        hook.reset()

    live_slots = (live / cli.SLOTS_FILENAME).read_text(encoding="utf-8")
    assert live_slots
    assert live_slots == (backfill / cli.SLOTS_FILENAME).read_text(encoding="utf-8")
    drop_reason = lambda rows: [{k: v for k, v in r.items() if k != "chain_start_reason"} for r in rows]  # noqa: E731
    assert drop_reason(store.read_rows(str(live / cli.LEDGER_FILENAME))) == drop_reason(
        store.read_rows(str(backfill / cli.LEDGER_FILENAME))
    )


def test_existing_slot_file_alone_also_blocks_writing(env, tmp_path):
    _history(tmp_path)
    (tmp_path / cli.SLOTS_FILENAME).write_text("{}\n", encoding="utf-8")

    assert _run(tmp_path) == 2
    assert not (tmp_path / cli.LEDGER_FILENAME).exists()


def test_slots_only_covers_old_days_and_leaves_ledger_and_state_alone(env, tmp_path, capsys):
    _history(tmp_path)
    assert _run(tmp_path) == 0
    ledger = tmp_path / cli.LEDGER_FILENAME
    state = tmp_path / cli.STATE_FILENAME
    slots = tmp_path / cli.SLOTS_FILENAME
    before = ledger.read_bytes(), state.read_bytes(), slots.read_text(encoding="utf-8")
    slots.unlink()

    assert _run(tmp_path, "--slots-only") == 0

    assert (ledger.read_bytes(), state.read_bytes()) == before[:2]
    assert slots.read_text(encoding="utf-8") == before[2]
    assert "replay matches all 3 ledger rows" in capsys.readouterr().out


def test_slots_only_repairs_a_broken_slot_file(env, tmp_path):
    _history(tmp_path)
    assert _run(tmp_path) == 0
    slots = tmp_path / cli.SLOTS_FILENAME
    slots.write_text("{broken\n", encoding="utf-8")

    assert _run(tmp_path, "--slots-only") == 0

    rows = store.read_rows(str(tmp_path / cli.LEDGER_FILENAME))
    assert len(store.closed_day_slots(rows, str(slots))) == 3


def test_slots_only_refuses_a_replay_that_differs_from_the_ledger(env, tmp_path, capsys):
    _history(tmp_path)
    assert _run(tmp_path) == 0
    ledger = tmp_path / cli.LEDGER_FILENAME
    slots = tmp_path / cli.SLOTS_FILENAME
    rows = store.read_rows(str(ledger))
    rows[1]["cost_with_eur"] += 1.0
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    slots.unlink()

    assert _run(tmp_path, "--slots-only") == 1

    assert not slots.exists()
    assert "Slot file not written" in capsys.readouterr().err


def test_slots_only_refuses_days_the_ledger_does_not_have(env, tmp_path, capsys):
    _history(tmp_path)
    assert _run(tmp_path) == 0
    ledger = tmp_path / cli.LEDGER_FILENAME
    slots = tmp_path / cli.SLOTS_FILENAME
    rows = store.read_rows(str(ledger))
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows[:-1]), encoding="utf-8")
    slots.unlink()

    assert _run(tmp_path, "--slots-only") == 1

    assert not slots.exists()
    assert "does not have" in capsys.readouterr().err


def test_slots_only_refuses_without_a_ledger(env, tmp_path, capsys):
    _history(tmp_path)

    assert _run(tmp_path, "--slots-only") == 1

    assert not (tmp_path / cli.SLOTS_FILENAME).exists()
    assert "no ledger rows" in capsys.readouterr().err


def test_slots_only_dry_run_checks_and_writes_nothing(env, tmp_path, capsys):
    _history(tmp_path)
    assert _run(tmp_path) == 0
    slots = tmp_path / cli.SLOTS_FILENAME
    slots.unlink()

    assert _run(tmp_path, "--slots-only", "--dry-run") == 0

    assert not slots.exists()
    out = capsys.readouterr().out
    assert "replay matches all 3 ledger rows" in out
    assert "dry run: nothing written" in out


def test_slots_only_cannot_be_combined_with_rebuild(env, tmp_path):
    with pytest.raises(SystemExit):
        _run(tmp_path, "--slots-only", "--rebuild")


def test_slots_only_refuses_while_the_daemon_runs(env, tmp_path, monkeypatch, capsys):
    _history(tmp_path)
    monkeypatch.setattr(cli, "_daemon_running", lambda _dir: True)

    assert _run(tmp_path, "--slots-only") == 2

    assert not (tmp_path / cli.SLOTS_FILENAME).exists()
    assert "stop it" in capsys.readouterr().err


def test_malformed_log_line_is_reported(env, tmp_path, capsys):
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    with open(tmp_path / ARCHIVE, "a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert _run(tmp_path, "--dry-run") == 0

    captured = capsys.readouterr()
    assert "1 malformed line(s)" in captured.out
    assert f"{ARCHIVE}:" in captured.err


def test_without_history_the_cli_fails_and_without_battery_it_runs(env, tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, "--dry-run") == 1
    assert "No optimization_history.jsonl" in capsys.readouterr().err

    # D3 (savings_v 2): a house without battery has a ledger too
    _write_history(tmp_path, datetime(2026, 10, 30, 12, 0), datetime(2026, 11, 2, 9, 0))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [])
    assert _run(tmp_path, "--dry-run") == 0
    assert "no house battery" in capsys.readouterr().out
