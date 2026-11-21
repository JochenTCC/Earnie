"""Load / write pack JSONs without stamping (ConfigMigration P1)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime_store.config_pack import PACK_JSON_FILES
from runtime_store.data_model import TARIFF_TRACK_FILES  # noqa: F401  (re-exported)
from runtime_store.migration.types import Docs

PACK_FILENAMES: tuple[str, ...] = tuple(name for name, _ in PACK_JSON_FILES)

# Earnie data-model track; tariff-track files (TARIFF_TRACK_FILES) carry tariff_format.
EARNIE_TRACK_FILES: frozenset[str] = frozenset(
    {
        "config.json",
        "backtesting_scenarios.json",
        "components.json",
        "deviation_rules.json",
        "house_profiles.json",
    }
)
GRID_FEES_FILE = "grid_fees.json"


def load_pack_docs(config_dir: str | Path) -> Docs:
    """Load pack JSON files that exist under ``config_dir``."""
    from settings.json_io import read_json_dict

    root = Path(config_dir)
    docs: Docs = {}
    for name in PACK_FILENAMES:
        path = root / name
        if not path.is_file():
            continue
        raw = read_json_dict(str(path))
        if not isinstance(raw, dict):
            raise ValueError(f"{name}: erwartet JSON-Objekt.")
        docs[name] = raw
    return docs


def write_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    """Write JSON via temp file + replace (no data-model stamp)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.isfile(tmp_name):
            os.unlink(tmp_name)
        raise


def replace_pack_docs(config_dir: str | Path, docs: Docs) -> tuple[str, ...]:
    """Replace the pack files present in ``docs``, each atomically. Returns written names.

    When a write fails, the files already replaced get their previous bytes back (a file
    the call created is removed) and the error is raised: the set is old or new, not mixed.
    """
    root = Path(config_dir)
    names = [name for name in docs if name in PACK_FILENAMES]
    previous: dict[str, bytes | None] = {
        name: ((root / name).read_bytes() if (root / name).is_file() else None) for name in names
    }
    written: list[str] = []
    try:
        for name in names:
            write_json_atomic(root / name, docs[name])
            written.append(name)
    except BaseException:
        for name in written:
            content = previous[name]
            if content is None:
                (root / name).unlink(missing_ok=True)
            else:
                _write_bytes_atomic(root / name, content)
        raise
    return tuple(written)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.isfile(tmp_name):
            os.unlink(tmp_name)
        raise


def stable_json_text(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
