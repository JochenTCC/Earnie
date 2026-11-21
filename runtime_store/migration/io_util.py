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


def _same_dir(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def pack_file_paths(config_dir: str | Path) -> dict[str, Path]:
    """Where each pack file of ``config_dir`` lives.

    For the active config directory these are the paths the loaders use (the resolvers of
    ``PACK_JSON_FILES``), so a sidecar behind ``EARNIE_*_PATH`` is migrated too. Any other
    directory (pack import, recorder replay, ``--config-dir``) holds its files itself.
    """
    from runtime_store.persist_paths import config_dir as active_config_dir

    root = Path(config_dir)
    if not _same_dir(root, active_config_dir()):
        return {name: root / name for name in PACK_FILENAMES}
    return {name: Path(resolver()) for name, resolver in PACK_JSON_FILES}


def load_pack_docs(config_dir: str | Path) -> Docs:
    """Load the pack JSON files of ``config_dir`` that exist (see ``pack_file_paths``)."""
    from settings.json_io import read_json_dict

    docs: Docs = {}
    for name, path in pack_file_paths(config_dir).items():
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
    paths = pack_file_paths(config_dir)
    names = [name for name in docs if name in PACK_FILENAMES]
    previous: dict[str, bytes | None] = {
        name: (paths[name].read_bytes() if paths[name].is_file() else None) for name in names
    }
    written: list[str] = []
    try:
        for name in names:
            write_json_atomic(paths[name], docs[name])
            written.append(name)
    except BaseException:
        for name in written:
            content = previous[name]
            if content is None:
                paths[name].unlink(missing_ok=True)
            else:
                _write_bytes_atomic(paths[name], content)
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
