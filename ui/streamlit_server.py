"""Streamlit-Server-Port aus config.json (ui.streamlit_port) mit Env-Override."""
from __future__ import annotations

from runtime_store.env_vars import read_env

_DEFAULT_PORT = 8501
_MIN_PORT = 1024
_MAX_PORT = 65535


def _parse_env_port() -> int | None:
    raw = read_env("UI_STREAMLIT_PORT")
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Umgebungsvariable EARNIE_UI_STREAMLIT_PORT muss eine ganze Zahl sein, erhalten: {raw!r}."
        ) from exc
    if not _MIN_PORT <= value <= _MAX_PORT:
        raise ValueError(
            f"Umgebungsvariable EARNIE_UI_STREAMLIT_PORT muss zwischen {_MIN_PORT} und {_MAX_PORT} liegen."
        )
    return value


def streamlit_port(*, require_config: bool = True) -> int:
    """Port für `streamlit run` (Env-Override hat Vorrang vor config.json).

    When ``require_config`` is False (ConfigMigration mode), env or default
    ``8501`` is used without importing ``config``.
    """
    env = _parse_env_port()
    if env is not None:
        return env
    if not require_config:
        return _DEFAULT_PORT
    import config

    return config.get_ui_streamlit_port()
