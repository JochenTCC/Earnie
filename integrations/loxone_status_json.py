"""Pattern B Virtual In status payload (``GET /ehal/loxone/status.json``)."""
from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from integrations.ehal_debug_mapping import (
    PLANT_LIVE_WRITE_FIELDS,
    build_loxone_setpoint_io_index,
)
from settings.ehal_marker_resolve import (
    marker_flex_enable,
    marker_flex_power_setpoint,
    marker_set_evcs_max_current,
    marker_set_evcs_mode,
)

POOL_ENABLE_KEYS = ("Earnie_Pool_Freigabe", "Earnie_Pool_Filter_Freigabe")


def _as_float_map(raw: Any) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            out[name] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _consumer_is_ev(consumer: Mapping[str, Any]) -> bool:
    if str(consumer.get("type") or "") == "ev":
        return True
    sched = consumer.get("charging_schedule") or {}
    return isinstance(sched, dict) and bool(sched.get("enabled"))


def _live_consumers() -> list[dict]:
    import config

    by_id: dict[str, dict] = {}
    resolved = config.CONFIG.get_resolved_runtime_settings()
    profile = resolved.get("_house_profile") if isinstance(resolved, dict) else None
    if isinstance(profile, dict):
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            cid = str(consumer.get("id") or "").strip()
            if cid:
                by_id[cid] = consumer
    for consumer in config.get_flexible_consumers():
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if cid and cid not in by_id:
            by_id[cid] = consumer
    return list(by_id.values())


def _plant_status_keys(
    loxone_sent: Mapping[str, float],
    io_to_field: Mapping[str, str],
) -> dict[str, float]:
    payload = {field: 0.0 for field in PLANT_LIVE_WRITE_FIELDS}
    for io_name, value in loxone_sent.items():
        field = str(io_to_field.get(io_name) or "").strip()
        if field in payload:
            payload[field] = float(value)
    return payload


def _flex_enable_status_key(consumer_id: str, enable_marker: str) -> str | None:
    marker = str(enable_marker or "").strip()
    if not marker:
        return None
    if marker in POOL_ENABLE_KEYS:
        return marker
    cid = str(consumer_id or "").strip()
    if not cid:
        return None
    lower = marker.lower()
    if "waermepumpe" in lower or marker.startswith("Earnie_WP_"):
        return f"flex.{cid}.Earnie_Waermepumpe_Freigabe"
    return f"flex.{cid}.Earnie_Verbraucher_Freigabe"


def _emit_if_present(
    payload: dict[str, float],
    loxone_sent: Mapping[str, float],
    merker: str,
    status_key: str,
) -> None:
    name = str(merker or "").strip()
    key = str(status_key or "").strip()
    if not name or not key or name not in loxone_sent:
        return
    payload[key] = float(loxone_sent[name])


def _consumer_status_keys(
    loxone_sent: Mapping[str, float],
    consumers: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    payload: dict[str, float] = {}
    for consumer in consumers:
        if not isinstance(consumer, Mapping):
            continue
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        as_dict = dict(consumer)
        if _consumer_is_ev(as_dict):
            _emit_if_present(
                payload,
                loxone_sent,
                marker_set_evcs_max_current(as_dict),
                f"ev.{cid}.Earnie_EAuto_Soll_A",
            )
            _emit_if_present(
                payload,
                loxone_sent,
                marker_set_evcs_mode(as_dict),
                f"ev.{cid}.Earnie_EAuto_Modus",
            )
            continue

        enable = marker_flex_enable(as_dict)
        enable_key = _flex_enable_status_key(cid, enable)
        if enable_key:
            _emit_if_present(payload, loxone_sent, enable, enable_key)

        setpoint = marker_flex_power_setpoint(as_dict)
        _emit_if_present(
            payload,
            loxone_sent,
            setpoint,
            f"flex.{cid}.Earnie_Verbraucher_Ziel_kW",
        )
    return payload


def _pool_keys_from_snapshot(loxone_sent: Mapping[str, float]) -> dict[str, float]:
    return {
        key: float(loxone_sent[key])
        for key in POOL_ENABLE_KEYS
        if key in loxone_sent
    }


def build_loxone_status_payload(
    *,
    loxone_sent: Mapping[str, float] | None = None,
    consumers: Sequence[Mapping[str, Any]] | None = None,
    plant_io_index: Mapping[str, str] | None = None,
    now_ts: float | None = None,
) -> dict[str, float | int]:
    """Build VI status JSON (kW / A / 0|1 / mode; ``heartbeat_ts`` Unix seconds)."""
    if loxone_sent is None:
        from runtime_store import run_state

        state = run_state.load_run_state() or {}
        sent = _as_float_map(state.get("loxone_sent"))
    else:
        sent = _as_float_map(loxone_sent)

    io_index = (
        dict(plant_io_index)
        if plant_io_index is not None
        else build_loxone_setpoint_io_index()
    )
    plant_only = {
        io: field
        for io, field in io_index.items()
        if field in PLANT_LIVE_WRITE_FIELDS
    }

    live_consumers: Sequence[Mapping[str, Any]]
    if consumers is not None:
        live_consumers = consumers
    else:
        live_consumers = _live_consumers()

    payload: dict[str, float | int] = {
        "heartbeat_ts": int(now_ts if now_ts is not None else time.time()),
    }
    payload.update(_plant_status_keys(sent, plant_only))
    payload.update(_consumer_status_keys(sent, live_consumers))
    for key, value in _pool_keys_from_snapshot(sent).items():
        payload.setdefault(key, value)
    return payload
