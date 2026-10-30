"""dm4.forced_charge_hint — insert the yellow Zwangs-Laden target-miss rule."""
from __future__ import annotations

import copy

from runtime_store.migration.steps.forced_charge_hint import (
    RULE_ID,
    STEP_ID,
    apply,
    detect,
)


def _docs(*, with_rule: bool = False, model: int = 4) -> dict:
    rules = [
        {
            "id": "battery_forced_charge_missing",
            "enabled": True,
            "category": "error",
            "priority": 80,
            "scope": "battery",
            "when": ["mode_is_forced_charge", "battery_power_below_tolerance"],
            "message": "Zwangs-Laden nicht ausgeführt",
        }
    ]
    if with_rule:
        rules.append({"id": RULE_ID, "category": "hint", "priority": 1, "scope": "battery", "when": ["mode_is_forced_charge"], "message": "custom"})
    return {
        "deviation_rules.json": {
            "earnie_data_model": model,
            "rules": rules,
        }
    }


def test_detect_true_when_rule_missing():
    assert detect(_docs()) is True


def test_detect_true_on_data_model_5_pack():
    assert detect(_docs(model=5)) is True


def test_detect_false_when_rule_present():
    assert detect(_docs(with_rule=True)) is False


def test_detect_false_before_data_model_4():
    assert detect(_docs(model=3)) is False


def test_apply_inserts_example_rule_after_forced_charge_error():
    result = apply(_docs(), {})
    rules = result.docs["deviation_rules.json"]["rules"]
    assert result.changed_files == ("deviation_rules.json",)
    assert [rule["id"] for rule in rules] == [
        "battery_forced_charge_missing",
        RULE_ID,
    ]
    added = rules[1]
    assert added["category"] == "warning"
    assert "battery_charge_target_missed" in added["when"]
    assert detect(result.docs) is False


def test_apply_keeps_an_existing_rule():
    docs = _docs(with_rule=True)
    result = apply(docs, {})
    assert result.changed_files == ()
    assert result.docs["deviation_rules.json"]["rules"][1]["message"] == "custom"


def test_apply_idempotent():
    filled = apply(_docs(), {}).docs
    again = apply(copy.deepcopy(filled), {})
    assert again.changed_files == ()
    assert again.docs == filled


def test_step_id_stable():
    assert STEP_ID == "dm4.forced_charge_hint"
