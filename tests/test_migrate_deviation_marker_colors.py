"""dm4.deviation_marker_colors — Hinweis green, Warnung yellow."""
from __future__ import annotations

import copy

from runtime_store.migration.steps.deviation_marker_colors import (
    HINT_COLOR,
    RULE_ID,
    STEP_ID,
    WARNING_COLOR,
    apply,
    detect,
)


def _docs(
    *,
    hint: str = "#f1c40f",
    warning: str = "#e67e22",
    rule: str | None = "hint",
    model: int = 4,
) -> dict:
    rules: list[dict] = []
    if rule is not None:
        rules.append({
            "id": RULE_ID,
            "category": rule,
            "scope": "battery",
            "when": ["mode_is_forced_charge"],
            "message": "x",
        })
    return {
        "deviation_rules.json": {
            "earnie_data_model": model,
            "categories": {
                "hint": {"label": "Hinweis", "symbol": "triangle-up", "color": hint},
                "warning": {"label": "Warnung", "symbol": "diamond", "color": warning},
            },
            "rules": rules,
        }
    }


def test_detect_true_for_old_palette():
    assert detect(_docs()) is True


def test_detect_true_when_only_the_rule_category_is_old():
    assert detect(_docs(hint=HINT_COLOR, warning=WARNING_COLOR, rule="hint")) is True


def test_detect_false_when_already_current():
    assert detect(_docs(hint=HINT_COLOR, warning=WARNING_COLOR, rule="warning")) is False


def test_detect_false_without_the_rule_once_colors_match():
    assert detect(_docs(hint=HINT_COLOR, warning=WARNING_COLOR, rule=None)) is False


def test_detect_false_when_categories_are_absent():
    docs = _docs(rule="warning")
    del docs["deviation_rules.json"]["categories"]
    assert detect(docs) is False


def test_detect_false_before_data_model_4():
    assert detect(_docs(model=3)) is False


def test_apply_sets_colors_and_rule_category():
    result = apply(_docs(), {})
    doc = result.docs["deviation_rules.json"]
    assert result.changed_files == ("deviation_rules.json",)
    assert doc["categories"]["hint"]["color"] == HINT_COLOR
    assert doc["categories"]["warning"]["color"] == WARNING_COLOR
    assert doc["rules"][0]["category"] == "warning"
    assert detect(result.docs) is False


def test_apply_idempotent():
    filled = apply(_docs(), {}).docs
    again = apply(copy.deepcopy(filled), {})
    assert again.changed_files == ()
    assert again.docs == filled


def test_step_id_stable():
    assert STEP_ID == "dm4.deviation_marker_colors"
