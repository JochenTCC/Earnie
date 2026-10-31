"""dm4.forced_charge_hint — grade Zwangs-Laden by delivered slot energy."""
from __future__ import annotations

import copy

from runtime_store.migration.steps.forced_charge_hint import (
    ERROR_RULE_ID,
    RULE_ID,
    STEP_ID,
    apply,
    detect,
)

_ENERGY_WHEN = ["mode_is_forced_charge", "battery_charge_energy_below_ratio"]
_BETA2_WARNING_MESSAGE = (
    "Zwangs-Laden: Zielenergie nicht erreicht "
    "(Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW)"
)
_ZIELLEISTUNG_MESSAGE = (
    "Zwangs-Laden: Zielleistung nicht erreicht "
    "(Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW)"
)


def _error_rule(
    *,
    when: list[str] | None = None,
    message: str = "Zwangs-Laden nicht ausgeführt",
) -> dict:
    return {
        "id": ERROR_RULE_ID,
        "enabled": True,
        "category": "error",
        "priority": 80,
        "scope": "battery",
        "when": when or ["mode_is_forced_charge", "battery_power_below_tolerance"],
        "message": message,
    }


def _warning_rule(*, when: list[str], message: str, params: dict | None = None) -> dict:
    rule = {
        "id": RULE_ID,
        "enabled": True,
        "category": "warning",
        "priority": 78,
        "scope": "battery",
        "when": when,
        "message": message,
    }
    if params is not None:
        rule["params"] = params
    return rule


def _docs(*rules: dict, model: int = 4) -> dict:
    return {
        "deviation_rules.json": {
            "earnie_data_model": model,
            "rules": list(rules),
        }
    }


def _beta2_docs(message: str = _BETA2_WARNING_MESSAGE) -> dict:
    """Pack after the 2.7.0-beta.2 step: movement predicate, kW wording."""
    return _docs(
        _error_rule(),
        _warning_rule(
            when=["mode_is_forced_charge", "battery_charge_target_missed"],
            message=message,
        ),
    )


def _by_id(result) -> dict[str, dict]:
    return {rule["id"]: rule for rule in result.docs["deviation_rules.json"]["rules"]}


def test_detect_true_when_rule_missing():
    assert detect(_docs(_error_rule())) is True


def test_detect_true_for_beta2_movement_predicate():
    assert detect(_beta2_docs()) is True


def test_detect_true_when_error_rule_has_shipped_power_form():
    docs = _docs(
        _error_rule(),
        _warning_rule(when=_ENERGY_WHEN, message="x", params={"max_ratio": 0.8}),
    )
    assert detect(docs) is True


def test_detect_false_before_data_model_4():
    assert detect(_docs(_error_rule(), model=3)) is False


def test_apply_inserts_energy_rules_after_forced_charge_error():
    result = apply(_docs(_error_rule()), {})
    assert result.changed_files == ("deviation_rules.json",)
    rules = result.docs["deviation_rules.json"]["rules"]
    assert [rule["id"] for rule in rules] == [ERROR_RULE_ID, RULE_ID]
    error, warning = rules
    assert error["when"] == _ENERGY_WHEN
    assert error["params"] == {"max_ratio": 0.6, "min_shortfall_kwh": 0.1}
    assert "Zielenergie" in error["message"] and "kWh" in error["message"]
    assert warning["category"] == "warning"
    assert warning["when"] == _ENERGY_WHEN
    assert warning["params"] == {"max_ratio": 0.8, "min_shortfall_kwh": 0.1}
    assert "{ratio_pct" in warning["message"] and "kWh" in warning["message"]
    assert detect(result.docs) is False


def test_apply_migrates_beta2_pack():
    for message in (_BETA2_WARNING_MESSAGE, _ZIELLEISTUNG_MESSAGE):
        result = apply(_beta2_docs(message), {})
        rules = _by_id(result)
        assert rules[RULE_ID]["when"] == _ENERGY_WHEN
        assert rules[RULE_ID]["params"] == {"max_ratio": 0.8, "min_shortfall_kwh": 0.1}
        assert "kWh" in rules[RULE_ID]["message"]
        assert rules[ERROR_RULE_ID]["params"] == {"max_ratio": 0.6, "min_shortfall_kwh": 0.1}
        assert detect(result.docs) is False


def test_apply_keeps_custom_messages():
    docs = _docs(
        _error_rule(message="eigener Fehlertext"),
        _warning_rule(
            when=["mode_is_forced_charge", "battery_charge_target_missed"],
            message="eigener Warntext",
        ),
    )
    rules = _by_id(apply(docs, {}))
    assert rules[ERROR_RULE_ID]["message"] == "eigener Fehlertext"
    assert rules[RULE_ID]["message"] == "eigener Warntext"
    assert rules[RULE_ID]["when"] == _ENERGY_WHEN


def test_apply_keeps_a_customised_error_rule():
    custom_when = ["mode_is_forced_charge", "battery_power_below_tolerance", "plugged_in"]
    docs = _docs(
        _error_rule(when=custom_when),
        _warning_rule(when=_ENERGY_WHEN, message="x", params={"max_ratio": 0.7}),
    )
    assert detect(docs) is False
    result = apply(docs, {})
    assert result.changed_files == ()
    assert _by_id(result)[ERROR_RULE_ID]["when"] == custom_when


def test_apply_idempotent():
    filled = apply(_beta2_docs(), {}).docs
    again = apply(copy.deepcopy(filled), {})
    assert again.changed_files == ()
    assert again.docs == filled


def test_step_id_stable():
    assert STEP_ID == "dm4.forced_charge_hint"
