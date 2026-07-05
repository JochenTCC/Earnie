"""Normalisierte Slot-Fakten für Soll/Ist-Abweichungen (Epic Soll-Ist)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import config
from optimizer import battery as bat
from runtime_store.history_timeline import SLOT_PRESENT


@dataclass(frozen=True)
class FlexPowerFacts:
    soll_kw: float
    ist_kw: float
    mismatch_kw: float


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


def _ist_flex_kw(entry: dict[str, Any], consumer_id: str) -> float:
    snapshot = entry.get("consumption_snapshot") or {}
    flex_kw = snapshot.get("flex_kw") or {}
    if consumer_id in flex_kw:
        return _float_or_zero(flex_kw[consumer_id])
    live = entry.get("flex_live_kw") or {}
    return _float_or_zero(live.get(consumer_id))


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
    del slot_start  # reserviert für Stufe 2 / Slot-spezifische Thermik
    consumers: dict[str, FlexPowerFacts] = {}
    for consumer_id in sorted(_consumer_ids_from_entry(entry)):
        soll_kw = _soll_flex_kw(entry, consumer_id)
        ist_kw = _ist_flex_kw(entry, consumer_id)
        consumers[consumer_id] = FlexPowerFacts(
            soll_kw=soll_kw,
            ist_kw=ist_kw,
            mismatch_kw=round(soll_kw - ist_kw, 3),
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
    )
