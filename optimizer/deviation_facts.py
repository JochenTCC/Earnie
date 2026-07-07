"""Normalisierte Slot-Fakten für Soll/Ist-Abweichungen (Epic Soll-Ist)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import config
from optimizer import battery as bat
from optimizer.consumer_power import loxone_control_outputs, uses_power_setpoint, uses_pv_follow
from runtime_store.history_timeline import SLOT_PRESENT


@dataclass(frozen=True)
class FlexPowerFacts:
    soll_kw: float
    ist_kw: float
    mismatch_kw: float
    pv_follow_soll: int | None = None
    loxone_setpoint_kw: float | None = None
    nominal_power_kw: float | None = None


@dataclass(frozen=True)
class FilterWindowFacts:
    """Natives Filterfenster (SwimSpa) eines Slots — aus dem Log-Eintrag."""
    native_start_hour: float | None
    native_duration_hours: float | None


@dataclass(frozen=True)
class ThermalFacts:
    actual_c: float | None
    band_min: float | None
    band_max: float | None
    heating_scheduled: bool


@dataclass(frozen=True)
class BatteryFacts:
    soll_mode: int
    soll_power_kw: float
    soll_plan_kw: float
    ist_power_kw: float


@dataclass(frozen=True)
class SlotDeviationFacts:
    slot_quality: str
    consumers: dict[str, FlexPowerFacts]
    battery: BatteryFacts
    thermal: dict[str, ThermalFacts]
    charging_contexts: dict[str, dict[str, Any]]
    consumer_remaining_kwh: dict[str, float]
    filter_windows: dict[str, FilterWindowFacts]
    slot_start: datetime | None


def _float_or_zero(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _consumer_ids_from_entry(entry: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    ids.update((entry.get("consumer_powers_kw") or {}).keys())
    ids.update((entry.get("flex_live_kw") or {}).keys())
    snapshot = entry.get("consumption_snapshot") or {}
    ids.update((snapshot.get("flex_kw") or {}).keys())
    for item in entry.get("thermal_observability") or []:
        if isinstance(item, dict) and item.get("consumer_id"):
            ids.add(str(item["consumer_id"]))
    if not ids:
        for consumer in config.get_flexible_consumers(optimizer_only=True):
            ids.add(consumer["id"])
    return ids


def _soll_flex_kw(entry: dict[str, Any], consumer_id: str) -> float:
    powers = entry.get("consumer_powers_kw") or {}
    if consumer_id in powers:
        return _float_or_zero(powers[consumer_id])
    return 0.0


def _consumer_config(consumer_id: str) -> dict | None:
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        if consumer["id"] == consumer_id:
            return consumer
    return None


def _effective_planned_kw(entry: dict[str, Any], consumer_id: str) -> float:
    planned = _soll_flex_kw(entry, consumer_id)
    ctx = (entry.get("charging_contexts") or {}).get(consumer_id) or {}
    if ctx.get("active") is False:
        return 0.0
    return planned


def _pv_follow_soll(
    entry: dict[str, Any],
    consumer_id: str,
    consumer: dict | None,
) -> int | None:
    if consumer is None or not uses_pv_follow(consumer):
        return None
    return int((entry.get("consumer_pv_follow") or {}).get(consumer_id, 0) or 0)


def _loxone_setpoint_kw(
    entry: dict[str, Any],
    consumer_id: str,
    consumer: dict | None,
) -> float | None:
    if consumer is None or not uses_power_setpoint(consumer):
        return None
    sent = entry.get("loxone_sent") or {}
    setpoint_name = str((consumer.get("loxone_outputs") or {}).get("power_setpoint_name", "")).strip()
    if setpoint_name and setpoint_name in sent:
        return _float_or_zero(sent[setpoint_name])
    pv_follow = int((entry.get("consumer_pv_follow") or {}).get(consumer_id, 0) or 0)
    planned = _effective_planned_kw(entry, consumer_id)
    setpoint, _ = loxone_control_outputs(consumer, planned, pv_follow)
    return setpoint


def _ist_flex_kw(entry: dict[str, Any], consumer_id: str) -> float:
    snapshot = entry.get("consumption_snapshot") or {}
    flex_kw = snapshot.get("flex_kw") or {}
    if consumer_id in flex_kw:
        return _float_or_zero(flex_kw[consumer_id])
    live = entry.get("flex_live_kw") or {}
    return _float_or_zero(live.get(consumer_id))


def _nominal_power_kw(consumer: dict | None) -> float | None:
    if consumer is None:
        return None
    value = consumer.get("nominal_power_kw")
    if value is None:
        return None
    return float(value)


def _filter_windows(entry: dict[str, Any], consumer_ids: set[str]) -> dict[str, FilterWindowFacts]:
    """Natives Filterfenster je Verbraucher aus dem geloggten filter_contexts-Block."""
    logged = entry.get("filter_contexts") or {}
    windows: dict[str, FilterWindowFacts] = {}
    for consumer_id in consumer_ids:
        ctx = logged.get(consumer_id)
        if not isinstance(ctx, dict):
            continue
        start = ctx.get("native_start_hour")
        duration = ctx.get("native_duration_hours")
        windows[consumer_id] = FilterWindowFacts(
            native_start_hour=None if start is None else float(start),
            native_duration_hours=None if duration is None else float(duration),
        )
    return windows


def _thermal_by_consumer(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in entry.get("thermal_observability") or []:
        if isinstance(item, dict) and item.get("consumer_id"):
            indexed[str(item["consumer_id"])] = item
    return indexed


def _thermal_facts(item: dict[str, Any] | None) -> ThermalFacts:
    if not item:
        return ThermalFacts(None, None, None, False)
    readings = item.get("readings_c") or {}
    schedule = item.get("heating_schedule") or []
    heating_scheduled = bool(item.get("heating_hours")) or (0 in schedule)
    return ThermalFacts(
        actual_c=readings.get("actual"),
        band_min=readings.get("band_min"),
        band_max=readings.get("band_max"),
        heating_scheduled=heating_scheduled,
    )


def _battery_plan_kw(entry: dict[str, Any]) -> float:
    if entry.get("battery_plan_kw") is not None:
        return _float_or_zero(entry["battery_plan_kw"])
    mode = int(entry.get("mode", bat.MODE_AUTOMATIK))
    target_power = _float_or_zero(entry.get("target_power_kw"))
    if mode == bat.MODE_ZWANGS_LADEN:
        return target_power
    if mode == bat.MODE_ZWANGS_ENTLADEN:
        return -target_power
    return 0.0


def _battery_facts(entry: dict[str, Any]) -> BatteryFacts:
    snapshot = entry.get("consumption_snapshot") or {}
    return BatteryFacts(
        soll_mode=int(entry.get("mode", bat.MODE_AUTOMATIK)),
        soll_power_kw=_float_or_zero(entry.get("target_power_kw")),
        soll_plan_kw=_battery_plan_kw(entry),
        ist_power_kw=_float_or_zero(snapshot.get("battery_kw")),
    )


def build_slot_deviation_facts(
    entry: dict[str, Any],
    *,
    slot_quality: str = SLOT_PRESENT,
    slot_start: datetime | None = None,
) -> SlotDeviationFacts:
    """Extrahiert Vergleichsfakten aus einem Produktiv-Log-Eintrag."""
    consumers: dict[str, FlexPowerFacts] = {}
    for consumer_id in sorted(_consumer_ids_from_entry(entry)):
        consumer = _consumer_config(consumer_id)
        soll_kw = _soll_flex_kw(entry, consumer_id)
        ist_kw = _ist_flex_kw(entry, consumer_id)
        consumers[consumer_id] = FlexPowerFacts(
            soll_kw=soll_kw,
            ist_kw=ist_kw,
            mismatch_kw=round(soll_kw - ist_kw, 3),
            pv_follow_soll=_pv_follow_soll(entry, consumer_id, consumer),
            loxone_setpoint_kw=_loxone_setpoint_kw(entry, consumer_id, consumer),
            nominal_power_kw=_nominal_power_kw(consumer),
        )
    thermal_index = _thermal_by_consumer(entry)
    thermal = {
        consumer_id: _thermal_facts(thermal_index.get(consumer_id))
        for consumer_id in consumers
    }
    remaining = {
        str(key): _float_or_zero(value)
        for key, value in (entry.get("consumer_remaining_kwh") or {}).items()
    }
    contexts = {
        str(key): dict(value)
        for key, value in (entry.get("charging_contexts") or {}).items()
        if isinstance(value, dict)
    }
    return SlotDeviationFacts(
        slot_quality=slot_quality,
        consumers=consumers,
        battery=_battery_facts(entry),
        thermal=thermal,
        charging_contexts=contexts,
        consumer_remaining_kwh=remaining,
        filter_windows=_filter_windows(entry, set(consumers)),
        slot_start=slot_start,
    )
