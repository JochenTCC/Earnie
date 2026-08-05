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

POOL_HEAT_ENABLE_KEY = "Earnie_Pool_Freigabe"
POOL_FILTER_ENABLE_KEY = "Earnie_Pool_Filter_Freigabe"
POOL_ENABLE_KEYS = (POOL_HEAT_ENABLE_KEY, POOL_FILTER_ENABLE_KEY)


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


def _consumer_is_pool_filter(consumer: Mapping[str, Any]) -> bool:
    cid = str(consumer.get("id") or "").strip().lower()
    if cid == "pool_filter":
        return True
    if str(consumer.get("daily_target_source") or "") == "loxone_remaining_hours":
        return True
    fsched = consumer.get("filter_schedule")
    return isinstance(fsched, dict) and bool(fsched.get("enabled"))


def _marker_looks_like_pool_filter(marker: str) -> bool:
    lower = marker.lower()
    return (
        "filter" in lower
        and "freigabe" in lower
        and ("swimspa" in lower or "pool" in lower)
    )


def _marker_looks_like_pool_heat(marker: str) -> bool:
    lower = marker.lower()
    if "filter" in lower:
        return False
    if lower == "earnie_pool_freigabe":
        return True
    return "freigabe" in lower and ("swimspa" in lower or lower.endswith("pool_freigabe"))


def _consumer_is_pool_heat(consumer: Mapping[str, Any]) -> bool:
    if _consumer_is_pool_filter(consumer):
        return False
    cid = str(consumer.get("id") or "").strip().lower()
    if cid in ("swimspa", "pool", "pool_swimspa"):
        return True
    return False


def _live_consumers() -> list[dict]:
    """Profile + flex consumers for status payload."""
    from integrations.ehal_debug_mapping import _all_live_consumers

    return _all_live_consumers()


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


def _flex_enable_status_key(
    consumer_id: str,
    enable_marker: str,
    consumer: Mapping[str, Any] | None = None,
) -> str | None:
    """VI Check key for Freigabe (Pool Titles stay bare ``Earnie_Pool_*``)."""
    marker = str(enable_marker or "").strip()
    if not marker:
        return None
    if marker in POOL_ENABLE_KEYS:
        return marker
    as_dict = dict(consumer) if isinstance(consumer, Mapping) else {}
    cid = str(consumer_id or as_dict.get("id") or "").strip()
    if _consumer_is_pool_filter(as_dict) or _marker_looks_like_pool_filter(marker):
        return POOL_FILTER_ENABLE_KEY
    if _consumer_is_pool_heat(as_dict) or _marker_looks_like_pool_heat(marker):
        return POOL_HEAT_ENABLE_KEY
    # pool_swimspa / pool heat ids (greenfield)
    if cid in ("pool_swimspa", "pool"):
        return POOL_HEAT_ENABLE_KEY
    if not cid:
        return None
    lower = marker.lower()
    if "waermepumpe" in lower or marker.startswith("Earnie_WP_"):
        return f"flex.{cid}.Earnie_Waermepumpe_Freigabe"
    return f"flex.{cid}.Earnie_Verbraucher_Freigabe"


def _sent_enable_value(
    loxone_sent: Mapping[str, float],
    primary_marker: str,
    status_key: str,
) -> float | None:
    """Value for status Freigabe — only the configured Freigabe marker or the Pool title."""
    name = str(primary_marker or "").strip()
    if name and name in loxone_sent:
        return float(loxone_sent[name])
    if status_key in POOL_ENABLE_KEYS and status_key in loxone_sent:
        return float(loxone_sent[status_key])
    return None


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
        enable_key = _flex_enable_status_key(cid, enable, as_dict)
        if enable_key:
            value = _sent_enable_value(loxone_sent, enable, enable_key)
            if value is not None:
                payload[enable_key] = value

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
