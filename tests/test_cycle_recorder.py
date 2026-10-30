"""Regression R-Rec: cycle recorder unit + capture-point acceptance."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

import config
from runtime_store import cycle_recorder
from runtime_store.debug_dump_archive import write_debug_dump_zip
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree


def _cfg(tmp_path, monkeypatch, *, local: dict | None = None):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(),
    )
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(
        json.dumps(local or {"silent_mode": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("EARNIE_CONFIG_PATH", config_path)
    monkeypatch.setenv("EARNIE_BACKTESTING_SCENARIOS_PATH", scenarios_path)
    monkeypatch.setenv("EARNIE_LOCAL_SETTINGS_PATH", str(local_path))
    config.reinit_config()
    cycle_recorder.reset_for_tests()


def _sample_matrix(n: int = 4) -> list[dict]:
    base = datetime(2026, 7, 16, 10, 0, 0)
    rows: list[dict] = []
    for index in range(n):
        slot = base + timedelta(minutes=15 * index)
        rows.append(
            {
                "slot_datetime": slot,
                "hour": slot.hour,
                "expected_p_pv": 1.5 + index * 0.1,
                "expected_p_act": 0.8,
                "k_act": 12.0 + index,
                "price_buy": 10.0,
            }
        )
    return rows


def _sample_window() -> dict:
    return {
        "start": "2026-07-16T10:00:00",
        "end": "2026-07-17T10:00:00",
        "sunset_1": "2026-07-16T20:00:00",
        "sunset_2": "2026-07-17T20:00:00",
        "sunrise_anchor": "2026-07-17T05:30:00",
        "slot_datetimes": [],
        "timezone_name": "Europe/Vienna",
        "latitude": 48.0,
        "longitude": 16.0,
        "horizon_hours": 24,
    }


def test_matrix_columnar_roundtrip():
    matrix = _sample_matrix(3)
    columnar = cycle_recorder.matrix_to_columnar(matrix)
    restored = cycle_recorder.columnar_to_matrix(columnar)
    assert len(restored) == 3
    assert restored[0]["expected_p_pv"] == pytest.approx(1.5)
    assert restored[1]["k_act"] == pytest.approx(13.0)
    assert restored[2]["slot_datetime"] == "2026-07-16T10:30:00"


def test_finish_stores_outdoor_forecast_fetched_during_the_cycle(tmp_path, monkeypatch):
    from data import outdoor_forecast as of

    _cfg(tmp_path, monkeypatch)
    token = cycle_recorder.begin_cycle(
        optimization_matrix=_sample_matrix(),
        planning_window=_sample_window(),
        soc_percent=50.0,
        timestamp=datetime(2026, 10, 28, 9, 44, 52),
    )
    with patch.object(of, "get_hourly_outdoor_forecast_c", return_value=[4.4, 5.9, 11.7]):
        of.get_outdoor_forecast_with_fallback(horizon=3, fallback_ambient_c=10.4)
    cycle_recorder.finish_cycle(token, mode=2, target_power_kw=0.0, battery_plan_kw=0.0)
    entry = cycle_recorder.read_segment_cycles(
        cycle_recorder.segment_path_for_day(datetime(2026, 10, 28).date())
    )[0]
    assert entry["start_state"]["outdoor_forecast"] == {
        "values_c": [4.4, 5.9, 11.7],
        "source": "open_meteo",
    }


def test_begin_finish_writes_gzip_jsonl(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    matrix = _sample_matrix()
    now = datetime.now().replace(microsecond=0)
    token = cycle_recorder.begin_cycle(
        optimization_matrix=matrix,
        planning_window=_sample_window(),
        soc_percent=55.0,
        timestamp=now,
    )
    assert token is not None
    ok = cycle_recorder.finish_cycle(
        token,
        mode=1,
        target_power_kw=2.5,
        battery_plan_kw=-1.0,
        consumer_powers_kw={"eauto": 3.68},
        flags={"override": False, "immediate_charging": False, "outage": False, "manual_intervention": False},
    )
    assert ok is True
    segment = cycle_recorder.segment_path_for_day(now.date())
    assert segment.is_file()
    cycles = cycle_recorder.read_segment_cycles(segment)
    assert len(cycles) == 1
    entry = cycles[0]
    assert entry["config_hash"]
    assert entry["optimization_matrix"]["n_rows"] == 4
    assert entry["outputs"]["plan_hash"]
    assert (cycle_recorder.configs_dir() / f"{entry['config_hash']}.json").is_file()


def test_disabled_writes_nothing(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, local={"recorder_enabled": False})
    token = cycle_recorder.begin_cycle(
        optimization_matrix=_sample_matrix(),
        planning_window=_sample_window(),
        soc_percent=40.0,
    )
    assert token is None
    assert list(cycle_recorder.list_segment_paths()) == []


def test_retention_prunes_old_segments(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, local={"recorder_retention_days": 2})
    root = cycle_recorder.recorder_dir()
    root.mkdir(parents=True)
    old_day = date.today() - timedelta(days=5)
    keep_day = date.today()
    old_path = root / f"cycles_{old_day.isoformat()}.jsonl.gz"
    keep_path = root / f"cycles_{keep_day.isoformat()}.jsonl.gz"
    for path in (old_path, keep_path):
        import gzip

        with gzip.open(path, "wb") as handle:
            handle.write(b'{"schema":1}\n')
    removed = cycle_recorder.prune_old_segments(keep_days=2)
    assert old_path in removed
    assert not old_path.exists()
    assert keep_path.is_file()


def test_soft_fail_increments_lost_counter(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    before = cycle_recorder.lost_cycle_count()
    with patch.object(
        cycle_recorder,
        "compute_config_hash",
        side_effect=OSError("boom"),
    ):
        token = cycle_recorder.begin_cycle(
            optimization_matrix=_sample_matrix(),
            planning_window=_sample_window(),
            soc_percent=10.0,
        )
    assert token is None
    assert cycle_recorder.lost_cycle_count() == before + 1


def test_config_snapshot_deduped(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    matrix = _sample_matrix(2)
    window = _sample_window()
    t1 = cycle_recorder.begin_cycle(
        optimization_matrix=matrix, planning_window=window, soc_percent=1.0
    )
    cycle_recorder.finish_cycle(t1, mode=0, target_power_kw=0.0)
    configs = list(cycle_recorder.configs_dir().glob("*.json"))
    assert len(configs) == 1
    t2 = cycle_recorder.begin_cycle(
        optimization_matrix=matrix, planning_window=window, soc_percent=2.0
    )
    cycle_recorder.finish_cycle(t2, mode=1, target_power_kw=1.0)
    assert len(list(cycle_recorder.configs_dir().glob("*.json"))) == 1


def test_debug_dump_includes_recorder_window(tmp_path, monkeypatch):
    _cfg(
        tmp_path,
        monkeypatch,
        local={
            "silent_mode": False,
            "chart_debug_capture_enabled": True,
        },
    )
    monkeypatch.setenv("EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED", "1")
    # Re-apply dump-friendly ui via config tree already written; ensure history exists.
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "optimization_history.jsonl").write_text(
        '{"written_at":"2026-07-16T08:00:00"}\n',
        encoding="utf-8",
    )
    config.reinit_config()
    now = datetime.now().replace(microsecond=0)
    token = cycle_recorder.begin_cycle(
        optimization_matrix=_sample_matrix(),
        planning_window=_sample_window(),
        soc_percent=50.0,
        timestamp=now,
    )
    cycle_recorder.finish_cycle(
        token, mode=1, target_power_kw=1.0, battery_plan_kw=0.0, consumer_powers_kw={}
    )
    zip_path = write_debug_dump_zip(
        title="rec",
        symptom="with recorder",
        captured_at=now,
    )
    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert any(name.startswith("recorder/cycles_") for name in names)
        assert any(name.startswith("recorder/configs/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["schema_version"] == 3
    assert manifest["recorder"]["cycle_count"] == 1
    assert manifest["recorder"]["config_hashes"]


def test_capture_point_record_replay_prepare_equal(tmp_path, monkeypatch):
    """Acceptance: recorded pre-prepare matrix → prepare equals live prepare."""
    _cfg(tmp_path, monkeypatch)
    from optimizer.charge_immediate import prepare_optimization_matrix

    live_matrix = _sample_matrix(8)
    consumers = [
        {
            "id": "eauto",
            "name": "E-Auto",
            "nominal_power_kw": 3.68,
            "min_power_kw": 1.4,
            "type": "ev",
        }
    ]
    targets = {"eauto": 5.0}

    now = datetime.now().replace(microsecond=0)
    token = cycle_recorder.begin_cycle(
        optimization_matrix=live_matrix,
        planning_window=_sample_window(),
        soc_percent=60.0,
        targets=targets,
        timestamp=now,
    )
    prepared_live, contexts_live, targets_live = prepare_optimization_matrix(
        [dict(row) for row in live_matrix],
        dict(targets),
        consumers=consumers,
    )
    plan_live = cycle_recorder.compute_plan_hash(
        mode=1,
        target_power_kw=2.0,
        battery_plan_kw=0.5,
        consumer_powers_kw={"eauto": 3.68},
    )
    cycle_recorder.finish_cycle(
        token,
        mode=1,
        target_power_kw=2.0,
        battery_plan_kw=0.5,
        consumer_powers_kw={"eauto": 3.68},
        plan_hash=plan_live,
    )

    segment = cycle_recorder.segment_path_for_day(now.date())
    recorded = cycle_recorder.read_segment_cycles(segment)[0]
    restored_matrix = cycle_recorder.columnar_to_matrix(recorded["optimization_matrix"])
    # slot_datetime comes back as ISO string; prepare tolerates via charging resolve —
    # normalize to datetime for a fair compare of prepare outputs.
    for row in restored_matrix:
        raw = row.get("slot_datetime")
        if isinstance(raw, str):
            row["slot_datetime"] = datetime.fromisoformat(raw)

    prepared_replay, contexts_replay, targets_replay = prepare_optimization_matrix(
        restored_matrix,
        dict(recorded["start_state"].get("targets") or targets),
        consumers=consumers,
    )
    assert targets_replay == targets_live
    assert set(contexts_replay) == set(contexts_live)
    assert len(prepared_replay) == len(prepared_live)
    for left, right in zip(prepared_replay, prepared_live):
        assert left["expected_p_pv"] == pytest.approx(float(right["expected_p_pv"]))
        assert left["expected_p_act"] == pytest.approx(float(right["expected_p_act"]))
        assert left["k_act"] == pytest.approx(float(right["k_act"]))
    assert recorded["outputs"]["plan_hash"] == plan_live
