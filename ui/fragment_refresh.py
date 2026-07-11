"""Konfigurierbare Streamlit-Fragment-Refresh-Intervalle (Charts vs. Status-Widgets)."""
from __future__ import annotations

from datetime import timedelta

import config
from runtime_store.env_vars import read_env

_DEFAULT_CHARTS_SEC = 60
_DEFAULT_STATUS_SEC = 10
_DEFAULT_MAIN_SYNC_POLL_SEC = 15


def _parse_env_sec(suffix: str) -> int | None:
    raw = read_env(suffix)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Umgebungsvariable EARNIE_{suffix} muss eine ganze Zahl (Sekunden) sein, erhalten: {raw!r}."
        ) from exc
    if value < 1:
        raise ValueError(f"Umgebungsvariable EARNIE_{suffix} muss mindestens 1 sein.")
    return value


def charts_fragment_interval_sec() -> int:
    """Refresh-Intervall für Charts 1+2 (Live-Optimierung)."""
    env = _parse_env_sec("UI_FRAGMENT_CHARTS_SEC")
    if env is not None:
        return env
    return config.get_ui_fragment_charts_sec()


def status_fragment_interval_sec() -> int:
    """Refresh-Intervall für Sankey und Countdown."""
    env = _parse_env_sec("UI_FRAGMENT_STATUS_SEC")
    if env is not None:
        return env
    return config.get_ui_fragment_status_sec()


def main_sync_poll_interval_sec() -> int:
    """Poll-Intervall für leichtgewichtigen main.py-Abgleich (ohne Chart-Rerender)."""
    env = _parse_env_sec("UI_MAIN_SYNC_POLL_SEC")
    if env is not None:
        return env
    return config.get_ui_main_sync_poll_sec()


def charts_fragment_run_every() -> timedelta:
    return timedelta(seconds=charts_fragment_interval_sec())


CHARTS_FRAGMENT_RUN_EVERY = charts_fragment_run_every()
STATUS_FRAGMENT_RUN_EVERY = status_fragment_interval_sec()
MAIN_SYNC_POLL_RUN_EVERY = timedelta(seconds=main_sync_poll_interval_sec())
