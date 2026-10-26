"""UI → daemon: ask for an ad-hoc optimization run and detect config changes worth one.

The Streamlit process is separate from ``main.py``; the request travels over the
daemon's local HTTP listener (same route as the Miniserver ``Earnie_Request_Optimize``).
"""
from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from typing import Callable

import config
from integrations.ehal_request_http import REQUEST_OPTIMIZE_PATH
from runtime_store import run_state
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_grid_fees_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
    resolve_user_grid_fees_json_path,
    resolve_user_tariffs_json_path,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SEC = 3.0

# Files whose content feeds the live plan. ``main.py`` re-reads them at every cycle
# start, so a newer mtime than the last finished run means the plan is outdated.
_PLAN_INPUT_RESOLVERS: tuple[Callable[[], str], ...] = (
    resolve_config_json_path,
    resolve_tariffs_json_path,
    resolve_user_tariffs_json_path,
    resolve_house_profiles_json_path,
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_grid_fees_json_path,
    resolve_user_grid_fees_json_path,
)


class OptimizeRequestError(RuntimeError):
    """The daemon could not be reached or rejected the request."""


def plan_inputs_changed_since_last_run(
    state: dict | None = None,
    *,
    resolvers: tuple[Callable[[], str], ...] = _PLAN_INPUT_RESOLVERS,
) -> bool:
    """True when a plan-relevant config file is newer than the last finished run."""
    last_run = run_state.completed_at_epoch(
        state if state is not None else run_state.load_run_state()
    )
    if last_run is None:
        return False
    for resolve in resolvers:
        try:
            path = resolve()
            if path and os.path.getmtime(path) > last_run:
                return True
        except OSError:
            continue
    return False


def request_optimize(*, port: int | None = None) -> None:
    """POST the Request-Optimize route of the local daemon; raises on failure."""
    target_port = int(port) if port is not None else config.get_ehal_http_port()
    url = f"http://127.0.0.1:{target_port}{REQUEST_OPTIMIZE_PATH}"
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SEC):
            return
    except (urllib.error.URLError, OSError) as exc:
        raise OptimizeRequestError(
            f"Optimierer-Dienst unter Port {target_port} nicht erreichbar ({exc})."
        ) from exc
