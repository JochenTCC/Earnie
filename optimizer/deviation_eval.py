"""Regelauswertung für Soll/Ist-Abweichungen (Epic Soll-Ist)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import config
from optimizer import battery as bat
from optimizer.deviation_facts import FlexPowerFacts, SlotDeviationFacts
from optimizer.deviation_rules import load_deviation_rules, validate_deviation_rules_document
from runtime_store.history_timeline import SLOT_PRESENT

Predicate = Callable[
    [SlotDeviationFacts, str, dict[str, Any], dict[str, float], dict[str, Any]],
    bool,
]

_MESSAGE_PATTERN = re.compile(r"\{(\w+)(:[^}]+)?\}")


@dataclass(frozen=True)
class DeviationEvent:
    rule_id: str
    category: str
    scope: str
    message: str
    label: str
    symbol: str
    color: str


def _power_tolerance(tolerances: dict[str, float]) -> float:
    return float(tolerances["power_kw"])


def _flex_for_scope(facts: SlotDeviationFacts, scope: str) -> FlexPowerFacts | None:
    if scope == "battery":
        return None
    return facts.consumers.get(scope)


def _power_mismatch_positive(
    facts: SlotDeviationFacts,
    scope: str,
    _rule: dict[str, Any],
    tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    flex = _flex_for_scope(facts, scope)
    if flex is None:
        return False
    tol = _power_tolerance(tolerances)
    return flex.soll_kw > tol and (flex.soll_kw - flex.ist_kw) > tol


def _power_mismatch_any(
    facts: SlotDeviationFacts,
    scope: str,
    _rule: dict[str, Any],
    tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    flex = _flex_for_scope(facts, scope)
    if flex is None:
        return False
    tol = _power_tolerance(tolerances)
    return abs(flex.soll_kw - flex.ist_kw) > tol


def _plugged_in(
    facts: SlotDeviationFacts,
    scope: str,
    _rule: dict[str, Any],
    _tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    ctx = facts.charging_contexts.get(scope) or {}
    return bool(ctx.get("plugged_in"))


def _remaining_kwh_above_threshold(
    facts: SlotDeviationFacts,
    scope: str,
    rule: dict[str, Any],
    _tolerances: dict[str, float],
    params: dict[str, Any],
) -> bool:
    threshold = float(params.get("remaining_kwh_threshold", 0.5))
    remaining = facts.consumer_remaining_kwh.get(scope)
    if remaining is None:
        ctx = facts.charging_contexts.get(scope) or {}
        target = float(ctx.get("target_kwh") or 0.0)
        return target > threshold
    return remaining > threshold


def _thermal_actual_in_band(
    facts: SlotDeviationFacts,
    scope: str,
    _rule: dict[str, Any],
    _tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    thermal = facts.thermal.get(scope)
    if thermal is None or thermal.actual_c is None:
        return False
    if thermal.band_min is None or thermal.band_max is None:
        return False
    return thermal.band_min <= float(thermal.actual_c) <= thermal.band_max


def _heating_was_scheduled(
    facts: SlotDeviationFacts,
    scope: str,
    _rule: dict[str, Any],
    _tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    thermal = facts.thermal.get(scope)
    return bool(thermal and thermal.heating_scheduled)


def _mode_is_forced_charge(
    facts: SlotDeviationFacts,
    _scope: str,
    _rule: dict[str, Any],
    _tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    return facts.battery.soll_mode == bat.MODE_ZWANGS_LADEN


def _mode_is_forced_discharge(
    facts: SlotDeviationFacts,
    _scope: str,
    _rule: dict[str, Any],
    _tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    return facts.battery.soll_mode == bat.MODE_ZWANGS_ENTLADEN


def _ist_charge_kw(battery_kw: float) -> float:
    """Loxone: negatives Vorzeichen = Laden."""
    return max(0.0, -float(battery_kw))


def _ist_discharge_kw(battery_kw: float) -> float:
    return max(0.0, float(battery_kw))


def _battery_power_below_tolerance(
    facts: SlotDeviationFacts,
    _scope: str,
    _rule: dict[str, Any],
    tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    tol = _power_tolerance(tolerances)
    battery = facts.battery
    if battery.soll_mode == bat.MODE_ZWANGS_LADEN:
        soll = max(0.0, battery.soll_plan_kw)
        ist = _ist_charge_kw(battery.ist_power_kw)
        return soll > tol and (soll - ist) > tol
    if battery.soll_mode == bat.MODE_ZWANGS_ENTLADEN:
        soll = max(0.0, -battery.soll_plan_kw)
        ist = _ist_discharge_kw(battery.ist_power_kw)
        return soll > tol and (soll - ist) > tol
    return False


def _slot_quality_present(
    facts: SlotDeviationFacts,
    _scope: str,
    _rule: dict[str, Any],
    _tolerances: dict[str, float],
    _params: dict[str, Any],
) -> bool:
    return facts.slot_quality == SLOT_PRESENT


PREDICATES: dict[str, Predicate] = {
    "power_mismatch_positive": _power_mismatch_positive,
    "power_mismatch_any": _power_mismatch_any,
    "plugged_in": _plugged_in,
    "remaining_kwh_above_threshold": _remaining_kwh_above_threshold,
    "thermal_actual_in_band": _thermal_actual_in_band,
    "heating_was_scheduled": _heating_was_scheduled,
    "mode_is_forced_charge": _mode_is_forced_charge,
    "mode_is_forced_discharge": _mode_is_forced_discharge,
    "battery_power_below_tolerance": _battery_power_below_tolerance,
    "slot_quality_present": _slot_quality_present,
}


def _consumer_display_name(scope: str) -> str:
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        if consumer["id"] == scope:
            return str(consumer.get("name") or scope)
    return scope


def _message_context(facts: SlotDeviationFacts, scope: str) -> dict[str, Any]:
    flex = facts.consumers.get(scope)
    return {
        "scope": scope,
        "consumer_name": _consumer_display_name(scope),
        "soll_kw": 0.0 if flex is None else flex.soll_kw,
        "ist_kw": 0.0 if flex is None else flex.ist_kw,
        "mismatch_kw": 0.0 if flex is None else flex.mismatch_kw,
    }


def format_deviation_message(template: str, values: dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        fmt = match.group(2) or ""
        if name not in values:
            return match.group(0)
        value = values[name]
        if fmt.startswith(":"):
            fmt = fmt[1:]
        return format(value, fmt) if fmt else str(value)

    return _MESSAGE_PATTERN.sub(_replace, template)


def _rule_matches(
    rule: dict[str, Any],
    facts: SlotDeviationFacts,
    tolerances: dict[str, float],
) -> bool:
    scope = str(rule["scope"])
    params = dict(rule.get("params") or {})
    for predicate_name in rule["when"]:
        predicate = PREDICATES.get(predicate_name)
        if predicate is None:
            raise ValueError(
                f"Unbekanntes Prädikat '{predicate_name}' in Regel '{rule['id']}'."
            )
        if not predicate(facts, scope, rule, tolerances, params):
            return False
    return True


def _build_event(
    rule: dict[str, Any],
    facts: SlotDeviationFacts,
    categories: dict[str, dict[str, str]],
) -> DeviationEvent:
    scope = str(rule["scope"])
    category = str(rule["category"])
    meta = categories[category]
    return DeviationEvent(
        rule_id=str(rule["id"]),
        category=category,
        scope=scope,
        message=format_deviation_message(
            str(rule["message"]),
            _message_context(facts, scope),
        ),
        label=str(meta["label"]),
        symbol=str(meta["symbol"]),
        color=str(meta["color"]),
    )


def _fallback_event(
    scope: str,
    category: str,
    facts: SlotDeviationFacts,
    categories: dict[str, dict[str, str]],
) -> DeviationEvent:
    meta = categories[category]
    flex = facts.consumers[scope]
    return DeviationEvent(
        rule_id="fallback",
        category=category,
        scope=scope,
        message=(
            f"{_consumer_display_name(scope)}: Soll {flex.soll_kw:.2f} kW, "
            f"Ist {flex.ist_kw:.2f} kW"
        ),
        label=str(meta["label"]),
        symbol=str(meta["symbol"]),
        color=str(meta["color"]),
    )


def evaluate_slot_deviations(
    facts: SlotDeviationFacts,
    rules_doc: dict[str, Any],
) -> list[DeviationEvent]:
    """Wendet Regeln auf einen Slot an; leer wenn slot_quality != present."""
    if facts.slot_quality != SLOT_PRESENT:
        return []

    validate_deviation_rules_document(rules_doc, source="rules_doc")
    tolerances = {key: float(value) for key, value in rules_doc["tolerances"].items()}
    categories = rules_doc["categories"]
    fallback = str(rules_doc["fallback"]["on_unclassified_mismatch"])

    enabled = [rule for rule in rules_doc["rules"] if rule.get("enabled", True)]
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for rule in enabled:
        by_scope.setdefault(str(rule["scope"]), []).append(rule)
    for scope_rules in by_scope.values():
        scope_rules.sort(key=lambda item: int(item["priority"]), reverse=True)

    events: list[DeviationEvent] = []
    matched_scopes: set[str] = set()
    for scope, scope_rules in by_scope.items():
        for rule in scope_rules:
            if _rule_matches(rule, facts, tolerances):
                events.append(_build_event(rule, facts, categories))
                matched_scopes.add(scope)
                break

    if fallback != "none":
        for scope, flex in facts.consumers.items():
            if scope in matched_scopes:
                continue
            tol = _power_tolerance(tolerances)
            if flex.soll_kw > tol and (flex.soll_kw - flex.ist_kw) > tol:
                events.append(_fallback_event(scope, fallback, facts, categories))
    return events


def evaluate_entry_deviations(
    entry: dict[str, Any],
    *,
    slot_quality: str = SLOT_PRESENT,
    rules_doc: dict[str, Any] | None = None,
    rules_path: str | None = None,
) -> list[DeviationEvent]:
    """Facts aus Log-Eintrag bauen und Regeln auswerten."""
    from optimizer.deviation_facts import build_slot_deviation_facts

    facts = build_slot_deviation_facts(entry, slot_quality=slot_quality)
    document = rules_doc if rules_doc is not None else load_deviation_rules(rules_path)
    return evaluate_slot_deviations(facts, document)
