"""Step dm4.deviation_energy_shortfall — energy rules need an absolute shortfall.

Detect-based (no data-model bump). An energy rule fires only when the ratio is
violated **and** the slot is more than ``params.min_shortfall_kwh`` short. The
step

- adds ``min_shortfall_kwh`` (value from the bundled example) to every rule
  using ``battery_charge_energy_below_ratio`` without it,
- rewrites the heat-pump rule (``wp_heating_enable_no_start`` /
  ``waermepumpe_enable_no_start``) while it has the shipped
  ``power_mismatch_positive`` form to ``power_energy_below_ratio``.

Existing parameters stay; shipped messages are replaced, custom messages stay.
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

STEP_ID = "dm4.deviation_energy_shortfall"
BATTERY_PREDICATE = "battery_charge_energy_below_ratio"
SHORTFALL_PARAM = "min_shortfall_kwh"
FORCED_CHARGE_WARNING_ID = "battery_forced_charge_target_missed"
WP_EXAMPLE_ID = "wp_heating_enable_no_start"
WP_RULE_IDS = frozenset({WP_EXAMPLE_ID, "waermepumpe_enable_no_start"})
_OLD_WP_WHEN = ["power_mismatch_positive"]
_SHIPPED_WP_MESSAGE = (
    "Wärmepumpe: Freigabe, aber nicht angesprungen "
    "(Soll {soll_kw:.2f} kW, Ist {ist_kw:.2f} kW)"
)
_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "share"
    / "config"
    / "deviation_rules.example.json"
)


@lru_cache(maxsize=1)
def _example_rules() -> dict[str, dict[str, Any]]:
    with open(_EXAMPLE_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError(f"{_EXAMPLE_PATH}: rules fehlt.")
    return {
        rule["id"]: rule
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str)
    }


def _example_rule(rule_id: str) -> dict[str, Any]:
    rule = _example_rules().get(rule_id)
    if rule is None:
        raise ValueError(f"{_EXAMPLE_PATH}: Regel {rule_id} fehlt.")
    return copy.deepcopy(rule)


def _example_shortfall(rule_id: str) -> float:
    """Shortfall of the example rule with this id; custom ids take the warning's."""
    example_id = rule_id if rule_id in _example_rules() else FORCED_CHARGE_WARNING_ID
    return float(_example_rule(example_id)["params"][SHORTFALL_PARAM])


def _rules(doc: Any) -> list[Any] | None:
    if not isinstance(doc, dict):
        return None
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return None
    return rules


def _battery_rule_lacks_shortfall(rule: Any) -> bool:
    if not isinstance(rule, dict) or BATTERY_PREDICATE not in (rule.get("when") or []):
        return False
    return SHORTFALL_PARAM not in (rule.get("params") or {})


def _is_shipped_wp_rule(rule: Any) -> bool:
    return (
        isinstance(rule, dict)
        and rule.get("id") in WP_RULE_IDS
        and rule.get("when") == _OLD_WP_WHEN
    )


def detect(docs: Docs) -> bool:
    doc = docs.get("deviation_rules.json")
    if read_data_model(doc if isinstance(doc, dict) else None) != CURRENT_DATA_MODEL:
        return False
    rules = _rules(doc)
    if rules is None:
        return False
    return any(
        _battery_rule_lacks_shortfall(rule) or _is_shipped_wp_rule(rule)
        for rule in rules
    )


def _adopt_wp_energy_form(rule: dict[str, Any]) -> None:
    example = _example_rule(WP_EXAMPLE_ID)
    rule["when"] = list(example["when"])
    params = dict(example["params"])
    params.update(rule.get("params") or {})
    rule["params"] = params
    if rule.get("message") == _SHIPPED_WP_MESSAGE:
        rule["message"] = example["message"]


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {key: copy.deepcopy(value) for key, value in docs.items()}
    rules = _rules(out.get("deviation_rules.json"))
    if rules is None or not detect(out):
        return StepResult(docs=out, changed_files=())
    for rule in rules:
        if _battery_rule_lacks_shortfall(rule):
            params = dict(rule.get("params") or {})
            params[SHORTFALL_PARAM] = _example_shortfall(str(rule.get("id")))
            rule["params"] = params
        elif _is_shipped_wp_rule(rule):
            _adopt_wp_energy_form(rule)
    return StepResult(docs=out, changed_files=("deviation_rules.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de=(
        "Abweichungsregeln Zwangs-Laden und Wärmepumpe: zusätzlich "
        "Mindest-Fehlmenge 0,1 kWh pro Slot"
    ),
    files=("deviation_rules.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
