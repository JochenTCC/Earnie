"""Shadow startup checks and runtime marker (§4.2, §6.5)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from runtime_store.env_vars import read_env, read_runtime_path
from runtime_store.shadow.errors import ShadowStartupError
from runtime_store.shadow.feed import FEED_SCHEMA, feed_dir
from runtime_store.shadow.mode import is_shadow_mode

logger = logging.getLogger(__name__)

SHADOW_MARKER_NAME = ".shadow_runtime"
_SUPPORTED_FEED_SCHEMAS = frozenset({FEED_SCHEMA})


def has_explicit_runtime_dir() -> bool:
    """True when EARNIE_RUNTIME_PATH or EARNIE_ENV_PATH is set."""
    if read_runtime_path():
        return True
    if read_env("ENV_PATH"):
        return True
    return False


def shadow_marker_path(runtime: str | Path | None = None) -> Path:
    from runtime_store.persist_paths import runtime_dir

    root = Path(runtime) if runtime is not None else Path(runtime_dir())
    return root / SHADOW_MARKER_NAME


def ensure_shadow_runtime_marker() -> Path:
    """Create ``{runtime}/.shadow_runtime`` on first Shadow start."""
    path = shadow_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("shadow\n", encoding="utf-8")
        logger.info("shadow: wrote runtime marker %s", path)
    return path


def _load_meta() -> dict:
    path = feed_dir() / "meta.json"
    if not path.is_file():
        raise ShadowStartupError(
            f"Shadow-Feed fehlt: {path} nicht gefunden. "
            "Prod muss mit shadow_feed_enabled=true laufen."
        )
    try:
        text = path.read_text(encoding="utf-8")
        doc = json.loads(text)
    except json.JSONDecodeError:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShadowStartupError(
                f"Shadow-Feed meta.json unlesbar: {exc}"
            ) from exc
    except OSError as exc:
        raise ShadowStartupError(f"Shadow-Feed meta.json unlesbar: {exc}") from exc
    if not isinstance(doc, dict):
        raise ShadowStartupError("Shadow-Feed meta.json: erwartet Objekt")
    return doc


def _check_feed_schema(meta: dict) -> None:
    raw = meta.get("feed_schema")
    try:
        schema = int(raw)
    except (TypeError, ValueError):
        raise ShadowStartupError(
            f"Shadow-Feed: feed_schema ungültig ({raw!r})"
        ) from None
    if schema not in _SUPPORTED_FEED_SCHEMAS:
        raise ShadowStartupError(
            f"Shadow-Feed: feed_schema={schema} nicht unterstützt "
            f"(dieses Build: {sorted(_SUPPORTED_FEED_SCHEMAS)})"
        )


def _check_data_model(meta: dict) -> None:
    from runtime_store.data_model import COMPATIBLE_DATA_MODELS

    raw = meta.get("earnie_data_model")
    try:
        model = int(raw)
    except (TypeError, ValueError):
        raise ShadowStartupError(
            f"Shadow-Feed: earnie_data_model ungültig ({raw!r})"
        ) from None
    if model not in COMPATIBLE_DATA_MODELS:
        raise ShadowStartupError(
            f"Shadow-Feed: earnie_data_model={model} nicht kompatibel "
            f"(unterstützt: {sorted(COMPATIBLE_DATA_MODELS)})"
        )


def _check_runtime_vs_prod(meta: dict) -> None:
    from runtime_store.persist_paths import runtime_dir

    ours = str(Path(runtime_dir()).resolve())
    prod_raw = str(meta.get("prod_runtime_dir") or "").strip()
    if prod_raw:
        prod = str(Path(prod_raw).resolve())
        if os.path.normcase(ours) == os.path.normcase(prod):
            raise ShadowStartupError(
                f"Shadow-Runtime darf nicht Prod-Runtime sein: {ours}"
            )
    marker = shadow_marker_path()
    if marker.is_file():
        return
    # Prod lock without Shadow marker → refuse (risk of sharing Prod runtime)
    lock = Path(runtime_dir()) / "main.lock"
    if lock.is_file():
        raise ShadowStartupError(
            f"Runtime {ours} enthält main.lock ohne {SHADOW_MARKER_NAME} — "
            "vermutlich Prod-Runtime. Bitte EARNIE_RUNTIME_PATH auf ein "
            "eigenes Shadow-Verzeichnis setzen."
        )


def ensure_shadow_startup() -> dict:
    """
    Run §4.2 checks when Shadow is active.

    Returns feed ``meta.json`` on success. Raises ``ShadowStartupError`` on refusal.
    No-op (returns {}) when not in Shadow mode.
    """
    if not is_shadow_mode():
        return {}
    if not has_explicit_runtime_dir():
        raise ShadowStartupError(
            "Shadow-Modus erfordert EARNIE_RUNTIME_PATH oder EARNIE_ENV_PATH "
            "(kein Fallback auf die Standard-Runtime von Prod)."
        )
    meta = _load_meta()
    _check_feed_schema(meta)
    _check_data_model(meta)
    _check_runtime_vs_prod(meta)
    ensure_shadow_runtime_marker()
    logger.info(
        "shadow: startup OK (Prod v%s, feed_schema=%s, cycle_seq=%s)",
        meta.get("earnie_version"),
        meta.get("feed_schema"),
        meta.get("cycle_seq"),
    )
    return meta


def refuse_shadow_startup_or_exit() -> dict:
    """Call from process entrypoints; exits non-zero on failure."""
    try:
        return ensure_shadow_startup()
    except ShadowStartupError as exc:
        logger.error("%s", exc)
        print(f"Abbruch (Shadow): {exc}", flush=True)
        raise SystemExit(1) from exc
