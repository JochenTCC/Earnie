"""High-rate plant/flex power sampling for QH slot-mean Produktiv-Log Ist."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Callable

from data.live_consumption import build_consumption_snapshot
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from optimizer.slot_duration import DEFAULT_DT_H
from runtime_store.file_metadata import stamp_payload, strip_metadata
from runtime_store.persist_paths import power_interval_sampler_state_file

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_SEC = 30
MIN_SAMPLE_COUNT_FOR_MEAN = 3
_SAMPLER_SCHEMA = 1

_PLANT_KEYS = ("pv_kw", "grid_kw", "battery_kw", "house_kw", "baseload_kw", "flex_sum_kw")


def _state_path() -> str:
    return power_interval_sampler_state_file()


def _save_state(path: str, data: dict[str, Any]) -> None:
    payload = stamp_payload(strip_metadata(data), schema_version=_SAMPLER_SCHEMA)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _load_state(path: str) -> dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return _empty_state()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        return strip_metadata(raw) if isinstance(raw, dict) else _empty_state()
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("power_interval_sampler: state unreadable (%s) — reset.", exc)
        return _empty_state()


def _empty_state() -> dict[str, Any]:
    return {
        "sample_interval_sec": SAMPLE_INTERVAL_SEC,
        "last_tick_at": None,
        "samples": [],
        "energy_anchors": {},
    }


def _default_read_energy() -> dict[str, dict[str, float]] | None:
    """Loxone Meter totals for pv/grid when backend is Loxone; else None."""
    try:
        import config
        from integrations import ehal_live
        from integrations.loxone_meter_energy import (
            plant_energy_meter_names,
            read_plant_energy_readings,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("power_interval_sampler: energy imports failed: %s", exc)
        return None
    if ehal_live.is_ehal_network_backend():
        return None
    if str(config.get("EHAL_BACKEND") or "loxone").strip().lower() not in (
        "",
        "loxone",
        "none",
    ):
        return None
    plant: dict[str, Any] = {}
    try:
        from house_config.profiles_store import load_house_profiles_document
        from runtime_store.persist_paths import resolve_house_profiles_json_path

        path = resolve_house_profiles_json_path()
        if path and os.path.isfile(path):
            doc = load_house_profiles_document(path)
            raw_plant = doc.get("plant") if isinstance(doc, dict) else None
            if isinstance(raw_plant, dict):
                plant = raw_plant
    except Exception as exc:  # noqa: BLE001
        logger.debug("power_interval_sampler: plant load failed: %s", exc)
    names = plant_energy_meter_names(plant=plant, config_get=config.get)
    if not names:
        return None
    readings = read_plant_energy_readings(names)
    return readings or None


def _note_energy_open_anchor(
    state: dict[str, Any],
    *,
    moment: datetime,
    read_energy: Callable[[], dict[str, dict[str, float]] | None] | None,
) -> None:
    slot = quarter_hour_slot_start(moment)
    slot = slot.replace(tzinfo=None) if slot.tzinfo else slot
    key = _iso(slot)
    anchors = dict(state.get("energy_anchors") or {})
    if key in anchors:
        return
    reader = read_energy if read_energy is not None else _default_read_energy
    try:
        readings = reader()
    except Exception as exc:  # noqa: BLE001
        logger.debug("power_interval_sampler: energy open read failed: %s", exc)
        return
    if not readings:
        return
    anchors[key] = {"open": readings, "open_ts": _iso(moment)}
    state["energy_anchors"] = anchors


def _overlay_energy_counters(
    closed: dict[str, Any],
    *,
    interval_start: datetime,
    state: dict[str, Any],
    read_energy: Callable[[], dict[str, dict[str, float]] | None] | None,
) -> dict[str, Any]:
    from integrations.loxone_meter_energy import overlay_counter_on_closed

    key = _iso(interval_start)
    anchors = dict(state.get("energy_anchors") or {})
    open_payload = anchors.pop(key, None)
    state["energy_anchors"] = anchors
    open_readings = None
    if isinstance(open_payload, dict):
        raw_open = open_payload.get("open")
        if isinstance(raw_open, dict):
            open_readings = raw_open
    if not open_readings:
        out = dict(closed)
        out["ist_power_source"] = {
            "pv": "mean",
            "grid": "mean",
            "battery": "mean",
            "house": "mean",
            "baseload": "mean",
            "flex": "mean",
        }
        return out
    reader = read_energy if read_energy is not None else _default_read_energy
    end_readings = None
    try:
        end_readings = reader()
    except Exception as exc:  # noqa: BLE001
        logger.debug("power_interval_sampler: energy close read failed: %s", exc)
    return overlay_counter_on_closed(
        closed,
        open_readings=open_readings,
        end_readings=end_readings,
        dt_h=DEFAULT_DT_H,
    )


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat(timespec="seconds")


def _sample_from_snapshot(
    snapshot: dict[str, Any],
    *,
    now: datetime,
    soc_percent: float | None,
) -> dict[str, Any]:
    flex = snapshot.get("flex_kw") or {}
    sample: dict[str, Any] = {
        "ts": _iso(now),
        "pv_kw": float(snapshot.get("pv_kw") or 0.0),
        "grid_kw": float(snapshot.get("grid_kw") or 0.0),
        "battery_kw": float(snapshot.get("battery_kw") or 0.0),
        "house_kw": float(snapshot.get("house_kw") or 0.0),
        "baseload_kw": float(snapshot.get("baseload_kw") or 0.0),
        "flex_sum_kw": float(snapshot.get("flex_sum_kw") or 0.0),
        "flex_kw": {str(k): float(v) for k, v in flex.items()},
    }
    if soc_percent is not None:
        sample["soc_percent"] = float(soc_percent)
    return sample


def _read_live_sample(
    *,
    now: datetime,
    read_plant: Callable[[], dict[str, float] | None] | None = None,
    read_soc: Callable[[], float | None] | None = None,
    read_flex_chart: Callable[[], dict[str, float]] | None = None,
) -> dict[str, Any] | None:
    from integrations import ehal_live

    plant_fn = read_plant or ehal_live.read_live_power_kw
    soc_fn = read_soc or ehal_live.read_ess_soc
    live_power = plant_fn()
    if not live_power:
        return None
    flex_kw: dict[str, float] = {}
    if read_flex_chart is not None:
        flex_kw = dict(read_flex_chart())
    elif not ehal_live.is_ehal_network_backend():
        from integrations import loxone_client

        flex_kw = dict(
            loxone_client.resolve_flexible_consumers_live_power(fallbacks={}).chart_kw
        )
    snapshot = build_consumption_snapshot(live_power, flex_kw)
    soc = None
    try:
        soc = soc_fn()
    except Exception as exc:  # noqa: BLE001 — best-effort SoC on sample tick
        logger.debug("power_interval_sampler: SoC read failed: %s", exc)
    return _sample_from_snapshot(snapshot, now=now, soc_percent=soc)


def _append_sample(state: dict[str, Any], sample: dict[str, Any]) -> None:
    samples = list(state.get("samples") or [])
    samples.append(sample)
    state["samples"] = samples


def _samples_in_interval(
    samples: list[dict[str, Any]],
    interval_start: datetime,
) -> list[dict[str, Any]]:
    start = interval_start.replace(tzinfo=None) if interval_start.tzinfo else interval_start
    end = start + timedelta(minutes=QUARTER_HOUR_MINUTES)
    matched: list[dict[str, Any]] = []
    for sample in samples:
        ts = _parse_ts(sample.get("ts"))
        if ts is None:
            continue
        if start <= ts < end:
            matched.append(sample)
    return matched


def _mean_float(samples: list[dict[str, Any]], key: str) -> float:
    values = [float(s.get(key) or 0.0) for s in samples]
    return round(sum(values) / len(values), 3)


def _mean_flex(samples: list[dict[str, Any]]) -> dict[str, float]:
    keys: set[str] = set()
    for sample in samples:
        keys.update((sample.get("flex_kw") or {}).keys())
    means: dict[str, float] = {}
    for key in sorted(keys):
        values = [float((s.get("flex_kw") or {}).get(key) or 0.0) for s in samples]
        means[str(key)] = round(sum(values) / len(values), 3)
    return means


def _build_closed_interval(
    interval_start: datetime,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    means = {key: _mean_float(samples, key) for key in _PLANT_KEYS}
    flex_mean = _mean_flex(samples)
    dt_h = DEFAULT_DT_H
    closed: dict[str, Any] = {
        "interval_start": _iso(interval_start),
        "sample_count": len(samples),
        "sample_interval_sec": SAMPLE_INTERVAL_SEC,
        **means,
        "flex_kw": flex_mean,
        "pv_energy_kwh": round(means["pv_kw"] * dt_h, 4),
        "grid_energy_kwh": round(means["grid_kw"] * dt_h, 4),
        "battery_energy_kwh": round(means["battery_kw"] * dt_h, 4),
        "house_energy_kwh": round(means["house_kw"] * dt_h, 4),
        "baseload_energy_kwh": round(means["baseload_kw"] * dt_h, 4),
    }
    socs = [
        float(s["soc_percent"])
        for s in samples
        if s.get("soc_percent") is not None
    ]
    if socs:
        closed["soc_start_percent"] = round(socs[0], 2)
        closed["soc_end_percent"] = round(socs[-1], 2)
    return closed


def tick(
    *,
    now: datetime | None = None,
    force: bool = False,
    state_path: str | None = None,
    read_plant: Callable[[], dict[str, float] | None] | None = None,
    read_soc: Callable[[], float | None] | None = None,
    read_flex_chart: Callable[[], dict[str, float]] | None = None,
    read_energy: Callable[[], dict[str, dict[str, float]] | None] | None = None,
) -> bool:
    """Sample plant/flex/SoC when SAMPLE_INTERVAL_SEC elapsed (or force)."""
    path = state_path or _state_path()
    moment = now or datetime.now()
    moment = moment.replace(tzinfo=None) if moment.tzinfo else moment
    state = _load_state(path)
    last = _parse_ts(state.get("last_tick_at"))
    if (
        not force
        and last is not None
        and (moment - last).total_seconds() < SAMPLE_INTERVAL_SEC
    ):
        return False
    try:
        sample = _read_live_sample(
            now=moment,
            read_plant=read_plant,
            read_soc=read_soc,
            read_flex_chart=read_flex_chart,
        )
    except Exception as exc:  # noqa: BLE001 — never break the wait loop
        logger.warning("power_interval_sampler: tick failed: %s", exc)
        return False
    if sample is None:
        state["last_tick_at"] = _iso(moment)
        _save_state(path, state)
        return False
    _append_sample(state, sample)
    _note_energy_open_anchor(state, moment=moment, read_energy=read_energy)
    state["last_tick_at"] = _iso(moment)
    state["sample_interval_sec"] = SAMPLE_INTERVAL_SEC
    _save_state(path, state)
    return True


def note_decision_sample(
    snapshot: dict[str, Any] | None,
    *,
    soc_percent: float | None = None,
    now: datetime | None = None,
    state_path: str | None = None,
) -> None:
    """Count the QH decision-time snapshot toward the open interval."""
    if not snapshot:
        return
    path = state_path or _state_path()
    moment = now or datetime.now()
    moment = moment.replace(tzinfo=None) if moment.tzinfo else moment
    state = _load_state(path)
    _append_sample(
        state,
        _sample_from_snapshot(snapshot, now=moment, soc_percent=soc_percent),
    )
    _save_state(path, state)


def finalize_closed_interval(
    interval_start: datetime,
    *,
    state_path: str | None = None,
    read_energy: Callable[[], dict[str, dict[str, float]] | None] | None = None,
) -> dict[str, Any] | None:
    """Mean/energy for ``[interval_start, interval_start+QH)``; drop those samples."""
    path = state_path or _state_path()
    start = quarter_hour_slot_start(interval_start)
    start = start.replace(tzinfo=None) if start.tzinfo else start
    state = _load_state(path)
    samples = list(state.get("samples") or [])
    matched = _samples_in_interval(samples, start)
    if not matched:
        return None
    closed = _build_closed_interval(start, matched)
    closed = _overlay_energy_counters(
        closed,
        interval_start=start,
        state=state,
        read_energy=read_energy,
    )
    end = start + timedelta(minutes=QUARTER_HOUR_MINUTES)
    kept: list[dict[str, Any]] = []
    for sample in samples:
        ts = _parse_ts(sample.get("ts"))
        if ts is None or not (start <= ts < end):
            kept.append(sample)
    state["samples"] = kept
    _save_state(path, state)
    logger.info(
        "power_interval_sampler: closed %s samples=%d pv=%.3f kW src=%s",
        closed["interval_start"],
        closed["sample_count"],
        closed["pv_kw"],
        (closed.get("ist_power_source") or {}).get("pv", "mean"),
    )
    return closed
