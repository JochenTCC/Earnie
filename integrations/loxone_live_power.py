"""Live power / meter resolution for Loxone flexible consumers."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import config
import logging
from settings.ehal_marker_resolve import (
    ehal_bindings,
    marker_flex_enable,
    marker_flex_power,
    marker_get_evcs_nominal_current,
    marker_sens_evcs_active_power,
    marker_sens_evcs_bat_capacity,
)
from settings.ev_power import (
    ampere_to_kw,
    ev_nominal_power_conversion,
    kw_from_nominal_reading,
)
from settings.flexible_consumers import runtime_consumer_id

logger = logging.getLogger(__name__)


def _parse_loxone_value(raw_value: str):
    from integrations import loxone_client as lc

    return lc._parse_loxone_value(raw_value)


def fetch_loxone_generic_value(io_name: str):
    from integrations import loxone_client as lc

    return lc.fetch_loxone_generic_value(io_name)


def fetch_filter_native_start_hour(io_name: str):
    from integrations import loxone_client as lc

    return lc.fetch_filter_native_start_hour(io_name)


def fetch_loxone_raw_value(io_name: str):
    from integrations import loxone_client as lc

    return lc.fetch_loxone_raw_value(io_name)


def resolve_consumer_nominal_power_kw(consumer: dict) -> float:
    """Nennleistung (kW) aus live ``get_evcs_nominal_current`` (A)."""
    fallback = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    bindings = ehal_bindings(consumer)
    ehal_name = str(
        bindings.get("get_evcs_nominal_current")
        or bindings.get("sens_evcs_nominal_current")
        or ""
    ).strip()
    io_name = marker_get_evcs_nominal_current(consumer)
    if not io_name:
        return fallback

    raw = fetch_loxone_raw_value(io_name)
    if raw is None:
        logger.warning(
            "Loxone: Keine gültige Nennleistung für '%s' (%s), Fallback %.2f kW",
            consumer.get("id"),
            io_name,
            fallback,
        )
        return fallback

    try:
        value, unit = _parse_loxone_value(raw)
    except ValueError as e:
        logger.error(
            "Loxone: Parsing-Fehler bei Nennleistung '%s' (raw=%r): %s",
            io_name,
            raw,
            e,
        )
        return fallback

    if ehal_name or unit == "a":
        voltage_v, phases = ev_nominal_power_conversion(consumer)
        live = ampere_to_kw(value, voltage_v=voltage_v, phases=phases)
    else:
        live = kw_from_nominal_reading(value, unit, consumer)

    if live <= 0:
        logger.warning(
            "Loxone: Keine gültige Nennleistung für '%s' (%s, raw=%r), Fallback %.2f kW",
            consumer.get("id"),
            io_name,
            raw,
            fallback,
        )
        return fallback
    return float(live)


def resolve_consumer_battery_capacity_kwh(consumer: dict) -> float | None:
    """Akkukapazität (kWh): Hausprofil-Bridge oder live sens_evcs_bat_capacity."""
    direct = consumer.get("battery_capacity_kwh")
    if direct is not None and float(direct) > 0:
        return float(direct)
    sched = consumer.get("charging_schedule") or {}
    sched_cap = sched.get("battery_capacity_kwh")
    if sched_cap is not None and float(sched_cap) > 0:
        return float(sched_cap)

    io_name = marker_sens_evcs_bat_capacity(consumer)
    cid = consumer.get("id", "?")
    if not io_name:
        logger.error(
            "Verbraucher '%s': sens_evcs_bat_capacity / "
            "battery_capacity_kwh_name fehlt.",
            cid,
        )
        return None

    raw = fetch_loxone_raw_value(io_name)
    if raw is None:
        logger.error(
            "Loxone: Akkukapazität für '%s' (%s) nicht lesbar.",
            cid,
            io_name,
        )
        return None

    try:
        value, unit = _parse_loxone_value(raw)
    except ValueError as e:
        logger.error(
            "Loxone: Parsing-Fehler bei Akkukapazität '%s' (raw=%r): %s",
            io_name,
            raw,
            e,
        )
        return None

    if unit is not None and unit not in ("kwh", "kw", ""):
        logger.error(
            "Loxone: Unbekannte Einheit '%s' bei Akkukapazität '%s' (%s).",
            unit,
            cid,
            io_name,
        )
        return None

    if value <= 0:
        logger.error(
            "Loxone: Ungültige Akkukapazität für '%s' (%s, raw=%r).",
            cid,
            io_name,
            raw,
        )
        return None
    return float(value)


def consumers_with_live_nominal_power(consumers: list | None = None) -> list:
    """Kopie der Verbraucher mit zur Laufzeit aus Loxone gelesener Nennleistung."""
    import copy
    source = consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)
    updated = []
    for consumer in source:
        item = copy.copy(consumer)
        item["nominal_power_kw"] = resolve_consumer_nominal_power_kw(consumer)
        updated.append(item)
    return updated


def _consumer_power_io_name(consumer: dict) -> str:
    """Live power Merker: EHAL bindings first, legacy ``loxone_inputs.power_name`` fallback."""
    sched = consumer.get("charging_schedule") or {}
    bindings = ehal_bindings(consumer)
    is_ev = consumer.get("type") == "ev" or (
        isinstance(sched, dict) and bool(sched.get("enabled"))
    )
    if not is_ev and isinstance(bindings, dict):
        is_ev = any(
            str(key or "").startswith(("sens_evcs_", "get_evcs_", "set_evcs_"))
            and str(value or "").strip()
            for key, value in bindings.items()
        )
    if is_ev:
        return marker_sens_evcs_active_power(consumer) or marker_flex_power(consumer)
    return marker_flex_power(consumer) or marker_sens_evcs_active_power(consumer)


def _binary_meter_kw(
    inputs: dict,
    nominal: float,
    *,
    primary_io_name: str = "",
    alternate_io_name: str = "",
) -> float | None:
    """Binärer Verbraucher: 0/1-Merker × Nennleistung.

    Optional alternate binary Merker (z. B. natives Filter-Relais neben
    Gesamt-Filterstatus) — läuft, wenn mindestens ein Merker ≥ 0,5 ist.
    Alternate-only is valid when no primary power Merker is configured.
    """
    io_name = str(primary_io_name or inputs.get("power_name", "")).strip()
    alt_name = str(
        alternate_io_name or inputs.get("alternate_binary_power_name", "")
    ).strip()
    if not io_name and not alt_name:
        return None
    readings: list[float | None] = []
    if io_name:
        readings.append(fetch_loxone_generic_value(io_name))
    if alt_name and alt_name != io_name:
        readings.append(fetch_loxone_generic_value(alt_name))
    if all(value is None for value in readings):
        return None
    if any(value is not None and float(value) >= 0.5 for value in readings):
        return round(nominal, 3)
    return 0.0


def _read_consumer_meter_kw(consumer: dict) -> float | None:
    """Reine Zähler-Messung (kW) ohne Fallback.

    None, wenn der Merker fehlt oder Loxone nicht antwortet — so lässt sich
    „gemessen" von „Fallback verwendet" unterscheiden.
    binary: Merker 0/1 × Nennleistung; power: direkter kW-Wert (≥ 0).
    """
    from settings.ehal_marker_resolve import marker_sens_filter_active

    inputs = consumer.get("loxone_inputs") or {}
    io_name = _consumer_power_io_name(consumer)
    alt_filter = marker_sens_filter_active(consumer)
    signal_type = str(inputs.get("signal_type") or consumer.get("signal_type", "power")).lower()
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if signal_type == "binary":
        return _binary_meter_kw(
            inputs,
            nominal,
            primary_io_name=io_name,
            alternate_io_name=alt_filter,
        )
    if not io_name:
        return None
    raw = fetch_loxone_generic_value(io_name)
    if raw is None:
        return None
    return round(max(0.0, float(raw)), 3)


def resolve_consumer_live_power_kw(
    consumer: dict,
    *,
    fallback_kw: float | None = None,
) -> float | None:
    """
    Aktuelle Leistung (kW) eines flexiblen Verbrauchers live aus Loxone.
    binary: Merker 0/1 × Nennleistung; power: direkter kW-Wert (≥ 0).
    """
    measured = _read_consumer_meter_kw(consumer)
    if measured is not None:
        return measured
    io_name = _consumer_power_io_name(consumer)
    if io_name:
        logger.warning(
            "Loxone: Keine Live-Leistung für '%s' (%s), Fallback %s kW",
            consumer.get("id"),
            io_name,
            fallback_kw,
        )
    return fallback_kw


FILTER_INFERENCE_TOLERANCE_KW = 0.05
POOL_FILTER_ID = "pool_filter"
SWIMSPA_HEATING_ID = "swimspa"


@dataclass(frozen=True)
class LiveFlexPowerResult:
    """Live-Leistungen flexibler Verbraucher: operativ (mit Fallback) vs. Chart-Ist."""

    kw: dict[str, float]
    chart_kw: dict[str, float]
    measured_ids: frozenset[str]


def _build_chart_kw(result: dict[str, float], measured_ids: set[str]) -> dict[str, float]:
    return {
        cid: round(float(result[cid]), 3)
        for cid in measured_ids
        if cid in result
    }


def _slot_in_native_filter_window(
    filter_contexts: dict[str, dict] | None,
    filter_consumer_id: str,
    slot_dt: datetime,
) -> bool:
    if not filter_contexts or slot_dt is None:
        return False
    ctx = filter_contexts.get(filter_consumer_id) or {}
    start = ctx.get("native_start_hour")
    duration = ctx.get("native_duration_hours")
    if start is None or duration is None:
        return False
    from optimizer.filter_context import slot_in_native_window

    return slot_in_native_window(slot_dt, float(start), float(duration))


def _shared_meter_heating_ids(consumers: list, filter_id: str) -> list[str]:
    """Heating/runtime ids whose shared meter lists ``filter_id`` under subtract."""
    found: list[str] = []
    for consumer in consumers:
        subtract_ids = (consumer.get("loxone_inputs") or {}).get(
            "subtract_consumer_ids"
        ) or []
        if filter_id not in subtract_ids:
            continue
        cid = runtime_consumer_id(consumer)
        if cid and cid not in found:
            found.append(cid)
    if found:
        return found
    # Legacy Fall B default when subtract_consumer_ids was never wired.
    if any(item.get("id") == SWIMSPA_HEATING_ID for item in consumers):
        return [SWIMSPA_HEATING_ID]
    return []


def _apply_native_filter_inference(
    result: dict[str, float],
    measured_ids: set[str],
    consumers: list,
    *,
    filter_contexts: dict[str, dict] | None,
    slot_datetime: datetime | None,
) -> None:
    """Filter-Ist aus Gesamtzähler, wenn Binär-Merker 0 sind aber natives Fenster + Last passt."""
    if slot_datetime is None:
        return
    if not _slot_in_native_filter_window(
        filter_contexts, POOL_FILTER_ID, slot_datetime
    ):
        return
    if float(result.get(POOL_FILTER_ID, 0.0) or 0.0) > 1e-9:
        return

    filter_consumer = next(
        (item for item in consumers if item.get("id") == POOL_FILTER_ID),
        None,
    )
    if filter_consumer is None:
        return
    nominal = float(filter_consumer.get("nominal_power_kw", 0.0) or 0.0)
    if nominal <= 1e-9:
        return

    for heating_id in _shared_meter_heating_ids(consumers, POOL_FILTER_ID):
        if heating_id not in measured_ids:
            continue
        total = float(result.get(heating_id, 0.0) or 0.0)
        if total <= 1e-9 or abs(total - nominal) > FILTER_INFERENCE_TOLERANCE_KW:
            continue

        result[POOL_FILTER_ID] = round(nominal, 3)
        result[heating_id] = round(max(0.0, total - nominal), 3)
        measured_ids.add(POOL_FILTER_ID)
        logger.info(
            "Loxone: natives Filterfenster — Filter %.3f kW aus Gesamtzähler %.3f kW "
            "inferiert (Binär-Merker 0, heating=%s).",
            nominal,
            total,
            heating_id,
        )
        return


def _subtract_shared_meter_loads(
    result: dict[str, float],
    consumers: list,
    measured_ids: set[str],
) -> dict[str, float]:
    """Zieht bei gemeinsamer Leistungsmessung enthaltene Verbraucher-Anteile ab.

    Misst der ``power_name`` eines Verbrauchers die Gesamtleistung mehrerer Lasten
    am selben Zähler (z. B. SwimSpa-Heizung inkl. Filter), listet er die enthaltenen
    IDs unter ``loxone_inputs.subtract_consumer_ids``. Der Abzug wird nur angewandt,
    wenn der Gesamtwert tatsächlich vom Zähler stammt (nicht aus dem Fallback) —
    sonst würde ein bereits filterfreier Fallback-Sollwert doppelt gekürzt.
    """
    corrected = dict(result)
    for consumer in consumers:
        subtract_ids = (consumer.get("loxone_inputs") or {}).get("subtract_consumer_ids") or []
        cid = runtime_consumer_id(consumer)
        if not subtract_ids or cid not in measured_ids or cid not in corrected:
            continue
        deduction = sum(float(result.get(sub_id, 0.0) or 0.0) for sub_id in subtract_ids)
        if deduction <= 0:
            continue
        new_value = round(max(0.0, corrected[cid] - deduction), 3)
        logger.info(
            "Loxone: '%s' Gesamtmessung %.3f kW − enthaltene Last(en) %s (%.3f kW) "
            "= %.3f kW.",
            cid,
            corrected[cid],
            list(subtract_ids),
            deduction,
            new_value,
        )
        corrected[cid] = new_value
    return corrected


def _house_profile_power_consumers() -> list[dict]:
    """House-profile consumers with a resolvable live power Merker (known/manual)."""
    resolved = config.CONFIG.get_resolved_runtime_settings()
    profile = resolved.get("_house_profile") if isinstance(resolved, dict) else None
    if not isinstance(profile, dict):
        return []
    out: list[dict] = []
    for consumer in profile.get("consumers") or []:
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        if not (marker_flex_power(consumer) or marker_sens_evcs_active_power(consumer)):
            continue
        out.append(consumer)
    return out


def _default_live_power_consumers() -> list[dict]:
    """MILP flex plus house-profile loads that have a live power Merker."""
    from integrations import loxone_client as lc

    flex = list(lc.config.get_flexible_consumers())
    by_id: dict[str, dict] = {}
    for consumer in flex:
        cid = str(consumer.get("id") or "").strip()
        if cid:
            by_id[cid] = consumer
    for house_consumer in lc._house_profile_power_consumers():
        cid = str(house_consumer.get("id") or "").strip()
        if not cid:
            continue
        existing = by_id.get(cid)
        if existing is None:
            by_id[cid] = house_consumer
            continue
        if existing.get("ehal_bindings") or not house_consumer.get("ehal_bindings"):
            continue
        merged = dict(existing)
        merged["ehal_bindings"] = dict(house_consumer["ehal_bindings"])
        by_id[cid] = merged
    return list(by_id.values())


def resolve_flexible_consumers_live_power(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
    *,
    filter_contexts: dict[str, dict] | None = None,
    slot_datetime: datetime | None = None,
) -> LiveFlexPowerResult:
    """
    Live-Leistungen aller flexiblen Verbraucher.

    ``kw`` enthält Fallbacks für cons_data/Delivery; ``chart_kw`` nur gemessene
    (und inferierte) Werte — ohne MILP-Soll — für Chart/Log-Ist.
    """
    from integrations import loxone_client as lc

    fallbacks = fallbacks or {}
    source = (
        consumers if consumers is not None else lc._default_live_power_consumers()
    )
    result: dict[str, float] = {}
    measured_ids: set[str] = set()

    for consumer in source:
        runtime_id = runtime_consumer_id(consumer)
        canonical_id = consumer["id"]
        fallback = float(
            fallbacks.get(runtime_id, fallbacks.get(canonical_id, 0.0)) or 0.0
        )
        io_name = _consumer_power_io_name(consumer)
        measured = _read_consumer_meter_kw(consumer)
        if measured is not None:
            measured_ids.add(runtime_id)
            result[runtime_id] = round(float(measured), 3)
            if io_name:
                logger.debug(
                    "Loxone Live-Leistung %s: %.3f kW (%s)",
                    runtime_id,
                    result[runtime_id],
                    io_name,
                )
        else:
            result[runtime_id] = round(fallback, 3)
            if io_name:
                logger.warning(
                    "Loxone: Keine Live-Leistung für '%s' (%s), Fallback %s kW",
                    runtime_id,
                    io_name,
                    fallback,
                )

    corrected = _subtract_shared_meter_loads(result, source, measured_ids)
    _apply_native_filter_inference(
        corrected,
        measured_ids,
        source,
        filter_contexts=filter_contexts,
        slot_datetime=slot_datetime,
    )
    chart_kw = _build_chart_kw(corrected, measured_ids)
    return LiveFlexPowerResult(
        kw=corrected,
        chart_kw=chart_kw,
        measured_ids=frozenset(measured_ids),
    )


def fetch_flexible_consumers_live_kw(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
    *,
    filter_contexts: dict[str, dict] | None = None,
    slot_datetime: datetime | None = None,
) -> dict[str, float]:
    """
    Live-Leistungen aller flexiblen Verbraucher für cons_data.
    Fallback (z. B. Optimizer-Sollwerte) wenn Merker fehlt oder Loxone nicht antwortet.
    """
    return resolve_flexible_consumers_live_power(
        fallbacks,
        consumers,
        filter_contexts=filter_contexts,
        slot_datetime=slot_datetime,
    ).kw


def fetch_loxone_live_power() -> Optional[dict]:
    """
    Holt Echtzeit-Leistungswerte aus Loxone, normiert sie und prüft Vorzeichen.
    """
    pv = fetch_loxone_generic_value(config.get("LOXONE_PV_POWER_NAME"))
    battery_raw = fetch_loxone_generic_value(config.get("LOXONE_BATTERY_POWER_NAME"))
    grid_raw = fetch_loxone_generic_value(config.get("LOXONE_GRID_POWER_NAME"))

    if pv is None or grid_raw is None or battery_raw is None:
        return None

    pv = max(0.0, float(pv))
    battery = float(battery_raw)
    grid = float(grid_raw)
    house = pv + battery + grid

    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2),
    }


