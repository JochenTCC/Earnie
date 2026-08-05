"""Promote house-profile Pool/SwimSpa filter off the synthetic bridge.

- ``known`` ``pool_filter`` → MILP shape (``daily_target_source``, ``filter_schedule``)
- ``swimspa_filter_bindings`` nest → create/merge ``pool_filter``, strip nest
- Warn when MILP ``thermal_rc`` exists without ``pool_filter``
- Rewrite deviation rule scopes ``swimspa_filter`` → ``pool_filter``
"""
from __future__ import annotations

import copy
from typing import Any

from house_config.consumption_csv import consumer_uses_profile_csv
from house_config.ehal_bindings import filter_bindings_to_ehal_map
from house_config.planning_flex_bridge import POOL_FILTER_ID


def _profiles_iterable(house_doc: dict) -> list[dict]:
    profiles = house_doc.get("profiles")
    if isinstance(profiles, dict):
        return [p for p in profiles.values() if isinstance(p, dict)]
    if isinstance(profiles, list):
        return [p for p in profiles if isinstance(p, dict)]
    return []


def _milp_thermal_rc_present(consumers: list[dict]) -> bool:
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if str(consumer.get("type") or "") != "thermal_rc":
            continue
        if consumer_uses_profile_csv(consumer):
            continue
        return True
    return False


def _find_pool_filter(consumers: list[dict]) -> dict | None:
    for consumer in consumers:
        if isinstance(consumer, dict) and str(consumer.get("id") or "").strip() == POOL_FILTER_ID:
            return consumer
    return None


def _nest_ehal_from_thermal(consumers: list[dict]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        stored = consumer.get("swimspa_filter_bindings")
        if isinstance(stored, dict) and stored:
            mapped = filter_bindings_to_ehal_map(stored)
            merged.update(mapped)
        ehal = consumer.get("ehal_bindings")
        if isinstance(ehal, dict):
            hours = str(ehal.get("get_filter_remaining_hours") or "").strip()
            if hours and "get_filter_remaining_hours" not in merged:
                merged["get_filter_remaining_hours"] = hours
    return merged


def _strip_nests(consumers: list[dict]) -> bool:
    changed = False
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if "swimspa_filter_bindings" in consumer:
            consumer.pop("swimspa_filter_bindings", None)
            changed = True
        ehal = consumer.get("ehal_bindings")
        if isinstance(ehal, dict) and "get_filter_remaining_hours" in ehal:
            if str(consumer.get("type") or "") == "thermal_rc":
                ehal = dict(ehal)
                ehal.pop("get_filter_remaining_hours", None)
                if ehal:
                    consumer["ehal_bindings"] = ehal
                else:
                    consumer.pop("ehal_bindings", None)
                changed = True
    return changed


def _default_filter_schedule(consumer: dict) -> dict:
    sched = consumer.get("schedule") if isinstance(consumer.get("schedule"), dict) else {}
    start = int(sched.get("start_hour", 10) or 10) % 24
    duration = float(sched.get("duration_h", 4.0) or 4.0)
    return {
        "enabled": True,
        "config_fallback": {
            "native_start_hour": start,
            "native_duration_hours": duration,
        },
    }


def _promote_existing_pool_filter(consumer: dict) -> bool:
    """Attach MILP filter fields; drop earnie_role known overlay use."""
    changed = False
    if str(consumer.get("daily_target_source") or "") != "loxone_remaining_hours":
        consumer["daily_target_source"] = "loxone_remaining_hours"
        changed = True
    if not isinstance(consumer.get("filter_schedule"), dict):
        consumer["filter_schedule"] = _default_filter_schedule(consumer)
        changed = True
    else:
        fs = dict(consumer["filter_schedule"])
        if "enabled" not in fs:
            fs["enabled"] = True
            changed = True
        if not isinstance(fs.get("config_fallback"), dict):
            fs["config_fallback"] = _default_filter_schedule(consumer)["config_fallback"]
            changed = True
        consumer["filter_schedule"] = fs
    if consumer.get("signal_type") in (None, ""):
        consumer["signal_type"] = "binary"
        changed = True
    if consumer.get("min_on_quarterhours") is None:
        consumer["min_on_quarterhours"] = 2
        changed = True
    if "earnie_role" in consumer:
        consumer.pop("earnie_role", None)
        changed = True
    if float(consumer.get("nominal_power_kw", 0) or 0) <= 0:
        consumer["nominal_power_kw"] = 0.18
        changed = True
    return changed


def _create_pool_filter(ehal: dict[str, str]) -> dict:
    return {
        "id": POOL_FILTER_ID,
        "label": "Pool-Filter",
        "type": "generic",
        "nominal_power_kw": 0.18,
        "use_profile_csv": False,
        "daily_target_source": "loxone_remaining_hours",
        "daily_target_kwh": 0.36,
        "signal_type": "binary",
        "min_on_quarterhours": 2,
        "filter_schedule": {
            "enabled": True,
            "config_fallback": {
                "native_start_hour": 10,
                "native_duration_hours": 4.0,
            },
        },
        "ehal_bindings": dict(ehal),
    }


def promote_pool_filter_in_profile(profile: dict) -> tuple[bool, list[str]]:
    """Mutate one profile; return (changed, warnings)."""
    warnings: list[str] = []
    consumers = profile.get("consumers")
    if not isinstance(consumers, list):
        return False, warnings
    consumers = [c for c in consumers if isinstance(c, dict)]
    profile["consumers"] = consumers
    changed = False
    nest_ehal = _nest_ehal_from_thermal(consumers)
    pool = _find_pool_filter(consumers)
    if pool is None and nest_ehal:
        consumers.append(_create_pool_filter(nest_ehal))
        pool = consumers[-1]
        changed = True
    elif pool is not None and nest_ehal:
        ehal = dict(pool.get("ehal_bindings") or {})
        for key, value in nest_ehal.items():
            if value and not str(ehal.get(key) or "").strip():
                ehal[key] = value
                changed = True
        pool["ehal_bindings"] = ehal
    if pool is not None and _promote_existing_pool_filter(pool):
        changed = True
    if _strip_nests(consumers):
        changed = True
    if _milp_thermal_rc_present(consumers) and _find_pool_filter(consumers) is None:
        pid = str(profile.get("id") or profile.get("label") or "?")
        warnings.append(
            f"Profile '{pid}': MILP thermal_rc without pool_filter — "
            "filter optimization disabled until pool_filter is added."
        )
    return changed, warnings


def promote_pool_filter_milp(house_doc: dict | None) -> tuple[dict, bool, list[str]]:
    """Return (new_house, changed, warnings)."""
    house = copy.deepcopy(house_doc) if isinstance(house_doc, dict) else {}
    changed = False
    warnings: list[str] = []
    for profile in _profiles_iterable(house):
        profile_changed, profile_warnings = promote_pool_filter_in_profile(profile)
        changed = changed or profile_changed
        warnings.extend(profile_warnings)
    return house, changed, warnings


def rewrite_deviation_filter_scopes(rules_doc: dict | None) -> tuple[dict, bool]:
    """Rewrite scope swimspa_filter → pool_filter in deviation rules."""
    doc = copy.deepcopy(rules_doc) if isinstance(rules_doc, dict) else {}
    changed = False
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return doc, False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("scope") or "").strip() == "swimspa_filter":
            rule["scope"] = POOL_FILTER_ID
            changed = True
    return doc, changed
