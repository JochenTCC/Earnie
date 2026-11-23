"""Recorder replay: config snapshot materialization, env activation and segment selection.

Split from ``runtime_store.recorder_replay`` (KPI refactor); that module re-exports these names.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("runtime_store.recorder_replay")


_ARCHIVE_TO_ENV: dict[str, str] = {
    "inputs/config.json": "config/config.json",
    "inputs/components.json": "config/components.json",
    "inputs/tariffs.json": "config/tariffs.json",
    "inputs/user_tariffs.json": "config/user_tariffs.json",
    "inputs/grid_fees.json": "config/grid_fees.json",
    "inputs/user_grid_fees.json": "config/user_grid_fees.json",
    "inputs/house_profiles.json": "config/house_profiles.json",
    "inputs/backtesting_scenarios.json": "config/backtesting_scenarios.json",
    "inputs/deviation_rules.json": "config/deviation_rules.json",
    "inputs/local_settings.json": "runtime/local_settings.json",
    "inputs/price_model_coefficients.json": "runtime/price_model_coefficients.json",
    "inputs/cons_data.csv": "runtime/cons_data.csv",
}


_ENV_CLEAR_SUFFIXES = (
    "CONFIG_PATH",
    "COMPONENTS_PATH",
    "DEVIATION_RULES_PATH",
    "GRID_FEES_PATH",
    "HOUSE_PROFILES_PATH",
    "LOCAL_SETTINGS_PATH",
    "RUNTIME_PATH",
    "TARIFFS_PATH",
    "BACKTESTING_SCENARIOS_PATH",
)


def load_config_snapshot(recorder_root: Path | str, config_hash: str) -> dict[str, Any]:
    """Load ``configs/{config_hash}.json`` or raise."""
    root = Path(recorder_root)
    path = root / "configs" / f"{config_hash}.json"
    if not path.is_file():
        hint = ""
        if (root / "configs.pack.json").is_file():
            hint = (
                "; the snapshots are still packed: "
                f"python -m runtime_store.recorder_config_pack {root}"
            )
        raise FileNotFoundError(
            f"recorder config snapshot missing: {path} "
            f"(config_hash={config_hash!r}){hint}"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or "files" not in payload:
        raise ValueError(f"invalid config snapshot shape: {path}")
    return payload


def _drop_removed_empty_overlay(content: str) -> str:
    """Recordings made before ``flexible_consumers`` was removed carry ``[]``; a filled block is an error."""
    doc = json.loads(content)
    if not isinstance(doc, dict) or "flexible_consumers" not in doc:
        return content
    if doc["flexible_consumers"]:
        raise ValueError(
            "recorded config.json uses the removed 'flexible_consumers' overlay; "
            "replay needs a recording made after consumers moved to the house profile."
        )
    del doc["flexible_consumers"]
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def materialize_config_snapshot(
    snapshot: dict[str, Any],
    dest_env: Path | str,
) -> Path:
    """Write snapshot ``files`` into an Earnie env tree (config/ + runtime/)."""
    env_root = Path(dest_env)
    files = snapshot.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("config snapshot has no files")
    written = 0
    for archive_name, content in files.items():
        rel = _ARCHIVE_TO_ENV.get(str(archive_name).replace("\\", "/"))
        if rel is None:
            raise ValueError(
                f"unsupported snapshot archive name {archive_name!r}; "
                f"known: {sorted(_ARCHIVE_TO_ENV)}"
            )
        if not isinstance(content, str):
            raise TypeError(
                f"snapshot file {archive_name!r} must be text, got {type(content)!r}"
            )
        if rel == "config/config.json":
            content = _drop_removed_empty_overlay(content)
        target = env_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    if written == 0:
        raise ValueError("config snapshot wrote zero files")
    (env_root / "runtime").mkdir(parents=True, exist_ok=True)
    _migrate_snapshot_config(env_root / "config")
    return env_root


def _migrate_snapshot_config(config_dir: Path) -> None:
    """Archived configs may predate the current data model / tariff format: migrate in memory.

    Same registry steps as the wizard from the recorded data model on, without answers; a
    snapshot that needs an answer or hits a blocker stops the replay with the reason (never
    guessed). Steps of the recorded model itself are skipped: the config ran when recorded.
    """
    from runtime_store.migration.runner import migrate_config_dir_unattended

    written = migrate_config_dir_unattended(
        config_dir, label="recorder config snapshot", model_bump_only=True
    )
    if written:
        logger.debug("replay: migrated snapshot config files %s", ", ".join(written))


def restore_matrix_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Columnar matrix → row dicts with ``datetime`` slot times."""
    from runtime_store.cycle_recorder import columnar_to_matrix

    columnar = entry.get("optimization_matrix")
    if not isinstance(columnar, dict):
        raise ValueError("entry missing optimization_matrix columnar payload")
    n_rows = int(columnar.get("n_rows") or 0)
    if n_rows <= 0:
        raise ValueError("entry optimization_matrix has n_rows <= 0")
    matrix = columnar_to_matrix(columnar)
    if len(matrix) != n_rows:
        raise ValueError(
            f"matrix restore length mismatch: got {len(matrix)}, expected {n_rows}"
        )
    return _coerce_matrix_datetimes(matrix)


def _coerce_matrix_datetimes(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in matrix:
        raw = row.get("slot_datetime")
        # Keep the recorded offset: the live matrix is tz-aware and so are the
        # recorded deadlines it is compared with (open_charging_deadlines).
        if isinstance(raw, datetime):
            slot = raw
        elif isinstance(raw, str):
            slot = datetime.fromisoformat(raw)
        else:
            raise TypeError(
                f"slot_datetime must be str or datetime, got {type(raw)!r}"
            )
        row["slot_datetime"] = slot
        row["hour"] = int(slot.hour)
        row["date"] = slot.date()
    return matrix


def _write_start_state_files(env_root: Path, start_state: dict[str, Any]) -> None:
    runtime = env_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    mapping = (
        ("flexible_consumers_state", "flexible_consumers_state.json"),
        ("pv_counter_state", "pv_counter_state.json"),
        ("run_state", "optimizer_run_state.json"),
    )
    for key, filename in mapping:
        payload = start_state.get(key)
        if payload is None:
            continue
        path = runtime / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


def _rebind_consumer_state_path() -> None:
    """Point an already-imported optimizer at the env activated for this replay.

    ``CONSUMER_STATE_FILE`` is captured when ``optimizer`` is first imported.
    Replay deletes that temp env afterwards, so the next cycle in the same
    process would load a missing file and drop the recorded delivered kWh.
    """
    import sys

    optimizer = sys.modules.get("optimizer")
    if optimizer is None or not hasattr(optimizer, "CONSUMER_STATE_FILE"):
        return
    from runtime_store.persist_paths import consumer_state_file

    optimizer.CONSUMER_STATE_FILE = consumer_state_file()


def _activate_env(env_root: Path) -> dict[str, str | None]:
    previous = {"EARNIE_ENV_PATH": os.environ.get("EARNIE_ENV_PATH")}
    for suffix in _ENV_CLEAR_SUFFIXES:
        key = f"EARNIE_{suffix}"
        previous[key] = os.environ.get(key)
        os.environ.pop(key, None)
    os.environ["EARNIE_ENV_PATH"] = str(env_root)
    os.environ["EARNIE_OFFLINE"] = "1"
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _segment_paths_for_root(root: Path) -> list[Path]:
    from runtime_store import cycle_recorder

    previous = os.environ.get("EARNIE_RUNTIME_PATH")
    try:
        # Segments live under recorder_root directly when passed as study dir,
        # or under runtime/recorder when root is an env runtime/recorder path.
        direct = sorted(root.glob("cycles_*.jsonl.gz"))
        if direct:
            return direct
        if any(root.glob("cycles_*.jsonl.xz")):
            raise FileNotFoundError(
                f"recorder segments under {root} are still xz-packed: "
                f"python -m runtime_store.recorder_config_pack {root}"
            )
        os.environ["EARNIE_RUNTIME_PATH"] = str(root.parent)
        return cycle_recorder.list_segment_paths()
    finally:
        if previous is None:
            os.environ.pop("EARNIE_RUNTIME_PATH", None)
        else:
            os.environ["EARNIE_RUNTIME_PATH"] = previous


def _entry_slot_count(entry: dict[str, Any]) -> int:
    columnar = entry.get("optimization_matrix") or {}
    try:
        return int(columnar.get("n_rows") or 0)
    except (TypeError, ValueError):
        return 0


# ``outage`` is the name cycles recorded before 2026-11-09 use for ``out_of_band``.
_FLAG_NAMES = ("override", "out_of_band", "outage", "manual_intervention")


def _entry_is_flagged(entry: dict[str, Any]) -> bool:
    flags = ((entry.get("outputs") or {}).get("flags")) or {}
    return any(bool(flags.get(name)) for name in _FLAG_NAMES)


def _best_effort_rmtree(path: Path) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError as exc:
        logger.debug("replay temp cleanup failed: %s", exc)
