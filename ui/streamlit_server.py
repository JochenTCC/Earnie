"""Streamlit-Server-Port aus config.json (ui.streamlit_port) mit Env-Override."""
from __future__ import annotations

import os

import config

_ENV_STREAMLIT_PORT = "ENERGY_OPTIMIZER_UI_STREAMLIT_PORT"
_DEFAULT_PORT = 8501
_MIN_PORT = 1024
_MAX_PORT = 65535


def _parse_env_port() -> int | None:
    raw = os.environ.get(_ENV_STREAMLIT_PORT, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Umgebungsvariable {_ENV_STREAMLIT_PORT} muss eine ganze Zahl sein, erhalten: {raw!r}."
        ) from exc
    if not _MIN_PORT <= value <= _MAX_PORT:
        raise ValueError(
            f"Umgebungsvariable {_ENV_STREAMLIT_PORT} muss zwischen {_MIN_PORT} und {_MAX_PORT} liegen."
        )
    return value


def streamlit_port() -> int:
    """Port für `streamlit run` (Env-Override hat Vorrang vor config.json)."""
    env = _parse_env_port()
    if env is not None:
        return env
    return config.get_ui_streamlit_port()
