"""Export/import of Earnie config packs (zip of JSON sidecars + uploads/)."""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_store.data_model import (
    CURRENT_DATA_MODEL,
    DATA_MODEL_KEY,
    DataModelError,
    ensure_compatible,
    stamp_data_model,
)
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_deviation_rules_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
    resolve_uploads_dir,
)
from settings.json_io import read_json_dict, write_json_dict

PACK_JSON_FILES: tuple[tuple[str, Any], ...] = (
    ("config.json", resolve_config_json_path),
    ("backtesting_scenarios.json", resolve_backtesting_scenarios_json_path),
    ("components.json", resolve_components_json_path),
    ("deviation_rules.json", resolve_deviation_rules_json_path),
    ("house_profiles.json", resolve_house_profiles_json_path),
    ("tariffs.json", resolve_tariffs_json_path),
)

MANIFEST_NAME = "earnie_config_pack.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_config_pack_bytes() -> bytes:
    """Build a zip archive of the six config JSONs plus uploads/."""
    buffer = io.BytesIO()
    file_list: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname, resolver in PACK_JSON_FILES:
            path = resolver()
            if not os.path.isfile(path):
                continue
            doc = read_json_dict(path)
            stamp_data_model(doc)
            archive.writestr(
                arcname,
                json.dumps(doc, indent=4, ensure_ascii=False) + "\n",
            )
            file_list.append(arcname)
        uploads = Path(resolve_uploads_dir())
        if uploads.is_dir():
            for file_path in sorted(uploads.rglob("*")):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(uploads).as_posix()
                arc = f"uploads/{rel}"
                archive.write(file_path, arcname=arc)
                file_list.append(arc)
        manifest = {
            DATA_MODEL_KEY: CURRENT_DATA_MODEL,
            "created_at": _utc_now_iso(),
            "files": file_list,
        }
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )
    return buffer.getvalue()


def _validate_pack_member(name: str, doc: dict[str, Any]) -> None:
    ensure_compatible(doc, label=name)


def import_config_pack_bytes(payload: bytes) -> list[str]:
    """
    Import a config pack zip into the active config directory.

    Returns the list of written relative names. Raises DataModelError / ValueError
    on invalid packs (no partial write — uses a temp dir then replaces).
    """
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        if MANIFEST_NAME not in names:
            raise ValueError(f"Ungültiges Config-Paket: '{MANIFEST_NAME}' fehlt.")
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Ungültiges Config-Paket: Manifest ist kein Objekt.")
        ensure_compatible(manifest, label=MANIFEST_NAME)

        json_payloads: dict[str, dict[str, Any]] = {}
        for arcname, _resolver in PACK_JSON_FILES:
            if arcname not in names:
                continue
            doc = json.loads(archive.read(arcname).decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError(f"Ungültiges Config-Paket: '{arcname}' ist kein Objekt.")
            _validate_pack_member(arcname, doc)
            stamp_data_model(doc)
            json_payloads[arcname] = doc

        upload_members = [
            n for n in names if n.startswith("uploads/") and not n.endswith("/")
        ]

        with tempfile.TemporaryDirectory(prefix="earnie_pack_") as tmp:
            tmp_root = Path(tmp)
            for arcname, doc in json_payloads.items():
                dest = tmp_root / arcname
                dest.write_text(
                    json.dumps(doc, indent=4, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            for member in upload_members:
                target = tmp_root / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

            written: list[str] = []
            for arcname, resolver in PACK_JSON_FILES:
                src = tmp_root / arcname
                if not src.is_file():
                    continue
                dest = Path(resolver())
                dest.parent.mkdir(parents=True, exist_ok=True)
                write_json_dict(str(dest), json_payloads[arcname])
                written.append(arcname)

            uploads_dest = Path(resolve_uploads_dir())
            uploads_src = tmp_root / "uploads"
            if uploads_src.is_dir():
                uploads_dest.mkdir(parents=True, exist_ok=True)
                for file_path in uploads_src.rglob("*"):
                    if not file_path.is_file():
                        continue
                    rel = file_path.relative_to(uploads_src)
                    target = uploads_dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, target)
                    written.append(f"uploads/{rel.as_posix()}")

    return written


def default_pack_filename() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"earnie_config_{stamp}.zip"
