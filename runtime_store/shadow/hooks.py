"""Single entry point for Shadow Mode outside ``runtime_store/shadow/``.

The package has two parts:

- **Core** (always shipped): ``mode``, ``feed``, ``hooks``, ``transport``,
  ``errors``, ``superset``. Prod uses them to record the shadow feed (off unless
  ``shadow_feed_enabled``).
- **Client** (``EARNIE_SHADOW=1`` only): the modules in :data:`CLIENT_FILES`.
  The release image leaves them out (``.dockerignore``); dev builds of
  ``scripts/build_container.py`` add them back.

Code outside the package imports client functions only through this module.
Prod answers come from here without importing the client; Shadow delegates to
the client at call time (module attribute lookup, so tests can patch the
client modules). Shadow without the client refuses to start
(:func:`refuse_shadow_startup_or_exit`) instead of running as Prod.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow import mode as shadow_mode

logger = logging.getLogger(__name__)

# Repo-relative paths left out of the release image; must match ``.dockerignore``.
CLIENT_FILES: tuple[str, ...] = (
    "runtime_store/shadow/cycle.py",
    "runtime_store/shadow/ehal_overlay.py",
    "runtime_store/shadow/reader.py",
    "runtime_store/shadow/replay.py",
    "runtime_store/shadow/startup.py",
    "runtime_store/shadow/writes.py",
    "ui/shadow_banner.py",
)

CLIENT_MISSING_MESSAGE = (
    "Shadow-Modus (EARNIE_SHADOW=1) ist in diesem Build nicht enthalten "
    "(Release-Image ohne Shadow-Laufzeit). Shadow aus einem Entwicklungsstand starten."
)


def record_transport(
    key: str,
    *,
    ok: bool,
    payload: Any = None,
    status: int | None = None,
    error: str | None = None,
) -> None:
    shadow_feed.record(
        key,
        ok=ok,
        payload=payload,
        status=status,
        error=error,
    )


def record_event(key: str, *, payload: Any = None) -> None:
    shadow_feed.record(key, ok=True, payload=payload, status=None, error=None)


# --- client access -----------------------------------------------------------


def client_available() -> bool:
    """True when the Shadow client modules are installed (dev tree, not release image)."""
    try:
        return all(
            importlib.util.find_spec(f"runtime_store.shadow.{name}") is not None
            for name in ("cycle", "ehal_overlay", "reader", "replay", "startup", "writes")
        )
    except ImportError:
        return False


def _client(name: str) -> ModuleType:
    return importlib.import_module(f"runtime_store.shadow.{name}")


# --- startup -----------------------------------------------------------------


def refuse_shadow_startup_or_exit() -> dict:
    """Call from process entrypoints; exits non-zero when Shadow must not start."""
    if not shadow_mode.is_shadow_mode():
        return {}
    if not client_available():
        logger.error("%s", CLIENT_MISSING_MESSAGE)
        print(f"Abbruch (Shadow): {CLIENT_MISSING_MESSAGE}", flush=True)
        raise SystemExit(1)
    return _client("startup").refuse_shadow_startup_or_exit()


def shadow_migration_mode_refusal(plan) -> str | None:
    """German refuse message when Shadow must not open the migration wizard, else None."""
    if not shadow_mode.is_shadow_mode():
        return None
    if not client_available():
        return CLIENT_MISSING_MESSAGE
    return _client("startup").shadow_migration_mode_refusal(plan)


# --- daemon loop glue --------------------------------------------------------


@dataclass(frozen=True)
class ShadowCyclePrep:
    """Result of :func:`prepare_shadow_cycle`."""

    trigger: str
    skipped: bool
    reason: str | None = None


def maybe_flush_after_sampler() -> None:
    """Prod-only sampler flush; never raises to the wait loop."""
    try:
        if not shadow_mode.is_shadow_mode():
            shadow_feed.flush_after_sampler()
    except Exception:  # noqa: BLE001 — never break wait loop
        logger.exception("shadow feed sampler flush failed")


def after_prod_cycle() -> None:
    """Prod-only superset + feed flush after a successful cycle; soft-fail."""
    try:
        from runtime_store.shadow import superset as shadow_superset

        if not shadow_mode.is_shadow_mode():
            shadow_superset.run_after_cycle()
            shadow_feed.flush_after_cycle()
    except Exception:  # noqa: BLE001 — recorder must never break Prod
        logger.exception("shadow feed post-cycle failed")


def maybe_clear_auth_gate() -> bool:
    """If Shadow and auth recovery is needed, clear the gate and return True.

    Prod returns False so ``main`` keeps its live credential probe loop.
    """
    if not shadow_mode.is_shadow_mode():
        return False
    from runtime_store.loxone_auth_error import clear_loxone_auth_error

    clear_loxone_auth_error()
    return True


def prepare_shadow_cycle(next_trigger: str, *, optimize_trigger: str) -> ShadowCyclePrep:
    """Shadow: consume optimize trigger + wait for Prod cycle.

    Non-Shadow: return *next_trigger* unchanged with ``skipped=False``.
    """
    if not shadow_mode.is_shadow_mode():
        return ShadowCyclePrep(trigger=next_trigger, skipped=False)
    cycle = _client("cycle")
    trigger = next_trigger
    if cycle.consume_optimize_trigger():
        trigger = optimize_trigger
    cycle_info = cycle.wait_for_prod_cycle()
    if cycle_info.get("skipped"):
        return ShadowCyclePrep(
            trigger=trigger,
            skipped=True,
            reason=str(cycle_info.get("reason") or "unknown"),
        )
    return ShadowCyclePrep(trigger=trigger, skipped=False)


def resolve_next_trigger(
    early: str | None,
    next_trigger: str,
    *,
    optimize_trigger: str,
) -> str:
    """Merge local early wake with Shadow feed optimize-trigger mirror."""
    if early == optimize_trigger:
        return optimize_trigger
    if shadow_mode.is_shadow_mode() and _client("cycle").consume_optimize_trigger():
        return optimize_trigger
    return next_trigger


# --- writes ------------------------------------------------------------------


def should_invoke_setpoint_writes(*, silent: bool | None = None) -> bool:
    """
    Whether the live cycle should call send_*/EHAL write helpers.

    Plain silent skips them. Shadow implies silent but still invokes the
    primitives so :func:`block_write_if_shadow` can append ``shadow_writes.jsonl``.
    Startup safe setpoints stay suppressed separately.

    Pass ``silent`` from the caller's config instance when available (tests
    often patch ``main.config.is_loxone_silent_mode``).
    """
    if shadow_mode.is_shadow_mode():
        return True
    if silent is None:
        import config as config_mod

        silent = bool(config_mod.is_loxone_silent_mode())
    return not silent


def block_write_if_shadow(
    *,
    backend: str,
    target: str,
    value: Any,
    source: str = "",
) -> bool:
    """If Shadow: log would-write and return True (caller must not send). Prod: False."""
    if not shadow_mode.is_shadow_mode():
        return False
    return _client("writes").block_write_if_shadow(
        backend=backend, target=target, value=value, source=source
    )


# --- replay ------------------------------------------------------------------


def assert_not_shadow_backend(action: str) -> None:
    """Raise if Shadow tries non-replayable backend access; no-op in Prod."""
    if not shadow_mode.is_shadow_mode():
        return
    _client("replay").assert_not_shadow_backend(action)


def lookup_record(key: str, **kwargs: Any) -> dict[str, Any] | None:
    """Fresh feed record for *key* (Shadow); None in Prod (there is no feed to read)."""
    if not shadow_mode.is_shadow_mode():
        return None
    return _client("replay").lookup_record(key, **kwargs)


def warn_missing_feed_key(key: str, reason: str = "missing") -> None:
    """Rate-limited Shadow warning for an unavailable feed key; no-op in Prod."""
    if not shadow_mode.is_shadow_mode():
        return
    _client("replay").warn_missing_feed_key(key, reason)


def replay_ext_payload(key: str, **kwargs: Any) -> Any | None:
    """Shadow-only replay callable for :func:`transport.ext_get`."""
    return _client("replay").replay_ext_payload(key, **kwargs)


def replay_openems_get(key: str) -> dict[str, Any] | None:
    """Shadow-only replay callable for :func:`transport.hub_get`."""
    return _client("replay").replay_openems_get(key)


# --- EHAL overlay (Shadow with read-only shared config only) -----------------


def overlay_path():
    return _client("ehal_overlay").overlay_path()


def read_overlay() -> dict:
    return _client("ehal_overlay").read_overlay()


def write_overlay(doc: dict):
    return _client("ehal_overlay").write_overlay(doc)


def apply_overlay_to_house(doc: dict) -> dict:
    return _client("ehal_overlay").apply_overlay_to_house(doc)


def apply_overlay_to_components(doc: dict) -> dict:
    return _client("ehal_overlay").apply_overlay_to_components(doc)


def upsert_entity_bindings(**kwargs: Any):
    return _client("ehal_overlay").upsert_entity_bindings(**kwargs)
