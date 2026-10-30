"""ConfigMigration P2 — startup gate (no silent live migrate; refuse / migration mode)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from runtime_store import bootstrap, main_daemon
from runtime_store.config_load import load_config_or_exit
from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY
from runtime_store.migration.gate import (
    abort_message_de,
    migration_blocks_normal_startup,
    model_range_label_de,
    plan_for_active_config,
)
from runtime_store.migration.types import MigrationPlan
from runtime_store.migration.planner import plan_migration
from runtime_store.shadow.errors import ShadowStartupError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "migration"
GOLDENS = FIXTURES / "goldens"


def _point_config(monkeypatch, config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(config_dir.parent / "runtime"))
    for suffix in (
        "COMPONENTS_PATH",
        "TARIFFS_PATH",
        "HOUSE_PROFILES_PATH",
        "BACKTESTING_SCENARIOS_PATH",
        "DEVIATION_RULES_PATH",
        "GRID_FEES_PATH",
    ):
        monkeypatch.delenv(f"EARNIE_{suffix}", raising=False)


def _copy_snapshot(tmp_path: Path, name: str, *, from_goldens: bool = False) -> Path:
    src = (GOLDENS if from_goldens else FIXTURES) / name
    dest = tmp_path / "config"
    shutil.copytree(src, dest)
    return dest


def test_pending_v3_blocks_load_config_and_daemon(tmp_path, monkeypatch, capsys):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    _point_config(monkeypatch, config_dir)
    plan = plan_for_active_config()
    assert migration_blocks_normal_startup(plan)
    assert plan.pending_step_ids

    with pytest.raises(SystemExit) as exc:
        load_config_or_exit()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "migriert" in err.lower() or "Migration" in err
    assert "migrate_config" in err

    with pytest.raises(main_daemon.DaemonError, match="migrate_config"):
        main_daemon.start()


def test_bootstrap_does_not_mutate_pending_live_pack(tmp_path, monkeypatch):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    _point_config(monkeypatch, config_dir)
    before = {
        p.name: json.loads(p.read_text(encoding="utf-8"))
        for p in config_dir.iterdir()
        if p.is_file() and p.suffix == ".json"
    }
    bootstrap.run()
    after = {
        p.name: json.loads(p.read_text(encoding="utf-8"))
        for p in config_dir.iterdir()
        if p.is_file() and p.suffix == ".json"
    }
    for name, doc in before.items():
        assert after[name] == doc
        assert after[name].get(DATA_MODEL_KEY) == doc.get(DATA_MODEL_KEY)


def test_untagged_earnie_file_blocks_grid_fees_exempt(tmp_path, monkeypatch, capsys):
    config_dir = tmp_path / "config"
    _point_config(monkeypatch, config_dir)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                DATA_MODEL_KEY: CURRENT_DATA_MODEL,
                "live_scenario_id": "live",
                "scenario_explorer_conf": {"path_cons_data": "runtime/x.csv"},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        json.dumps({"batteries": [], "pv_systems": []}),
        encoding="utf-8",
    )
    (config_dir / "grid_fees.json").write_text(
        json.dumps({"rule_sets": {}, "areas": []}),
        encoding="utf-8",
    )

    plan = plan_migration(config_dir)
    assert migration_blocks_normal_startup(plan)
    assert any("components.json" in b.message_de for b in plan.blockers)
    assert not any("grid_fees" in b.message_de for b in plan.blockers)

    with pytest.raises(SystemExit):
        load_config_or_exit()
    err = capsys.readouterr().err
    assert "Version unbekannt" in err or "fehlt" in err


def test_untagged_grid_fees_is_a_pending_tariff_step(tmp_path, monkeypatch):
    """Fully migrated Earnie track + untagged grid_fees → tf1.tariff_format pending, no level blocker."""
    config_dir = _copy_snapshot(tmp_path, "v4_pre_topology", from_goldens=True)
    _point_config(monkeypatch, config_dir)
    fees_path = config_dir / "grid_fees.json"
    doc = json.loads(fees_path.read_text(encoding="utf-8"))
    doc.pop("tariff_format")
    fees_path.write_text(json.dumps(doc), encoding="utf-8")
    plan = plan_migration(config_dir)
    assert migration_blocks_normal_startup(plan)
    assert plan.pending_step_ids == ("tf1.tariff_format",)
    assert not plan.blockers
    assert DATA_MODEL_KEY not in json.loads(fees_path.read_text(encoding="utf-8"))


def test_clean_config_allows_gate(tmp_path, monkeypatch):
    config_dir = _copy_snapshot(tmp_path, "v4_pre_topology", from_goldens=True)
    _point_config(monkeypatch, config_dir)
    plan = plan_for_active_config()
    assert not migration_blocks_normal_startup(plan)


def test_greenfield_bootstrap_gate_stays_open(tmp_path, monkeypatch):
    """Empty config + real share minimals → silent dm4 seed, no Migration UI."""
    from runtime_store.persist_paths import clear_sidecar_path_cache

    repo_root = Path(__file__).resolve().parents[1]
    config_dir = tmp_path / "config"
    env_root = tmp_path / "earnie_env"
    env_root.mkdir()
    _point_config(monkeypatch, config_dir)
    monkeypatch.setenv("EARNIE_ENV_PATH", str(env_root))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(env_root / "runtime"))
    # HA first-start: sidecars co-locate under CONFIG_PATH even when missing.
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    monkeypatch.chdir(repo_root)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    clear_sidecar_path_cache()

    bootstrap.run()

    house = json.loads(
        (config_dir / "house_profiles.json").read_text(encoding="utf-8")
    )
    grid_meter = house.get("plant", {}).get("grid_meter")
    assert isinstance(grid_meter, dict)
    assert "at_house_connection" in grid_meter
    assert "single_tariff" in grid_meter

    plan = plan_for_active_config()
    assert plan.pending_step_ids == ()
    assert plan.blockers == ()
    assert not migration_blocks_normal_startup(plan)
    assert "dm4.topology" not in plan.pending_step_ids


def test_same_model_range_label_avoids_arrow():
    plan = MigrationPlan(
        config_dir="/tmp/x",
        from_model=4,
        to_model=4,
        pending_step_ids=("dm4.topology",),
        questions=(),
        blockers=(),
        manual_todos=(),
        file_diffs=(),
        can_run=True,
    )
    assert model_range_label_de(plan) == (
        "strukturelle Schritte innerhalb Datenmodell 4"
    )
    assert "4 → 4" not in abort_message_de(plan)
    bump = MigrationPlan(
        config_dir="/tmp/x",
        from_model=3,
        to_model=4,
        pending_step_ids=("dm4.v3_to_v4",),
        questions=(),
        blockers=(),
        manual_todos=(),
        file_diffs=(),
        can_run=True,
    )
    assert model_range_label_de(bump) == "Datenmodell 3 → 4"


def test_shadow_pending_refuses_startup(tmp_path, monkeypatch):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    _point_config(monkeypatch, config_dir)
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_runtime"))
    (tmp_path / "shadow_runtime").mkdir(parents=True)

    from runtime_store.shadow.startup import ensure_shadow_startup

    with pytest.raises(ShadowStartupError, match="migriert"):
        ensure_shadow_startup()


def test_run_streamlit_migration_mode_skips_auto_start(tmp_path, monkeypatch):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    _point_config(monkeypatch, config_dir)
    monkeypatch.setenv("EARNIE_AUTO_START_MAIN", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)

    calls: list[str] = []

    def fake_auto_start():
        calls.append("auto")
        return None

    def fake_run_cli(argv):
        calls.append("streamlit")
        return 0

    monkeypatch.setattr(
        "runtime_store.main_daemon.maybe_auto_start",
        fake_auto_start,
    )
    # Patch where run_streamlit looks up helpers after import.
    import scripts.run_streamlit as rs

    monkeypatch.setattr(rs, "_maybe_auto_start_main", lambda: calls.append("auto"))
    monkeypatch.setattr(rs, "_run_streamlit_cli", fake_run_cli)

    code = rs.main([])
    assert code == 0
    assert "auto" not in calls
    assert "streamlit" in calls


def test_run_streamlit_shadow_pending_exits(tmp_path, monkeypatch, capsys):
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    _point_config(monkeypatch, config_dir)
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_runtime"))
    (tmp_path / "shadow_runtime").mkdir(parents=True)

    import scripts.run_streamlit as rs

    monkeypatch.setattr(rs, "_run_streamlit_cli", lambda _argv: 0)
    # Shadow+pending refuses before Streamlit; bootstrap must not crash on seed.
    code = rs.main([])
    assert code == 1
    captured = capsys.readouterr()
    assert "Shadow" in captured.out or "Shadow" in captured.err
    assert "geteilte Prod-Konfiguration" in captured.out


def test_run_streamlit_private_shadow_pending_opens_migration_mode(
    tmp_path, monkeypatch, capsys
):
    """Private Shadow config (feed outside it) migrates like any install: wizard, no abort."""
    config_dir = _copy_snapshot(tmp_path, "v3_single_battery")
    _point_config(monkeypatch, config_dir)
    feed = tmp_path / "prod_feed"
    feed.mkdir()
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_runtime"))
    (tmp_path / "shadow_runtime").mkdir(parents=True)

    calls: list[str] = []
    import scripts.run_streamlit as rs

    monkeypatch.setattr(rs, "_maybe_auto_start_main", lambda: calls.append("auto"))
    monkeypatch.setattr(rs, "_run_streamlit_cli", lambda _argv: calls.append("streamlit") or 0)

    code = rs.main([])
    assert code == 0
    assert calls == ["streamlit"]
    out = capsys.readouterr().out
    assert "Migrationsmodus" in out
    assert "Abbruch (Shadow)" not in out


def test_migration_planner_import_does_not_load_config():
    """Planner/gate must import without ``config`` (legacy keys would fail loud first)."""
    import subprocess
    import sys

    code = (
        "import sys; "
        "import runtime_store.migration.gate, runtime_store.migration.registry; "
        "sys.exit(1 if 'config' in sys.modules else 0)"
    )
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, "-c", code], cwd=root, check=False)
    assert result.returncode == 0


def test_bootstrap_with_legacy_config_reaches_migration_gate(tmp_path):
    """bootstrap.run() plans migration without loading ``config`` (legacy keys)."""
    import os
    import subprocess
    import sys

    config_dir = _copy_snapshot(tmp_path, "v4_pre_ha_pull")
    code = (
        "import sys; from runtime_store import bootstrap; bootstrap.run(); "
        "sys.exit(1 if 'config' in sys.modules else 0)"
    )
    env = {
        **os.environ,
        "EARNIE_CONFIG_PATH": str(config_dir / "config.json"),
        "EARNIE_RUNTIME_PATH": str(tmp_path / "runtime"),
    }
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root, env=env, check=False,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_leftover_ha_transport_reaches_migration_gate(tmp_path, monkeypatch, capsys):
    config_dir = _copy_snapshot(tmp_path, "v4_pre_ha_pull")
    _point_config(monkeypatch, config_dir)
    plan = plan_for_active_config()
    assert "dm4.ha_pull_removal" in plan.pending_step_ids
    with pytest.raises(SystemExit):
        load_config_or_exit()
    assert "migriert" in capsys.readouterr().err.lower()
