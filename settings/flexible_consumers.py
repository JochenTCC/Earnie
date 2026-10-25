"""Hilfsfunktionen für flexible Verbraucher (Quelle: Hausprofil)."""
from __future__ import annotations

from datetime import datetime

CONSUMER_PALETTE_SIZE = 8


def runtime_consumer_id(consumer: dict) -> str:
    """Live/cons_data/state key — always the canonical consumer id."""
    return str(consumer["id"])


def profile_column_id(consumer: dict) -> str:
    """Column name in flexible_consumer_profiles.csv (canonical id)."""
    return str(consumer["id"])


def charging_context_lookup(contexts: dict | None, consumer: dict) -> dict:
    """Lookup persisted charging_contexts by canonical consumer id."""
    if not contexts:
        return {}
    ctx = contexts.get(str(consumer["id"])) or {}
    return ctx if isinstance(ctx, dict) else {}


def flex_kw_lookup(flex: dict | None, consumer: dict) -> float:
    """Lookup live/matrix flex kW by canonical consumer id."""
    if not flex:
        return 0.0
    return float(flex.get(str(consumer["id"]), 0.0) or 0.0)


def flex_kw_to_canonical(
    flex: dict | None,
    consumers: list[dict],
) -> dict[str, float]:
    """Restrict a flex dict to the given consumers (canonical ids, rounded)."""
    return {
        str(consumer["id"]): round(flex_kw_lookup(flex, consumer), 6)
        for consumer in consumers
    }


def flex_kw_pop_for_consumer(flex: dict, consumer: dict) -> float:
    """Remove and return flex kW for consumer (canonical id)."""
    return float(flex.pop(str(consumer["id"]), 0.0) or 0.0)


def reject_legacy_id(raw: dict, consumer_id: str) -> None:
    """Fail fast when a config/profile row still carries the removed ``legacy_id``."""
    if "legacy_id" not in raw:
        return
    raise ValueError(
        f"Kritischer Konfigurationsfehler: Verbraucher '{consumer_id}': "
        "legacy_id entfernt, kanonische id verwenden."
    )


def normalize_day_schedule(block: dict | None) -> dict:
    if not isinstance(block, dict):
        return {}
    out = {}
    available = block.get("car_available_from_hour", block.get("charge_from_hour"))
    ready = block.get("ready_by_hour", block.get("charge_until_hour"))
    if available is not None:
        out["car_available_from_hour"] = int(available) % 24
    if ready is not None:
        out["ready_by_hour"] = int(ready) % 24
    if block.get("daily_rest_soc") is not None:
        out["daily_rest_soc"] = float(block["daily_rest_soc"])
    return out


def charging_efficiency(sched: dict) -> float:
    """Lade-Wirkungsgrad (Netz-/Zählerenergie → Akku); Default 0,95 wenn nicht gesetzt."""
    raw = sched.get("charging_efficiency")
    if raw is None:
        return 0.90
    efficiency = float(raw)
    if efficiency <= 0.0 or efficiency > 1.0:
        raise ValueError(
            "charging_schedule.charging_efficiency muss ein Wert zwischen 0 (exklusiv) "
            "und 1 (inklusiv) sein."
        )
    return efficiency


def target_kwh_from_rest_soc(
    consumer: dict,
    rest_soc_percent: float | None,
    *,
    capacity_kwh: float | None,
    limit_soc_percent: float | None = None,
) -> float | None:
    """Ladeziel (kWh) aus Ist-/Rest-SOC (%), Limit-SOC, Kapazität und Wirkungsgrad."""
    if rest_soc_percent is None:
        return None
    if capacity_kwh is None:
        return None
    capacity = float(capacity_kwh)
    if capacity <= 0:
        return None
    sched = consumer.get("charging_schedule") or {}
    if limit_soc_percent is None:
        target_soc = float(sched.get("target_soc_percent", 100.0) or 100.0)
    else:
        target_soc = float(limit_soc_percent)
    battery_delta_kwh = (target_soc - float(rest_soc_percent)) / 100.0 * capacity
    eff = charging_efficiency(sched)
    return max(0.0, battery_delta_kwh / eff)


def target_kwh_from_day_schedule(
    consumer: dict,
    when: datetime,
    *,
    capacity_kwh: float | None,
) -> float | None:
    """Ladeziel (kWh) aus daily_rest_soc des passenden Wochentags in charging_schedule."""
    sched = consumer.get("charging_schedule")
    if not sched or not sched.get("enabled"):
        return None
    day_key = "weekend" if when.weekday() >= 5 else "weekday"
    rest_soc = (sched.get(day_key) or {}).get("daily_rest_soc")
    return target_kwh_from_rest_soc(consumer, rest_soc, capacity_kwh=capacity_kwh)


def consumer_has_daily_target(consumer: dict) -> bool:
    if consumer.get("generic_flex_window"):
        return True
    target_source = consumer.get("daily_target_source", "config")
    if target_source == "thermal_annual":
        return True
    sched = consumer.get("charging_schedule")
    if sched and sched.get("enabled"):
        if target_source == "historical":
            return bool(consumer.get("path_historical_log"))
        if target_source == "loxone":
            return True
        capacity = float(sched.get("battery_capacity_kwh", 0.0) or 0.0)
        if capacity > 0:
            for day_key in ("weekday", "weekend"):
                if (sched.get(day_key) or {}).get("daily_rest_soc") is not None:
                    return True
    if target_source in ("historical", "loxone", "loxone_remaining_hours", "thermal"):
        return True
    return float(consumer.get("daily_target_kwh", 0.0) or 0.0) > 0


def load_flexible_consumers(
    resolved: dict,
    *,
    optimizer_only: bool = False,
) -> list:
    """Flexible Verbraucher aus dem Hausprofil (``_planning_flex_consumers``)."""
    planning = resolved.get("_planning_flex_consumers") or []
    seen: set[str] = set()
    for consumer in planning:
        consumer_id = str(consumer["id"])
        if consumer_id in seen:
            raise ValueError(
                f"Kritischer Konfigurationsfehler: Verbraucher-ID '{consumer_id}' "
                "kommt im Hausprofil mehrfach vor."
            )
        seen.add(consumer_id)
    from house_config.planning_flex_bridge import merge_flexible_consumers

    consumers = merge_flexible_consumers([], planning)
    if optimizer_only:
        return [
            c for c in consumers
            if c["optimizer_enabled"]
            and c["nominal_power_kw"] > 0
            and consumer_has_daily_target(c)
        ]
    return consumers
