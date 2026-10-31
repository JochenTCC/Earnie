"""dm4.deviation_energy_shortfall — energy rules need an absolute shortfall."""
from __future__ import annotations

import copy

from runtime_store.migration.steps.deviation_energy_shortfall import (
    STEP_ID,
    apply,
    detect,
)

_ENERGY_WHEN = ["mode_is_forced_charge", "battery_charge_energy_below_ratio"]
_SHIPPED_WP_MESSAGE = (
    "Wärmepumpe: Freigabe, aber nicht angesprungen "
    "(Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW)"
)


def _battery_rule(rule_id: str, max_ratio: float, **extra_params) -> dict:
    return {
        "id": rule_id,
        "enabled": True,
        "category": "error",
        "priority": 80,
        "scope": "battery",
        "when": list(_ENERGY_WHEN),
        "params": {"max_ratio": max_ratio, **extra_params},
        "message": "x",
    }


def _wp_rule(
    rule_id: str = "waermepumpe_enable_no_start",
    *,
    when: list[str] | None = None,
    message: str = _SHIPPED_WP_MESSAGE,
) -> dict:
    return {
        "id": rule_id,
        "enabled": True,
        "category": "hint",
        "priority": 40,
        "scope": "waermepumpe",
        "when": when or ["power_mismatch_positive"],
        "message": message,
    }


def _docs(*rules: dict, model: int = 4) -> dict:
    return {
        "deviation_rules.json": {
            "earnie_data_model": model,
            "rules": list(rules),
        }
    }


def _beta3_docs() -> dict:
    """Pack after dm4.forced_charge_hint (2.7.0-beta.3): ratio only."""
    return _docs(
        _battery_rule("battery_forced_charge_missing", 0.6),
        _battery_rule("battery_forced_charge_target_missed", 0.8),
        _wp_rule(),
    )


def _by_id(result) -> dict[str, dict]:
    return {rule["id"]: rule for rule in result.docs["deviation_rules.json"]["rules"]}


def test_detect_true_for_ratio_only_battery_rule():
    assert detect(_docs(_battery_rule("battery_forced_charge_missing", 0.6))) is True


def test_detect_true_for_shipped_wp_rule():
    assert detect(_docs(_wp_rule())) is True
    assert detect(_docs(_wp_rule("wp_heating_enable_no_start"))) is True


def test_detect_false_before_data_model_4():
    assert detect(_docs(_wp_rule(), model=3)) is False


def test_apply_adds_shortfall_and_reworks_wp_rule():
    result = apply(_beta3_docs(), {})
    assert result.changed_files == ("deviation_rules.json",)
    rules = _by_id(result)
    assert rules["battery_forced_charge_missing"]["params"] == {
        "max_ratio": 0.6,
        "min_shortfall_kwh": 0.1,
    }
    assert rules["battery_forced_charge_target_missed"]["params"] == {
        "max_ratio": 0.8,
        "min_shortfall_kwh": 0.1,
    }
    wp = rules["waermepumpe_enable_no_start"]
    assert wp["when"] == ["power_energy_below_ratio"]
    assert wp["params"] == {"max_ratio": 0.5, "min_shortfall_kwh": 0.1}
    assert wp["scope"] == "waermepumpe"
    assert "{ratio_pct" in wp["message"] and "kWh" in wp["message"]
    assert detect(result.docs) is False


def test_apply_keeps_custom_values_and_messages():
    docs = _docs(
        _battery_rule("battery_forced_charge_missing", 0.5, min_shortfall_kwh=0.3),
        _battery_rule("my_forced_charge_rule", 0.7),
        _wp_rule(message="eigener WP-Text"),
    )
    rules = _by_id(apply(docs, {}))
    assert rules["battery_forced_charge_missing"]["params"] == {
        "max_ratio": 0.5,
        "min_shortfall_kwh": 0.3,
    }
    assert rules["my_forced_charge_rule"]["params"] == {
        "max_ratio": 0.7,
        "min_shortfall_kwh": 0.1,
    }
    assert rules["waermepumpe_enable_no_start"]["message"] == "eigener WP-Text"
    assert rules["waermepumpe_enable_no_start"]["when"] == ["power_energy_below_ratio"]


def test_apply_keeps_a_customised_wp_rule():
    custom_when = ["power_mismatch_positive", "heating_was_scheduled"]
    docs = _docs(_wp_rule(when=custom_when))
    assert detect(docs) is False
    result = apply(docs, {})
    assert result.changed_files == ()
    assert _by_id(result)["waermepumpe_enable_no_start"]["when"] == custom_when


def test_apply_idempotent():
    filled = apply(_beta3_docs(), {}).docs
    again = apply(copy.deepcopy(filled), {})
    assert again.changed_files == ()
    assert again.docs == filled


def test_step_id_stable():
    assert STEP_ID == "dm4.deviation_energy_shortfall"
