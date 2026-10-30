"""Step dm4.deviation_marker_colors — Hinweis green, Warnung yellow.

Detect-based (no data-model bump). Also moves
``battery_forced_charge_target_missed`` to category warning when that rule
is already present.
"""
from __future__ import annotations

import copy
from typing import Any

from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.deviation_marker_colors"
HINT_COLOR = "#27ae60"
WARNING_COLOR = "#f1c40f"
RULE_ID = "battery_forced_charge_target_missed"
RULE_CATEGORY = "warning"


def _doc(docs: Docs) -> dict[str, Any] | None:
    doc = docs.get("deviation_rules.json")
    if isinstance(doc, dict):
        return doc
    return None


def _category_block(doc: dict[str, Any], name: str) -> dict[str, Any] | None:
    categories = doc.get("categories")
    if not isinstance(categories, dict):
        return None
    block = categories.get(name)
    if isinstance(block, dict):
        return block
    return None


def _target_rule(doc: dict[str, Any]) -> dict[str, Any] | None:
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return None
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id") == RULE_ID:
            return rule
    return None


def detect(docs: Docs) -> bool:
    doc = _doc(docs)
    if doc is None or read_data_model(doc) != CURRENT_DATA_MODEL:
        return False
    hint = _category_block(doc, "hint")
    if hint is not None and hint.get("color") != HINT_COLOR:
        return True
    warning = _category_block(doc, "warning")
    if warning is not None and warning.get("color") != WARNING_COLOR:
        return True
    rule = _target_rule(doc)
    return rule is not None and rule.get("category") != RULE_CATEGORY


def _set_color(doc: dict[str, Any], name: str, color: str) -> None:
    block = _category_block(doc, name)
    if block is not None:
        block["color"] = color


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {key: copy.deepcopy(value) for key, value in docs.items()}
    if not detect(out):
        return StepResult(docs=out, changed_files=())
    doc = _doc(out)
    if doc is None:
        return StepResult(docs=out, changed_files=())
    _set_color(doc, "hint", HINT_COLOR)
    _set_color(doc, "warning", WARNING_COLOR)
    rule = _target_rule(doc)
    if rule is not None:
        rule["category"] = RULE_CATEGORY
    return StepResult(docs=out, changed_files=("deviation_rules.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Abweichungsmarker: Hinweis grün, Warnung gelb",
    files=("deviation_rules.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
