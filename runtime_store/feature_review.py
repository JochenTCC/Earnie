"""Anonymous feature-review POST (star ratings) to earnie-server."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from runtime_store.persist_paths_base import feature_reviews_state_file
from runtime_store.server_endpoints import PATH_REVIEW, post_json, resolve_endpoint

logger = logging.getLogger(__name__)

SESSION_SE_SIM_STARTED_KEY = "earnie_se_sim_started"
SESSION_SE_ACTIVE_THIS_RUN_KEY = "se_active_this_script_run"
SESSION_SE_WAS_ACTIVE_KEY = "se_was_active"
SESSION_SE_REVIEW_PENDING_KEY = "se_review_prompt_pending"

REVIEW_ID_SCENARIO_EXPLORER = "scenario_explorer"

PAYLOAD_KEYS_V1 = frozenset({"v", "review_id", "app_version", "ratings", "comment"})
MAX_COMMENT_LEN = 500
MIN_RATINGS = 1
MAX_RATINGS = 3
TIMEOUT_SEC = 5.0

Transport = Callable[[str, bytes, float], int]


def _utc_now(now: datetime | None = None) -> datetime:
    stamp = now if now is not None else datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _app_version() -> str:
    try:
        from version import __version__

        return str(__version__)
    except ImportError:
        return "unknown"


def load_state() -> dict[str, Any]:
    path = feature_reviews_state_file()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("feature_review: cannot read %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("feature_review: state root must be an object: %s", path)
        return {}
    return raw


def save_state(state: dict[str, Any]) -> None:
    path = feature_reviews_state_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def is_review_done(review_id: str) -> bool:
    entry = load_state().get(review_id)
    return isinstance(entry, dict) and bool(entry.get("done_at"))


def mark_review_done(review_id: str, *, sent: bool, now: datetime | None = None) -> None:
    if not review_id or not isinstance(review_id, str):
        raise ValueError("review_id must be a non-empty string")
    state = load_state()
    state[review_id] = {
        "done_at": _utc_now(now).isoformat(),
        "sent": bool(sent),
    }
    save_state(state)


def build_payload(
    *,
    review_id: str,
    ratings: list[int],
    comment: str = "",
) -> dict[str, Any]:
    """Build whitelist JSON; raises ValueError on invalid input."""
    if not isinstance(review_id, str) or not review_id.strip():
        raise ValueError("review_id must be a non-empty string")
    if not isinstance(ratings, list) or not MIN_RATINGS <= len(ratings) <= MAX_RATINGS:
        raise ValueError(f"ratings must be a list of length {MIN_RATINGS}..{MAX_RATINGS}")
    normalized: list[int] = []
    for item in ratings:
        if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 5:
            raise ValueError("each rating must be an int 1..5")
        normalized.append(item)
    if not isinstance(comment, str):
        raise ValueError("comment must be a string")
    if len(comment) > MAX_COMMENT_LEN:
        raise ValueError(f"comment must be <= {MAX_COMMENT_LEN} chars")
    payload = {
        "v": 1,
        "review_id": review_id.strip(),
        "app_version": _app_version(),
        "ratings": normalized,
        "comment": comment,
    }
    if set(payload.keys()) != PAYLOAD_KEYS_V1:
        raise ValueError("feature_review: payload key set drifted from whitelist")
    return payload


def _default_transport(url: str, body: bytes, timeout: float) -> int:
    return post_json(url, body, timeout, log_name="feature_review")


def send_review(
    *,
    review_id: str,
    ratings: list[int],
    comment: str = "",
    transport: Transport | None = None,
    endpoint_url: str | None = None,
) -> None:
    """POST review payload. Raises ValueError/RuntimeError on failure (no silent skip)."""
    url = resolve_endpoint(PATH_REVIEW, endpoint_url)
    payload = build_payload(review_id=review_id, ratings=ratings, comment=comment)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    send = transport if transport is not None else _default_transport
    status = send(url, body, TIMEOUT_SEC)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"feature review POST failed with HTTP status {status}")


def mark_se_simulation_started() -> None:
    """Remember that this browser session started a Szenario-Explorer run."""
    import streamlit as st

    st.session_state[SESSION_SE_SIM_STARTED_KEY] = True


def se_simulation_started() -> bool:
    try:
        import streamlit as st

        return bool(st.session_state.get(SESSION_SE_SIM_STARTED_KEY))
    except Exception:
        return False


def note_se_page_active() -> None:
    """Call from Szenario-Explorer page render each script run."""
    import streamlit as st

    st.session_state[SESSION_SE_ACTIVE_THIS_RUN_KEY] = True
