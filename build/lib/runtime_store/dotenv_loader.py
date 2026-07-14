"""Zentrales Laden der .env (config/.env in Prod, Legacy ./.env in Dev)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

from runtime_store.persist_paths import resolve_dotenv_path


def load_app_dotenv(*, override: bool = False) -> str | None:
    """
    Lädt Loxone-Zugangsdaten aus der aufgelösten .env-Datei.

    Returns:
        Pfad der geladenen Datei oder None, wenn keine Datei vorhanden ist.
    """
    path = resolve_dotenv_path()
    if os.path.isdir(path):
        return None
    if not os.path.isfile(path):
        return None
    load_dotenv(path, override=override)
    return path
