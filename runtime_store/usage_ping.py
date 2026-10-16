"""Opt-in anonymous usage ping client (UsagePing P1–P3).

State lives in ``runtime/usage_ping.json``. Nothing is sent unless consent is
``on`` and ``EARNIE_USAGE_PING`` is not ``off``. See ``docs/spec/usage-ping.md``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

from runtime_store.env_vars import read_env
from runtime_store.install_context import detect_install_context
from runtime_store.persist_paths import usage_ping_state_file

logger = logging.getLogger(__name__)

Consent = Literal["unset", "on", "off"]
Stage = Literal["explorer", "live"]

PAYLOAD_KEYS = frozenset({"v", "id", "app_version", "context", "stage"})
VALID_STAGES = frozenset({"explorer", "live"})
_STAGE_RANK = {"explorer": 0, "live": 1}

TIMEOUT_SEC = 5.0
RETRY_AFTER = timedelta(hours=1)

Transport = Callable[[str, bytes, float], int]

_send_lock = threading.Lock()
_send_in_flight = False


def _utc_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _utc_date_str(now: datetime) -> str:
    return _utc_now(now).date().isoformat()


def _parse_iso(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _atomic_replace_unavailable(exc: OSError) -> bool:
    if getattr(exc, "errno", None) in (13, 16):
        return True
    return getattr(exc, "winerror", None) == 5


def _write_json_direct(path: str, data: dict[str, Any]) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def load_state() -> dict[str, Any]:
    """Load usage-ping state; missing file means consent ``unset``."""
    path = usage_ping_state_file()
    if not os.path.isfile(path):
        return {"consent": "unset"}
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: usage_ping state must be a JSON object")
    out = dict(raw)
    if "consent" not in out:
        out["consent"] = "unset"
    return out


def save_state(state: dict[str, Any]) -> None:
    """Atomically write usage-ping state (SMB/Windows fallback)."""
    path = usage_ping_state_file()
    tmp = f"{path}.tmp"
    try:
        _write_json_direct(tmp, state)
        os.replace(tmp, path)
    except OSError as exc:
        if not _atomic_replace_unavailable(exc):
            raise
        logger.warning(
            "usage_ping: atomic replace to %s failed (%s), writing directly",
            path,
            exc,
        )
        _write_json_direct(path, state)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def is_kill_switch_off() -> bool:
    return read_env("USAGE_PING").lower() == "off"


def endpoint_url_from_env() -> str:
    return read_env("USAGE_PING_URL")


def set_consent(value: Literal["on", "off"], *, now: datetime | None = None) -> dict[str, Any]:
    """Opt in (mint install ID) or opt out (wipe install ID)."""
    state = load_state()
    stamp = _utc_now(now)
    if value == "on":
        state["consent"] = "on"
        state["consent_at"] = _utc_date_str(stamp)
        if not str(state.get("install_id") or "").strip():
            state["install_id"] = str(uuid.uuid4())
        if state.get("stage") not in VALID_STAGES:
            state["stage"] = "explorer"
    else:
        state["consent"] = "off"
        state.pop("install_id", None)
    save_state(state)
    return state


def set_highest_stage(stage: Stage) -> dict[str, Any]:
    """Raise stored stage monotonically (explorer → live). For UsagePing P2."""
    if stage not in VALID_STAGES:
        raise ValueError(f"invalid stage: {stage!r}")
    state = load_state()
    current = str(state.get("stage") or "explorer")
    if current not in VALID_STAGES:
        current = "explorer"
    if _STAGE_RANK[stage] >= _STAGE_RANK[current]:
        state["stage"] = stage
    else:
        state["stage"] = current
    save_state(state)
    return state


def _app_version() -> str:
    try:
        from version import __version__

        return str(__version__)
    except ImportError:
        return "unknown"


PREVIEW_ID_PLACEHOLDER = "<wird bei Zustimmung erzeugt>"


def build_payload(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the fixed v1 payload whitelist from state."""
    data = state if state is not None else load_state()
    install_id = str(data.get("install_id") or "").strip()
    if not install_id:
        raise ValueError("usage_ping: install_id missing; consent must be on")
    stage = str(data.get("stage") or "explorer")
    if stage not in VALID_STAGES:
        raise ValueError(f"usage_ping: invalid stage {stage!r}")
    payload = {
        "v": 1,
        "id": install_id,
        "app_version": _app_version(),
        "context": detect_install_context(),
        "stage": stage,
    }
    if set(payload.keys()) != PAYLOAD_KEYS:
        raise ValueError("usage_ping: payload key set drifted from whitelist")
    return payload


def preview_payload(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """UI transparency payload (never sent). Uses placeholder id until opt-in."""
    data = state if state is not None else load_state()
    install_id = str(data.get("install_id") or "").strip()
    stage = str(data.get("stage") or "explorer")
    if stage not in VALID_STAGES:
        stage = "explorer"
    payload = {
        "v": 1,
        "id": install_id or PREVIEW_ID_PLACEHOLDER,
        "app_version": _app_version(),
        "context": detect_install_context(),
        "stage": stage,
    }
    if set(payload.keys()) != PAYLOAD_KEYS:
        raise ValueError("usage_ping: preview key set drifted from whitelist")
    return payload


def _default_transport(url: str, body: bytes, timeout: float) -> int:
    request = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return int(response.getcode())
    except urllib_error.HTTPError as exc:
        return int(exc.code)
    except (urllib_error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("usage_ping: transport failed: %s", exc)
        return 0


def _should_attempt(state: dict[str, Any], now: datetime) -> bool:
    if is_kill_switch_off():
        return False
    if str(state.get("consent") or "unset") != "on":
        return False
    today = _utc_date_str(now)
    if str(state.get("last_sent_date") or "") == today:
        return False
    last_attempt = _parse_iso(state.get("last_attempt_at"))
    if last_attempt is not None and (now - last_attempt) < RETRY_AFTER:
        return False
    return True


def maybe_send_ping(
    now: datetime | None = None,
    *,
    transport: Transport | None = None,
    endpoint_url: str | None = None,
) -> bool:
    """Attempt one daily ping when gates allow. Returns True on HTTP 2xx."""
    stamp = _utc_now(now)
    state = load_state()
    if not _should_attempt(state, stamp):
        return False

    url = (endpoint_url if endpoint_url is not None else endpoint_url_from_env()).strip()
    send = transport if transport is not None else _default_transport
    if not url and transport is None:
        logger.warning("usage_ping: EARNIE_USAGE_PING_URL unset; skip send")
        return False

    try:
        payload = build_payload(state)
    except ValueError as exc:
        logger.warning("usage_ping: cannot build payload: %s", exc)
        return False

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    status = send(url, body, TIMEOUT_SEC)
    state["last_attempt_at"] = stamp.isoformat()
    if 200 <= int(status) < 300:
        state["last_sent_date"] = _utc_date_str(stamp)
        save_state(state)
        return True
    save_state(state)
    logger.warning("usage_ping: send failed with status %s", status)
    return False


def note_explorer_activated() -> None:
    """Record Scenario Editor activation milestone (explorer stage)."""
    try:
        set_highest_stage("explorer")
    except Exception as exc:
        logger.warning("usage_ping: explorer activation failed: %s", exc)


def note_explorer_success() -> None:
    """Alias for ``note_explorer_activated`` (legacy call sites)."""
    note_explorer_activated()


def note_scenarios_calculated(n: int) -> None:
    """Bump local scenario-calc counter; force same-day ping when consent is on.

    Requires ``n > 0``. Clears ``last_sent_date`` and ``last_attempt_at`` so a
    successful calc can POST again the same UTC day (and bypass the 1 h retry
    gate). Wire payload stays unchanged (counter is local only).
    """
    if int(n) <= 0:
        raise ValueError(f"usage_ping: scenarios calculated count must be > 0, got {n!r}")
    try:
        state = load_state()
        current = int(state.get("scenarios_calc_count") or 0)
        state["scenarios_calc_count"] = current + int(n)
        if str(state.get("consent") or "unset") == "on":
            state.pop("last_sent_date", None)
            state.pop("last_attempt_at", None)
        save_state(state)
        if str(state.get("consent") or "unset") == "on" and not is_kill_switch_off():
            spawn_maybe_send_ping()
    except Exception as exc:
        logger.warning("usage_ping: scenarios_calc_count bump failed: %s", exc)


def note_live_cycle_success() -> None:
    """Record live-cycle milestone after a successful non-shadow run_state save."""
    try:
        from runtime_store.shadow.mode import is_shadow_mode

        if is_shadow_mode():
            return
        set_highest_stage("live")
    except Exception as exc:
        logger.warning("usage_ping: live milestone failed: %s", exc)


def _run_maybe_send_ping() -> None:
    global _send_in_flight
    try:
        maybe_send_ping()
    except Exception as exc:
        logger.warning("usage_ping: spawn send failed: %s", exc)
    finally:
        with _send_lock:
            _send_in_flight = False


def spawn_maybe_send_ping() -> bool:
    """Start at most one daemon thread for ``maybe_send_ping``. Returns True if started."""
    global _send_in_flight
    with _send_lock:
        if _send_in_flight:
            return False
        _send_in_flight = True
    thread = threading.Thread(
        target=_run_maybe_send_ping,
        name="usage-ping",
        daemon=True,
    )
    thread.start()
    return True


def reset_send_in_flight_for_tests() -> None:
    """Clear the in-flight flag (unit tests only)."""
    global _send_in_flight
    with _send_lock:
        _send_in_flight = False
