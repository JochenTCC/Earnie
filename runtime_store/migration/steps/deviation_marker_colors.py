"""Step dm4.deviation_marker_colors — Hinweis green, Warnung yellow.

Detect-based (no data-model bump). Also moves
``battery_forced_charge_target_missed`` to category warning when that rule
is already present.

Only the values shipped before the change are replaced (hint yellow, warning
orange, the rule in category hint). An own colour or category stays, and the
step does not come back for it.
"""
from __future__ import annotations

import copy
from typing import Any

from runtime_store.data_model import read_data_model
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
# Shipped before this step (deviation_rules.example.json up to 2.7.0-beta.2).
OLD_HINT_COLOR = "#f1c40f"
OLD_WARNING_COLOR = "#e67e22"
OLD_RULE_CATEGORY = "hint"


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
    if doc is None:
        return False
    # Only after structural dm4 migration; dm5 packs still get the colors.
    version = read_data_model(doc)
    if version is None or version < 4:
        return False
    hint = _category_block(doc, "hint")
    if hint is not None and hint.get("color") == OLD_HINT_COLOR:
        return True
    warning = _category_block(doc, "warning")
    if warning is not None and warning.get("color") == OLD_WARNING_COLOR:
        return True
    rule = _target_rule(doc)
    return rule is not None and rule.get("category") == OLD_RULE_CATEGORY


def _replace_color(doc: dict[str, Any], name: str, old: str, new: str) -> None:
    block = _category_block(doc, name)
    if block is not None and block.get("color") == old:
        block["color"] = new


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {key: copy.deepcopy(value) for key, value in docs.items()}
    if not detect(out):
        return StepResult(docs=out, changed_files=())
    doc = _doc(out)
    if doc is None:
        return StepResult(docs=out, changed_files=())
    # Warning first: the old hint colour is the new warning colour.
    _replace_color(doc, "warning", OLD_WARNING_COLOR, WARNING_COLOR)
    _replace_color(doc, "hint", OLD_HINT_COLOR, HINT_COLOR)
    rule = _target_rule(doc)
    if rule is not None and rule.get("category") == OLD_RULE_CATEGORY:
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
