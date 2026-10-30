"""Always-on production cycle recorder (Regression R-Rec).

Captures optimizer inputs immediately before ``prepare_optimization_matrix``
and flushes outputs after the cycle. Failures never affect the live run.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RECORDER_SCHEMA = 1
_DEFAULT_RETENTION_DAYS = 7
_SEGMENT_RE = re.compile(r"^cycles_(\d{4}-\d{2}-\d{2})\.jsonl\.gz$")

_lock = threading.RLock()
_lost_cycles = 0
_pending: dict[int, "CycleToken"] = {}
_next_token_id = 1


@dataclass
class CycleToken:
    """Opaque in-memory handle between begin_cycle and finish_cycle."""

    token_id: int
    timestamp: str
    app_version: str
    config_hash: str
    optimization_matrix: dict[str, Any]
    planning_window: dict[str, Any]
    start_state: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)


def reset_for_tests() -> None:
    """Clear in-memory recorder state (unit tests only)."""
    global _lost_cycles, _next_token_id
    from data.outdoor_forecast import close_forecast_capture
    from runtime_store.push_read_replay import close_push_read_capture

    close_forecast_capture()
    close_push_read_capture()
    with _lock:
        _pending.clear()
        _lost_cycles = 0
        _next_token_id = 1


def lost_cycle_count() -> int:
    with _lock:
        return _lost_cycles


def recorder_dir() -> Path:
    from runtime_store.persist_paths import runtime_path

    return Path(runtime_path("recorder"))


def configs_dir() -> Path:
    return recorder_dir() / "configs"


def is_recorder_enabled() -> bool:
    try:
        import config

        return bool(config.is_recorder_enabled())
    except Exception:  # noqa: BLE001 — never break callers
        return True


def retention_days() -> int:
    try:
        import config

        return int(config.get_recorder_retention_days())
    except Exception:  # noqa: BLE001
        return _DEFAULT_RETENTION_DAYS


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _json_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(item) for item in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def matrix_to_columnar(matrix: list[dict] | None) -> dict[str, Any]:
    """Serialize row-dicts to columnar arrays (spec §14)."""
    rows = list(matrix or [])
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    data = {
        col: [_json_safe(row.get(col) if isinstance(row, dict) else None) for row in rows]
        for col in columns
    }
    return {"columns": columns, "n_rows": len(rows), "data": data}


def columnar_to_matrix(columnar: dict[str, Any] | None) -> list[dict]:
    """Inverse of :func:`matrix_to_columnar`."""
    if not isinstance(columnar, dict):
        return []
    columns = list(columnar.get("columns") or [])
    data = columnar.get("data") or {}
    n_rows = int(columnar.get("n_rows") or 0)
    rows: list[dict] = []
    for index in range(n_rows):
        row: dict[str, Any] = {}
        for col in columns:
            values = data.get(col)
            if isinstance(values, list) and index < len(values):
                row[col] = values[index]
        rows.append(row)
    return rows


def compute_plan_hash(
    *,
    mode: Any = None,
    target_power_kw: Any = None,
    battery_plan_kw: Any = None,
    consumer_powers_kw: Any = None,
) -> str:
    """Stable short hash of the written plan surface."""
    payload = {
        "mode": mode,
        "target_power_kw": target_power_kw,
        "battery_plan_kw": _json_safe(battery_plan_kw),
        "consumer_powers_kw": _json_safe(consumer_powers_kw),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_config_hash() -> str:
    """SHA-256 over dump input files (same set as debug dumps)."""
    from runtime_store.debug_dump_inputs import iter_input_files

    digest = hashlib.sha256()
    for source_path, archive_name in sorted(iter_input_files(), key=lambda item: item[1]):
        digest.update(archive_name.encode("utf-8"))
        digest.update(b"\0")
        with open(source_path, "rb") as handle:
            digest.update(handle.read())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_json_file(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _collect_ev_limit_soc() -> dict[str, float]:
    """Resolved ``get_evcs_limit_soc`` per consumer bound to that marker.

    ``prepare_optimization_matrix`` reads it live; replay has no live value.
    Raises when a bound marker is unreadable (same as the live run would).
    """
    import config
    from settings.ehal_marker_resolve import (
        marker_get_evcs_limit_soc,
        resolve_get_evcs_limit_soc,
    )

    out: dict[str, float] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True) or []:
        if marker_get_evcs_limit_soc(consumer):
            out[str(consumer["id"])] = resolve_get_evcs_limit_soc(consumer)
    return out


def _collect_thermal_readings() -> dict[str, dict]:
    """Live thermal readings per consumer with an enabled ``thermal_control``.

    The thermal daily target reads them live (``fetch_thermal_readings``);
    replay has no live value.
    """
    import config
    from integrations import ehal_live

    out: dict[str, dict] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True) or []:
        if (consumer.get("thermal_control") or {}).get("enabled"):
            out[str(consumer["id"])] = _json_safe(
                ehal_live.fetch_thermal_readings(consumer)
            )
    return out


def _collect_start_state(
    *,
    soc_percent: float | None,
    soc_percent_by_ess: dict[str, float] | None,
    charging_contexts: dict | None,
    targets: dict | None,
) -> dict[str, Any]:
    from runtime_store.persist_paths import consumer_state_file, pv_counter_state_file
    from runtime_store import run_state

    return {
        "soc_percent": soc_percent,
        "soc_percent_by_ess": _json_safe(soc_percent_by_ess or {}),
        "flexible_consumers_state": _read_json_file(consumer_state_file()),
        "pv_counter_state": _read_json_file(pv_counter_state_file()),
        "run_state": run_state.load_run_state(),
        "charging_contexts": _json_safe(charging_contexts or {}),
        "targets": _json_safe(targets or {}),
        "ev_limit_soc_percent": _collect_ev_limit_soc(),
        "thermal_readings": _collect_thermal_readings(),
    }


def _app_version() -> str:
    try:
        from version import __version__

        return str(__version__)
    except ImportError:
        return "unknown"


def _note_lost(cause: str, exc: BaseException) -> None:
    global _lost_cycles
    with _lock:
        _lost_cycles += 1
        count = _lost_cycles
    logger.warning(
        "cycle_recorder: cycle lost (%s, total=%d): %s",
        cause,
        count,
        exc,
    )


def _ensure_config_snapshot(config_hash: str) -> None:
    from runtime_store.debug_dump_inputs import iter_input_files

    configs_dir().mkdir(parents=True, exist_ok=True)
    path = configs_dir() / f"{config_hash}.json"
    if path.is_file():
        return
    snapshot: dict[str, Any] = {"schema": RECORDER_SCHEMA, "files": {}}
    for source_path, archive_name in iter_input_files():
        with open(source_path, encoding="utf-8") as handle:
            snapshot["files"][archive_name] = handle.read()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False)
    os.replace(tmp, path)


def segment_path_for_day(day: date | None = None) -> Path:
    stamp = (day or date.today()).isoformat()
    return recorder_dir() / f"cycles_{stamp}.jsonl.gz"


def list_segment_paths() -> list[Path]:
    root = recorder_dir()
    if not root.is_dir():
        return []
    paths = [path for path in root.iterdir() if _SEGMENT_RE.match(path.name)]
    return sorted(paths)


def prune_old_segments(keep_days: int | None = None) -> list[Path]:
    """Delete segment files older than retention. Returns removed paths."""
    days = int(keep_days if keep_days is not None else retention_days())
    cutoff = date.today() - timedelta(days=max(days, 1) - 1)
    removed: list[Path] = []
    for path in list_segment_paths():
        match = _SEGMENT_RE.match(path.name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if day < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def _append_cycle_line(entry: dict[str, Any], *, day: date | None = None) -> Path:
    recorder_dir().mkdir(parents=True, exist_ok=True)
    path = segment_path_for_day(day)
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
    with gzip.open(path, "ab") as handle:
        handle.write(line.encode("utf-8"))
    return path


def begin_cycle(
    *,
    optimization_matrix: list[dict],
    planning_window: dict[str, Any] | Any,
    soc_percent: float | None = None,
    soc_percent_by_ess: dict[str, float] | None = None,
    charging_contexts: dict | None = None,
    targets: dict | None = None,
    timestamp: datetime | None = None,
) -> CycleToken | None:
    """Snapshot inputs before prepare. Returns None when disabled or soft-failed."""
    if not is_recorder_enabled():
        return None
    try:
        from runtime_store.live_display_loader import serialize_planning_window

        moment = timestamp or datetime.now()
        if hasattr(planning_window, "start"):
            window_payload = serialize_planning_window(planning_window)
        elif isinstance(planning_window, dict):
            window_payload = _json_safe(planning_window)
        else:
            raise TypeError(
                f"planning_window must be PlanningWindow or dict, got {type(planning_window)!r}"
            )
        config_hash = compute_config_hash()
        _ensure_config_snapshot(config_hash)
        global _next_token_id
        with _lock:
            token_id = _next_token_id
            _next_token_id += 1
            token = CycleToken(
                token_id=token_id,
                timestamp=moment.isoformat(timespec="seconds"),
                app_version=_app_version(),
                config_hash=config_hash,
                optimization_matrix=matrix_to_columnar(deepcopy(optimization_matrix)),
                planning_window=window_payload,
                start_state=_collect_start_state(
                    soc_percent=soc_percent,
                    soc_percent_by_ess=soc_percent_by_ess,
                    charging_contexts=charging_contexts,
                    targets=targets,
                ),
            )
            _pending[token_id] = token
        from data.outdoor_forecast import open_forecast_capture
        from runtime_store.push_read_replay import open_push_read_capture

        open_forecast_capture()
        open_push_read_capture()
        return token
    except Exception as exc:  # noqa: BLE001
        from data.outdoor_forecast import close_forecast_capture
        from runtime_store.push_read_replay import close_push_read_capture

        close_forecast_capture()
        close_push_read_capture()
        _note_lost("begin_cycle", exc)
        return None


def _attach_recorded_outdoor_forecast(token: CycleToken) -> None:
    """Copy the series fetched after begin_cycle into the entry, then stop capture.

    The key is always written. ``None`` means no forecast was read during the
    cycle, so replay fails loud if it reads one. A missing key marks cycles
    recorded before this field existed (replay may fetch live).
    """
    from data.outdoor_forecast import close_forecast_capture

    bucket = close_forecast_capture()
    token.start_state["outdoor_forecast"] = None
    if not bucket:
        return
    values = bucket.get("values_c")
    source = bucket.get("source")
    if not isinstance(values, list) or not values or not isinstance(source, str):
        return
    token.start_state["outdoor_forecast"] = {
        "values_c": values,
        "source": source,
    }


def _attach_recorded_push_reads(token: CycleToken) -> None:
    """Copy the inbox reads made after begin_cycle into the entry, then stop capture.

    The live EV charging context (plugged in, SoC, ready time, limits) is built
    from these reads after ``begin_cycle``; replay serves them back.
    """
    from runtime_store.push_read_replay import close_push_read_capture

    bucket = close_push_read_capture()
    if bucket is not None:
        token.start_state["push_reads"] = _json_safe(bucket)


def record_active_reserves(
    token: CycleToken | None,
    reserves: list[dict[str, Any]] | None,
) -> None:
    """Store the powerstation reserves the live MILP planned with.

    They come from ``powerstation_reserves.json`` after the telemetry trigger
    sync, and shape the battery params (virtual refill carve-out).
    """
    if token is None:
        return
    try:
        token.start_state["active_reserves"] = _json_safe(list(reserves or []))
    except Exception as exc:  # noqa: BLE001 — never abort the live run
        logger.warning("cycle_recorder: record_active_reserves failed: %s", exc)


def _default_flags() -> dict[str, bool]:
    return {
        "override": False,
        "immediate_charging": False,
        "outage": False,
        "manual_intervention": False,
    }


def _build_cycle_entry(
    token: CycleToken,
    *,
    setpoints: dict[str, Any] | None,
    plan_hash: str | None,
    flags: dict[str, Any] | None,
    mode: Any,
    target_power_kw: Any,
    battery_plan_kw: Any,
    consumer_powers_kw: Any,
) -> dict[str, Any]:
    resolved_hash = plan_hash or compute_plan_hash(
        mode=mode,
        target_power_kw=target_power_kw,
        battery_plan_kw=battery_plan_kw,
        consumer_powers_kw=consumer_powers_kw,
    )
    resolved_setpoints = setpoints or {
        "mode": mode,
        "target_power_kw": target_power_kw,
        "battery_plan_kw": _json_safe(battery_plan_kw),
        "consumer_powers_kw": _json_safe(consumer_powers_kw),
    }
    return {
        "schema": RECORDER_SCHEMA,
        "timestamp": token.timestamp,
        "app_version": token.app_version,
        "config_hash": token.config_hash,
        "optimization_matrix": token.optimization_matrix,
        "planning_window": token.planning_window,
        "start_state": token.start_state,
        "outputs": {
            "setpoints": _json_safe(resolved_setpoints),
            "plan_hash": resolved_hash,
            "flags": _json_safe(flags or _default_flags()),
        },
    }


def _segment_day_from_timestamp(timestamp: str) -> date:
    try:
        return date.fromisoformat(str(timestamp)[:10])
    except ValueError:
        return date.today()


def finish_cycle(
    token: CycleToken | None,
    *,
    setpoints: dict[str, Any] | None = None,
    plan_hash: str | None = None,
    flags: dict[str, Any] | None = None,
    mode: Any = None,
    target_power_kw: Any = None,
    battery_plan_kw: Any = None,
    consumer_powers_kw: Any = None,
) -> bool:
    """Append one cycle line with outputs. Soft-fails; never raises to caller."""
    if token is None:
        return False
    _attach_recorded_outdoor_forecast(token)
    _attach_recorded_push_reads(token)
    if not is_recorder_enabled():
        with _lock:
            _pending.pop(token.token_id, None)
        return False
    try:
        entry = _build_cycle_entry(
            token,
            setpoints=setpoints,
            plan_hash=plan_hash,
            flags=flags,
            mode=mode,
            target_power_kw=target_power_kw,
            battery_plan_kw=battery_plan_kw,
            consumer_powers_kw=consumer_powers_kw,
        )
        _append_cycle_line(entry, day=_segment_day_from_timestamp(token.timestamp))
        prune_old_segments()
        with _lock:
            _pending.pop(token.token_id, None)
        return True
    except Exception as exc:  # noqa: BLE001
        _note_lost("finish_cycle", exc)
        with _lock:
            _pending.pop(token.token_id, None)
        return False


def read_segment_cycles(path: Path | str) -> list[dict[str, Any]]:
    """Read all cycle entries from one gzip JSONL segment."""
    target = Path(path)
    cycles: list[dict[str, Any]] = []
    with gzip.open(target, "rt", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            cycles.append(json.loads(text))
    return cycles


def list_segment_paths_in(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    paths = [path for path in root.iterdir() if _SEGMENT_RE.match(path.name)]
    return sorted(paths)


def collect_recorder_dump_payload(
    *,
    retention: int | None = None,
    recorder_root: str | Path | None = None,
) -> dict[str, Any]:
    """
    Gather ring-buffer files and manifest fields for a debug dump.

    Returns ``{"files": [(src, arcname), ...], "manifest": {...}|None}``.
    Empty when recorder dir is missing or has no segments.
    """
    root = Path(recorder_root) if recorder_root is not None else recorder_dir()
    segments = list_segment_paths_in(root)
    if not segments:
        return {"files": [], "manifest": None}

    keep = int(retention if retention is not None else retention_days())
    cutoff = date.today() - timedelta(days=max(keep, 1) - 1)
    selected: list[Path] = []
    for path in segments:
        match = _SEGMENT_RE.match(path.name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if day >= cutoff:
            selected.append(path)

    if not selected:
        return {"files": [], "manifest": None}

    files: list[tuple[str, str]] = []
    config_hashes: set[str] = set()
    timestamps: list[str] = []
    cycle_count = 0
    for path in selected:
        files.append((str(path), f"recorder/{path.name}"))
        for entry in read_segment_cycles(path):
            cycle_count += 1
            ts = entry.get("timestamp")
            if isinstance(ts, str):
                timestamps.append(ts)
            ch = entry.get("config_hash")
            if isinstance(ch, str) and ch:
                config_hashes.add(ch)

    cfg_root = root / "configs"
    for config_hash in sorted(config_hashes):
        cfg_path = cfg_root / f"{config_hash}.json"
        if cfg_path.is_file():
            files.append((str(cfg_path), f"recorder/configs/{config_hash}.json"))

    timestamps.sort()
    manifest = {
        "from": timestamps[0] if timestamps else None,
        "to": timestamps[-1] if timestamps else None,
        "cycle_count": cycle_count,
        "config_hashes": sorted(config_hashes),
    }
    return {"files": files, "manifest": manifest}
