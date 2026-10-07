"""Monthly rotation for optimization_history.jsonl."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from runtime_store import optimization_history
from runtime_store.month_file_rotation import (
    DEFAULT_BACKUP_COUNT,
    compute_next_month_rollover,
    list_rotated_siblings,
    prune_archives,
)


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    hist = tmp_path / "optimization_history.jsonl"
    monkeypatch.setattr(optimization_history, "HISTORY_FILE", str(hist))
    monkeypatch.setattr(optimization_history, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(optimization_history, "_ROLLOVER_AT", None)
    optimization_history._clear_jsonl_history_cache()
    yield
    optimization_history._clear_jsonl_history_cache()
    monkeypatch.setattr(optimization_history, "_ROLLOVER_AT", None)


def _entry(completed_at: str, soc: float = 50.0) -> dict:
    return {
        "completed_at": completed_at,
        "written_at": completed_at,
        "source": "main.py",
        "run_trigger": "quarter_hour",
        "soc_percent": soc,
        "mode": 0,
        "target_power_kw": 0.0,
        "target_soc_percent": 50.0,
        "market_price_cent": 10.0,
        "forecast_pv_kw": 0.0,
        "forecast_consumption_kw": 1.0,
        "battery_plan_kw": 0.0,
        "consumer_powers_kw": {},
    }


def test_compute_next_month_rollover_day_one() -> None:
    mid = time.mktime((2026, 3, 20, 8, 0, 0, -1, -1, -1))
    next_at = compute_next_month_rollover(mid)
    lt = time.localtime(next_at)
    assert (lt.tm_year, lt.tm_mon, lt.tm_mday) == (2026, 4, 1)
    assert (lt.tm_hour, lt.tm_min, lt.tm_sec) == (0, 0, 0)


def test_forced_month_rollover_archives_active(tmp_path: Path) -> None:
    path = Path(optimization_history.HISTORY_FILE)
    path.write_text(
        json.dumps(_entry("2026-01-15T12:00:00")) + "\n",
        encoding="utf-8",
    )
    optimization_history._ROLLOVER_AT = 1.0
    optimization_history.append_production_run(_entry("2026-02-01T00:15:00", soc=55.0))

    archives = list_rotated_siblings(str(path))
    assert len(archives) == 1
    archived = Path(archives[0]).read_text(encoding="utf-8")
    assert "2026-01-15T12:00:00" in archived
    active = path.read_text(encoding="utf-8")
    assert "2026-02-01T00:15:00" in active
    assert "2026-01-15T12:00:00" not in active


def test_large_file_does_not_rotate_before_month(tmp_path: Path) -> None:
    path = Path(optimization_history.HISTORY_FILE)
    big = (json.dumps(_entry("2026-05-01T10:00:00")) + "\n") * 200
    path.write_text(big, encoding="utf-8")
    size_before = path.stat().st_size
    assert size_before > 5000
    optimization_history._ROLLOVER_AT = time.time() + 86400
    optimization_history.append_production_run(_entry("2026-05-01T11:00:00", soc=60.0))
    assert not list_rotated_siblings(str(path))
    assert path.stat().st_size > size_before


def test_backup_count_twelve_prunes_oldest(tmp_path: Path) -> None:
    path = Path(optimization_history.HISTORY_FILE)
    for i in range(13):
        year = 2025 + (i // 12)
        month = (i % 12) + 1
        stamp = f"{year}-{month:02d}-01_00-00-00"
        (tmp_path / f"optimization_history.jsonl.{stamp}").write_text(
            json.dumps(_entry(f"{year}-{month:02d}-15T12:00:00")) + "\n",
            encoding="utf-8",
        )
    path.write_text(json.dumps(_entry("2026-02-01T12:00:00")) + "\n", encoding="utf-8")
    prune_archives(str(path), DEFAULT_BACKUP_COUNT)
    assert len(list_rotated_siblings(str(path))) == 12


def test_load_merges_active_and_archives(tmp_path: Path) -> None:
    path = Path(optimization_history.HISTORY_FILE)
    archive = tmp_path / "optimization_history.jsonl.2026-01-01_00-00-00"
    archive.write_text(
        json.dumps(_entry("2026-01-10T12:00:00", soc=40.0)) + "\n",
        encoding="utf-8",
    )
    path.write_text(
        json.dumps(_entry("2026-02-10T12:00:00", soc=70.0)) + "\n",
        encoding="utf-8",
    )
    rows = optimization_history._load_jsonl_history()
    socs = [row["soc_percent"] for row in rows]
    assert 40.0 in socs
    assert 70.0 in socs

    entries = optimization_history.load_replay_entries_between(
        datetime(2026, 1, 1),
        datetime(2026, 3, 1),
    )
    assert len(entries) == 2


def test_append_after_rollover_invalidates_cache(tmp_path: Path) -> None:
    path = Path(optimization_history.HISTORY_FILE)
    path.write_text(
        json.dumps(_entry("2026-01-01T12:00:00", soc=10.0)) + "\n",
        encoding="utf-8",
    )
    first = optimization_history._load_jsonl_history()
    assert len(first) == 1
    optimization_history._ROLLOVER_AT = 1.0
    optimization_history.append_production_run(_entry("2026-02-01T12:00:00", soc=20.0))
    merged = optimization_history._load_jsonl_history()
    socs = sorted(row["soc_percent"] for row in merged)
    assert socs == [10.0, 20.0]
