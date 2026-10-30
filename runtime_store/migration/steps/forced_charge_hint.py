"""Step dm4.forced_charge_hint — add the Zwangs-Laden target-miss warning.

Detect-based (no data-model bump). Inserts ``battery_forced_charge_target_missed``
from the bundled example when that id is absent. Existing rules stay unchanged.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.forced_charge_hint"
RULE_ID = "battery_forced_charge_target_missed"
_AFTER_ID = "battery_forced_charge_missing"
_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "share"
    / "config"
    / "deviation_rules.example.json"
)


@lru_cache(maxsize=1)
def _example_rule() -> dict[str, Any]:
    with open(_EXAMPLE_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError(f"{_EXAMPLE_PATH}: rules fehlt.")
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id") == RULE_ID:
            return copy.deepcopy(rule)
    raise ValueError(f"{_EXAMPLE_PATH}: Regel {RULE_ID} fehlt.")


def _rules(doc: dict[str, Any] | None) -> list[Any] | None:
    if not isinstance(doc, dict):
        return None
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return None
    return rules


def _has_rule(rules: list[Any]) -> bool:
    return any(isinstance(rule, dict) and rule.get("id") == RULE_ID for rule in rules)


def detect(docs: Docs) -> bool:
    doc = docs.get("deviation_rules.json")
    if read_data_model(doc if isinstance(doc, dict) else None) != CURRENT_DATA_MODEL:
        return False
    rules = _rules(doc if isinstance(doc, dict) else None)
    if rules is None:
        return False
    return not _has_rule(rules)


def _insert_rule(rules: list[Any], rule: dict[str, Any]) -> list[Any]:
    updated = list(rules)
    for index, item in enumerate(updated):
        if isinstance(item, dict) and item.get("id") == _AFTER_ID:
            updated.insert(index + 1, rule)
            return updated
    updated.append(rule)
    return updated


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {key: copy.deepcopy(value) for key, value in docs.items()}
    doc = out.get("deviation_rules.json")
    rules = _rules(doc if isinstance(doc, dict) else None)
    if not isinstance(doc, dict) or rules is None or _has_rule(rules):
        return StepResult(docs=out, changed_files=())
    updated = dict(doc)
    updated["rules"] = _insert_rule(rules, _example_rule())
    out["deviation_rules.json"] = updated
    return StepResult(docs=out, changed_files=("deviation_rules.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Warnung für verfehlte Zwangs-Lade-Energie ergänzen",
    files=("deviation_rules.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
