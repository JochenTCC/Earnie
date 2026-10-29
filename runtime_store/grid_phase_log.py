"""Device-detection push log (NILM stage 0, dev only).

Appends every push of a grid meter value (``ehal.grid_phase_fields``: per-phase U/I/P,
total Q / PF and total grid power) to a daily JSONL file with the arrival timestamp:

    runtime/grid_phase_log/YYYY-MM-DD.jsonl   (UTC date)
    {"ts": "2026-10-29T08:15:03.412+00:00", "id": "grid.meter.sens_grid_voltage_l1", "v": 231.4}

Values are stored as pushed (hub units, e.g. Loxone kW); conversion to EHAL units uses
the ``loxone`` blocks in ``share/ehal/roles/grid_phases.json`` / ``grid.json`` at analysis
time. A push that does not parse is logged with ``"v": null`` and its ``"raw"`` text.

Active only when ``EARNIE_UI_MODES`` lists ``device_detection``. No retention: files stay
until removed by hand (≈ 10–20 MB per day at a 5 s Loxone poll).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

from ehal.grid_phase_fields import grid_phase_log_ids
from runtime_store.env_vars import is_device_detection_enabled
from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

LOG_DIRNAME = "grid_phase_log"

_LOG_IDS = grid_phase_log_ids()
_lock = threading.Lock()
_failure_logged = False


def log_dir() -> str:
    return runtime_path(LOG_DIRNAME)


def log_path_for(stamp: datetime) -> str:
    return os.path.join(log_dir(), f"{stamp.date().isoformat()}.jsonl")


def is_logged_id(ehal_id: str) -> bool:
    return ehal_id in _LOG_IDS


def record(ehal_id: str, value: float | None, raw: str, stamp: datetime) -> bool:
    """Append one push when the feature is on and *ehal_id* is a grid meter value.

    Returns True when a line was written. A write error is logged (first one with
    traceback) and never propagates into the push listener.
    """
    global _failure_logged
    if ehal_id not in _LOG_IDS or not is_device_detection_enabled():
        return False
    row: dict[str, object] = {"ts": stamp.isoformat(timespec="milliseconds"), "id": ehal_id, "v": value}
    if value is None:
        row["raw"] = raw
    line = json.dumps(row, separators=(",", ":")) + "\n"
    try:
        with _lock:
            os.makedirs(log_dir(), exist_ok=True)
            with open(log_path_for(stamp), "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
    except OSError:
        if not _failure_logged:
            _failure_logged = True
            logger.exception("grid_phase_log: cannot write %s", log_path_for(stamp))
        else:
            logger.warning("grid_phase_log: write failed for %s", ehal_id)
        return False
    return True
