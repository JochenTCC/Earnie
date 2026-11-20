"""Local sponsoring UI state (opt-out of the "Earnie unterstützen" button).

Nothing here is sent anywhere. Missing file means the user has not opted out.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from runtime_store.persist_paths_base import sponsoring_state_file

logger = logging.getLogger(__name__)

SPONSORS_URL = "https://github.com/sponsors/Earnie-HEMS"


def load_state() -> dict[str, Any]:
    path = sponsoring_state_file()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("sponsoring: cannot read %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("sponsoring: state root must be an object: %s", path)
        return {}
    return raw


def save_state(state: dict[str, Any]) -> None:
    path = sponsoring_state_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def is_opted_out() -> bool:
    return load_state().get("opt_out") is True


def set_opt_out(opt_out: bool, *, now: datetime | None = None) -> None:
    stamp = now if now is not None else datetime.now(timezone.utc)
    state = load_state()
    state["opt_out"] = bool(opt_out)
    state["opt_out_changed_at"] = stamp.astimezone(timezone.utc).isoformat()
    save_state(state)
