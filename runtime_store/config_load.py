"""Robustes Laden von config.py für Prozess-Entrypoints."""
from __future__ import annotations

import os
import sys
from types import ModuleType

_CONFIG_ERRORS = (FileNotFoundError, ValueError, KeyError)


def _missing_config_message(config_path: str) -> str:
    env_path = os.environ.get("ENERGY_OPTIMIZER_CONFIG_PATH", "").strip()
    lines = [f"Abbruch: Konfigurationsdatei nicht gefunden: {config_path!r}"]
    if env_path:
        lines.append(f"  ENERGY_OPTIMIZER_CONFIG_PATH={env_path!r}")
    else:
        lines.append(
            "  Prüfen Sie ENERGY_OPTIMIZER_CONFIG_PATH in config/.env "
            "oder legen Sie config/config.json an."
        )
    return "\n".join(lines)


def _abort_config_error(exc: BaseException) -> None:
    print(f"Abbruch: {exc}", file=sys.stderr)
    raise SystemExit(1) from None


def prepare_config_path() -> str:
    """Lädt .env und prüft, dass config.json existiert."""
    from runtime_store.dotenv_loader import load_app_dotenv
    from runtime_store.persist_paths import resolve_config_json_path

    load_app_dotenv()
    config_path = resolve_config_json_path()
    if not os.path.isfile(config_path):
        print(_missing_config_message(config_path), file=sys.stderr)
        raise SystemExit(1)
    return config_path


def load_config_or_exit() -> ModuleType:
    """Importiert config; bei fehlendem Pfad oder ungültigem Inhalt ohne Traceback abbrechen."""
    prepare_config_path()
    try:
        import config as config_module

        return config_module
    except _CONFIG_ERRORS as exc:
        _abort_config_error(exc)


def reinit_config_or_exit(config_module: ModuleType, **kwargs) -> None:
    """Lädt config neu; bei Fehlern ohne Traceback abbrechen."""
    try:
        config_module.reinit_config(**kwargs)
    except _CONFIG_ERRORS as exc:
        _abort_config_error(exc)
