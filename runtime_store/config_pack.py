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
    TARIFF_TRACK_FILES,
    DataModelError,
    ensure_compatible,
    stamp_data_model,
)
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_deviation_rules_json_path,
    resolve_grid_fees_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
    resolve_uploads_dir,
    resolve_user_grid_fees_json_path,
    resolve_user_tariffs_json_path,
)
from settings.json_io import read_json_dict, write_json_dict

PACK_JSON_FILES: tuple[tuple[str, Any], ...] = (
    ("config.json", resolve_config_json_path),
    ("backtesting_scenarios.json", resolve_backtesting_scenarios_json_path),
    ("components.json", resolve_components_json_path),
    ("deviation_rules.json", resolve_deviation_rules_json_path),
    ("grid_fees.json", resolve_grid_fees_json_path),
    ("user_grid_fees.json", resolve_user_grid_fees_json_path),
    ("house_profiles.json", resolve_house_profiles_json_path),
    ("tariffs.json", resolve_tariffs_json_path),
    ("user_tariffs.json", resolve_user_tariffs_json_path),
)

MANIFEST_NAME = "earnie_config_pack.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_config_pack_bytes(*, for_support: bool = False) -> bytes:
    """Build a zip archive of the config JSON sidecars plus uploads/.

    ``for_support``: the pack goes to the support: secrets are removed
    (``secret_redaction``) and uploads/ (consumption and PV CSVs) stay out.
    """
    from runtime_store.secret_redaction import redact_secrets

    buffer = io.BytesIO()
    file_list: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname, resolver in PACK_JSON_FILES:
            path = resolver()
            if not os.path.isfile(path):
                continue
            doc = read_json_dict(path)
            # Tariff-track file: never stamp earnie_data_model (ConfigMigration).
            if arcname not in TARIFF_TRACK_FILES:
                stamp_data_model(doc)
            if for_support:
                doc = redact_secrets(doc)
            archive.writestr(
                arcname,
                json.dumps(doc, indent=4, ensure_ascii=False) + "\n",
            )
            file_list.append(arcname)
        uploads = Path(resolve_uploads_dir())
        if uploads.is_dir() and not for_support:
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


def _migrate_and_validate_pack_docs(
    json_payloads: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Run the ConfigMigration registry chain, then ensure members are compatible."""
    from runtime_store.migration.runner import MigrationError, migrate_docs_unattended

    try:
        json_payloads = migrate_docs_unattended(json_payloads, label="Config-Paket")
    except MigrationError as exc:
        raise DataModelError(str(exc)) from exc
    for name, doc in json_payloads.items():
        if name in TARIFF_TRACK_FILES:
            continue
        # Compatibility first — never stamp before ensure (would whitewash v1/v2/untagged).
        ensure_compatible(doc, label=name)
        stamp_data_model(doc)
    return json_payloads


def import_config_pack_bytes(payload: bytes) -> list[str]:
    """
    Import a config pack zip into the active config directory.

    Returns the list of written relative names. Raises DataModelError / ValueError
    on invalid packs (no partial write — uses a temp dir then replaces).
    v3 packs are migrated to v4 before validation. After writing, the config is
    reloaded from the live files; if it does not load, the previous files are
    restored and a ValueError is raised (the active config stays usable).
    """
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        manifest, json_payloads = _read_pack_documents(archive, names)
        json_payloads = _migrate_pack_documents(manifest, json_payloads)
        upload_members = [
            n for n in names if n.startswith("uploads/") and not n.endswith("/")
        ]
        for member in upload_members:
            _require_plain_upload_member(member)
        return _write_pack_to_config_dir(archive, json_payloads, upload_members)


def _require_plain_upload_member(member: str) -> None:
    """Reject an ``uploads/`` member whose name would leave the uploads folder.

    The member name becomes a path below the staging dir and then below the live
    uploads dir. ``..``, empty or drive parts and backslashes (a separator on
    Windows) are refused before anything is written.
    """
    parts = member.split("/")
    if (
        "\\" in member
        or ":" in member
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(
            f"Ungültiges Config-Paket: Dateiname '{member}' unter uploads/ ist nicht erlaubt "
            "(kein '..', kein absoluter Pfad, kein Backslash)."
        )


def _read_pack_documents(
    archive: zipfile.ZipFile, names: set[str]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Manifest and the JSON documents of a pack zip (objects only)."""
    if MANIFEST_NAME not in names:
        raise ValueError(f"Ungültiges Config-Paket: '{MANIFEST_NAME}' fehlt.")
    manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Ungültiges Config-Paket: Manifest ist kein Objekt.")

    json_payloads: dict[str, dict[str, Any]] = {}
    for arcname, _resolver in PACK_JSON_FILES:
        if arcname not in names:
            continue
        doc = json.loads(archive.read(arcname).decode("utf-8"))
        if not isinstance(doc, dict):
            raise ValueError(f"Ungültiges Config-Paket: '{arcname}' ist kein Objekt.")
        json_payloads[arcname] = doc
    return manifest, json_payloads


def _migrate_pack_documents(
    manifest: dict[str, Any], json_payloads: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Migrate (when needed) and validate the pack documents; stamps a migrated manifest."""
    from runtime_store.data_model import MIGRATABLE_DATA_MODELS, read_data_model

    manifest_ver = read_data_model(manifest)
    if manifest_ver in MIGRATABLE_DATA_MODELS or any(
        read_data_model(d) in MIGRATABLE_DATA_MODELS for d in json_payloads.values()
    ):
        json_payloads = _migrate_and_validate_pack_docs(json_payloads)
        stamp_data_model(manifest)
    else:
        ensure_compatible(manifest, label=MANIFEST_NAME)
        json_payloads = _migrate_and_validate_pack_docs(json_payloads)
    return json_payloads


def _pack_target_paths(staged_root: Path) -> list[Path]:
    """Live files the staged pack will overwrite or create (JSON sidecars + uploads)."""
    targets: list[Path] = []
    for arcname, resolver in PACK_JSON_FILES:
        if (staged_root / arcname).is_file():
            targets.append(Path(resolver()))
    uploads_src = staged_root / "uploads"
    if uploads_src.is_dir():
        uploads_dest = Path(resolve_uploads_dir())
        for file_path in uploads_src.rglob("*"):
            if file_path.is_file():
                targets.append(uploads_dest / file_path.relative_to(uploads_src))
    return targets


def _snapshot_files(paths: list[Path]) -> dict[Path, bytes | None]:
    """Current bytes of each path; ``None`` marks a file that does not exist yet."""
    return {path: (path.read_bytes() if path.is_file() else None) for path in paths}


def _restore_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    """Put every snapshotted path back: rewrite old bytes, delete files the import created."""
    for path, content in snapshot.items():
        if content is None:
            if path.is_file():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _reload_live_config() -> None:
    """Load the config from the live files, exactly like ``app.py`` does on the next rerun.

    Raises the config loader's errors (``FileNotFoundError``, ``ValueError``,
    ``KeyError``) when the files do not form a loadable config.
    """
    import sys

    module = sys.modules.get("config")
    if module is None:
        # First import builds CONFIG from the live files (a failed import leaves
        # no module behind, so the next call retries the import).
        import config  # noqa: F401
        return
    module.reinit_config()


def _activate_or_roll_back(snapshot: dict[Path, bytes | None]) -> None:
    """Load the just-written config; on failure restore the previous files and raise."""
    from runtime_store.config_load import _CONFIG_ERRORS

    try:
        _reload_live_config()
    except _CONFIG_ERRORS as exc:
        _restore_snapshot(snapshot)
        message = (
            "Config-Paket nicht übernommen: die Konfiguration darin lässt sich nicht "
            f"laden ({_error_text(exc)}). Die bisherige Konfiguration bleibt aktiv."
        )
        try:
            _reload_live_config()
        except _CONFIG_ERRORS as restore_exc:
            raise ValueError(
                f"{message} Hinweis: auch die bisherige Konfiguration lässt sich "
                f"nicht laden ({_error_text(restore_exc)})."
            ) from exc
        raise ValueError(message) from exc


def _error_text(exc: BaseException) -> str:
    """Loader message without the quotes ``str(KeyError)`` adds."""
    if isinstance(exc, KeyError) and len(exc.args) == 1:
        return str(exc.args[0])
    return str(exc)


def _write_pack_to_config_dir(
    archive: zipfile.ZipFile,
    json_payloads: dict[str, dict[str, Any]],
    upload_members: list[str],
) -> list[str]:
    """Stage the pack in a temp dir, copy it into place, and keep it only if it loads.

    The previous live files are snapshotted first; when the imported set does not
    load (cross-file refs, house profile rules, ...), they are restored and a
    ``ValueError`` with the loader's message is raised.
    """
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

        snapshot = _snapshot_files(_pack_target_paths(tmp_root))
        try:
            written = _copy_staged_pack(tmp_root, json_payloads)
        except BaseException:
            _restore_snapshot(snapshot)
            raise
        _activate_or_roll_back(snapshot)
    return written


def _copy_staged_pack(
    tmp_root: Path, json_payloads: dict[str, dict[str, Any]]
) -> list[str]:
    """Copy staged JSON files and uploads into the live config dir."""
    written: list[str] = []
    for arcname, resolver in PACK_JSON_FILES:
        src = tmp_root / arcname
        if not src.is_file():
            continue
        dest = Path(resolver())
        dest.parent.mkdir(parents=True, exist_ok=True)
        if arcname in TARIFF_TRACK_FILES:
            # Tariff-track file: never stamp earnie_data_model (ConfigMigration).
            dest.write_text(
                json.dumps(json_payloads[arcname], indent=4, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
        else:
            write_json_dict(str(dest), json_payloads[arcname])
        written.append(arcname)
    _copy_pack_uploads(tmp_root / "uploads", written)
    return written


def _copy_pack_uploads(uploads_src: Path, written: list[str]) -> None:
    """Copy staged upload files into the uploads dir; appends relative names to ``written``."""
    uploads_dest = Path(resolve_uploads_dir())
    if not uploads_src.is_dir():
        return
    uploads_dest.mkdir(parents=True, exist_ok=True)
    for file_path in uploads_src.rglob("*"):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(uploads_src)
        target = uploads_dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        written.append(f"uploads/{rel.as_posix()}")


def default_pack_filename() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"earnie_config_{stamp}.zip"
