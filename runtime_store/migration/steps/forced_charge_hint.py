"""Step dm4.forced_charge_hint — grade Zwangs-Laden by delivered slot energy.

Detect-based (no data-model bump). Both forced-charge rules use
``battery_charge_energy_below_ratio`` from the bundled example: red below 60 %,
yellow below 80 % of the target energy. The step

- inserts ``battery_forced_charge_target_missed`` when that id is absent,
- rewrites any rule still using the removed 2.7.0-beta.2 predicate
  ``battery_charge_target_missed``,
- rewrites ``battery_forced_charge_missing`` while it has the shipped
  ``battery_power_below_tolerance`` form.

Shipped messages are replaced; custom messages stay.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime_store.data_model import read_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.forced_charge_hint"
RULE_ID = "battery_forced_charge_target_missed"
ERROR_RULE_ID = "battery_forced_charge_missing"
REMOVED_PREDICATE = "battery_charge_target_missed"
_OLD_ERROR_WHEN = ["mode_is_forced_charge", "battery_power_below_tolerance"]
_SHIPPED_MESSAGES = frozenset(
    {
        "Zwangs-Laden nicht ausgeführt",
        "Zwangs-Laden: Zielenergie nicht erreicht "
        "(Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW)",
        "Zwangs-Laden: Zielleistung nicht erreicht "
        "(Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW)",
    }
)
_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "share"
    / "config"
    / "deviation_rules.example.json"
)


@lru_cache(maxsize=2)
def _example_rule(rule_id: str) -> dict[str, Any]:
    with open(_EXAMPLE_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError(f"{_EXAMPLE_PATH}: rules fehlt.")
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id") == rule_id:
            return copy.deepcopy(rule)
    raise ValueError(f"{_EXAMPLE_PATH}: Regel {rule_id} fehlt.")


def _rules(doc: dict[str, Any] | None) -> list[Any] | None:
    if not isinstance(doc, dict):
        return None
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return None
    return rules


def _find_rule(rules: list[Any], rule_id: str) -> dict[str, Any] | None:
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id") == rule_id:
            return rule
    return None


def _uses_removed_predicate(rule: Any) -> bool:
    return isinstance(rule, dict) and REMOVED_PREDICATE in (rule.get("when") or [])


def _error_rule_is_shipped_power_form(rules: list[Any]) -> bool:
    rule = _find_rule(rules, ERROR_RULE_ID)
    return rule is not None and rule.get("when") == _OLD_ERROR_WHEN


def detect(docs: Docs) -> bool:
    doc = docs.get("deviation_rules.json")
    # Only after structural dm4 migration; dm5 packs still get the rule.
    version = read_data_model(doc if isinstance(doc, dict) else None)
    if version is None or version < 4:
        return False
    rules = _rules(doc if isinstance(doc, dict) else None)
    if rules is None:
        return False
    if _find_rule(rules, RULE_ID) is None:
        return True
    if any(_uses_removed_predicate(rule) for rule in rules):
        return True
    return _error_rule_is_shipped_power_form(rules)


def _insert_rule(rules: list[Any], rule: dict[str, Any]) -> list[Any]:
    updated = list(rules)
    for index, item in enumerate(updated):
        if isinstance(item, dict) and item.get("id") == ERROR_RULE_ID:
            updated.insert(index + 1, rule)
            return updated
    updated.append(rule)
    return updated


def _adopt_energy_form(rule: dict[str, Any], example: dict[str, Any]) -> None:
    """Take ``when`` / ``params`` from the example; keep a custom message."""
    rule["when"] = list(example["when"])
    params = dict(rule.get("params") or {})
    params.update(example["params"])
    rule["params"] = params
    if rule.get("message") in _SHIPPED_MESSAGES:
        rule["message"] = example["message"]


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {key: copy.deepcopy(value) for key, value in docs.items()}
    doc = out.get("deviation_rules.json")
    rules = _rules(doc if isinstance(doc, dict) else None)
    if not isinstance(doc, dict) or rules is None or not detect(out):
        return StepResult(docs=out, changed_files=())
    warning_example = _example_rule(RULE_ID)
    for rule in rules:
        if _uses_removed_predicate(rule):
            _adopt_energy_form(rule, warning_example)
    if _error_rule_is_shipped_power_form(rules):
        _adopt_energy_form(
            _find_rule(rules, ERROR_RULE_ID) or {},
            _example_rule(ERROR_RULE_ID),
        )
    if _find_rule(rules, RULE_ID) is None:
        doc["rules"] = _insert_rule(rules, warning_example)
    return StepResult(docs=out, changed_files=("deviation_rules.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Zwangs-Laden nach Zielenergie bewerten (Warnung < 80 %, Fehler < 60 %)",
    files=("deviation_rules.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
