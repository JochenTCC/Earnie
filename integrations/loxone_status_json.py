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


def _unconstrained_export_limit_kw() -> float:
    """Default for ``set_grid_export_power_limit`` when nothing was sent yet.

    ``0`` would mean Einspeisesperre, so fall back to the same "unconstrained" value
    the Live write path sends.
    """
    from optimizer.export_power_limit import (
        EXPORT_LIMIT_UNCONSTRAINED_W,
        export_limit_setpoint_kw,
    )

    try:
        from optimizer.live_export_limit import live_unconstrained_export_kw

        return float(
            export_limit_setpoint_kw(None, unconstrained_kw=live_unconstrained_export_kw())
        )
    except Exception:  # noqa: BLE001 — status JSON must never fail on config
        return EXPORT_LIMIT_UNCONSTRAINED_W / 1000.0


def _plant_status_keys(
    loxone_sent: Mapping[str, float],
    io_to_field: Mapping[str, str],
) -> dict[str, float]:
    payload = {field: 0.0 for field in PLANT_LIVE_WRITE_FIELDS}
    payload["set_grid_export_power_limit"] = _unconstrained_export_limit_kw()
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


def _status_consumer_type(consumer: Mapping[str, Any]) -> str:
    """Type for ``qualified_consumer_id`` (prefer stored type; infer EV/pool)."""
    ctype = str(consumer.get("type") or "").strip()
    if ctype:
        return ctype
    if _consumer_is_ev(consumer):
        return "ev"
    if _consumer_is_pool_filter(consumer) or _consumer_is_pool_heat(consumer):
        return "thermal_rc"
    return ""


def _emit_qualified_peer(
    payload: dict[str, float],
    consumer: Mapping[str, Any],
    kind: str,
    value: float,
) -> None:
    """Emit qualified EHAL ID next to a legacy status key (2.7.q Q2)."""
    from ehal.qualified_ids import qualified_consumer_id

    cid = str(consumer.get("id") or "").strip()
    if not cid:
        return
    qid = qualified_consumer_id(cid, _status_consumer_type(consumer), kind)
    payload[qid] = float(value)


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
            legacy_a = f"ev.{cid}.Earnie_EAuto_Soll_A"
            legacy_mode = f"ev.{cid}.Earnie_EAuto_Modus"
            _emit_if_present(
                payload,
                loxone_sent,
                marker_set_evcs_max_current(as_dict),
                legacy_a,
            )
            _emit_if_present(
                payload,
                loxone_sent,
                marker_set_evcs_mode(as_dict),
                legacy_mode,
            )
            if legacy_a in payload:
                _emit_qualified_peer(
                    payload, as_dict, "set_evcs_max_current", payload[legacy_a]
                )
            if legacy_mode in payload:
                _emit_qualified_peer(
                    payload, as_dict, "set_evcs_mode", payload[legacy_mode]
                )
            continue

        enable = marker_flex_enable(as_dict)
        enable_key = _flex_enable_status_key(cid, enable, as_dict)
        if enable_key:
            value = _sent_enable_value(loxone_sent, enable, enable_key)
            if value is not None:
                payload[enable_key] = value
                _emit_qualified_peer(payload, as_dict, "set_enable", value)
    return payload


def _pool_keys_from_snapshot(loxone_sent: Mapping[str, float]) -> dict[str, float]:
    """Legacy bare pool titles; filter also gets ``pool.pool_filter.set_enable``."""
    from ehal.qualified_ids import POOL_FILTER_ID, qualified_consumer_id

    out: dict[str, float] = {}
    for key in POOL_ENABLE_KEYS:
        if key not in loxone_sent:
            continue
        value = float(loxone_sent[key])
        out[key] = value
        if key == POOL_FILTER_ENABLE_KEY:
            out[qualified_consumer_id(POOL_FILTER_ID, "thermal_rc", "set_enable")] = (
                value
            )
    return out


def _legacy_peer_for_qualified(
    qid: str,
    consumers: Sequence[Mapping[str, Any]],
) -> str | None:
    """Legacy status.json key for a published qualified ID (dual-run)."""
    from ehal.flex_fields import flex_ehal_slug
    from ehal.qualified_ids import field_kind

    parts = str(qid or "").split(".")
    if len(parts) < 3:
        return None
    ns, slug, kind = parts[0], parts[1], field_kind(qid)
    for consumer in consumers:
        if not isinstance(consumer, Mapping):
            continue
        cid = str(consumer.get("id") or "").strip()
        if not cid or flex_ehal_slug(cid) != slug:
            continue
        as_dict = dict(consumer)
        if kind in ("set_evcs_max_current", "set_evcs_mode") and _consumer_is_ev(
            as_dict
        ):
            if kind == "set_evcs_max_current":
                return f"ev.{cid}.Earnie_EAuto_Soll_A"
            return f"ev.{cid}.Earnie_EAuto_Modus"
        if kind == "set_enable":
            enable = marker_flex_enable(as_dict)
            return _flex_enable_status_key(cid, enable, as_dict)
    if ns == "pool" and slug == "pool_filter" and kind == "set_enable":
        return POOL_FILTER_ENABLE_KEY
    return None


def _merge_published_into_payload(
    payload: dict[str, float | int],
    consumers: Sequence[Mapping[str, Any]],
) -> None:
    """Overlay ``write_field`` ledger; dual-emit legacy peers when known."""
    try:
        from integrations.ehal_write import load_published
    except Exception:  # noqa: BLE001
        return
    try:
        published = load_published()
    except Exception:  # noqa: BLE001
        return
    for qid, value in published.items():
        payload[qid] = float(value)
        legacy = _legacy_peer_for_qualified(qid, consumers)
        if legacy:
            payload[legacy] = float(value)


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
    # 2.7.h / 2.7.g physical powerstation writes cached by live hooks: Pattern-B
    # ``ess.{slug}.{kind}`` keys, plus the shared flat Quellenwahl. Flat limit / mode keys
    # stay the house battery's and are never overwritten by a powerstation.
    try:
        from ehal.ess_fields import parse_ess_pattern_b
        from optimizer.powerstation_live import last_powerstation_sent

        for key, value in last_powerstation_sent().items():
            if parse_ess_pattern_b(key) or key == "set_ess_source_select":
                payload[key] = float(value)
    except Exception:  # noqa: BLE001 — status JSON must never fail
        pass
    payload.update(_consumer_status_keys(sent, live_consumers))
    for key, value in _pool_keys_from_snapshot(sent).items():
        payload.setdefault(key, value)
    _merge_published_into_payload(payload, live_consumers)
    return payload
