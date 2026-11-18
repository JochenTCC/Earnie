"""Step dm6.scenario_own_reference_removal — SE references are chosen per run, not per scenario.

Detect-based in-model step. Since the SE run page has three global reference boxes
(Historisch, Referenz ohne Speicher, L1), a scenario no longer says whether it gets its own
reference: ``own_reference`` is dropped from every scenario of ``backtesting_scenarios.json``.
The Live scenario always runs in the SE, so a Live entry with ``"enabled": false`` is set to
``true``. A leftover key fails loud in the loader (``settings.scenarios.normalize_scenario``,
``settings.live_scenario.ensure_live_scenario_enabled``).
"""
from __future__ import annotations

import copy
from typing import Any

from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm6.scenario_own_reference_removal"
SCENARIOS_FILE = "backtesting_scenarios.json"
CONFIG_FILE = "config.json"
REMOVED_SCENARIO_KEY = "own_reference"


def _entries(doc: Any) -> list[dict[str, Any]]:
    scenarios = doc.get("scenarios") if isinstance(doc, dict) else None
    return [entry for entry in scenarios if isinstance(entry, dict)] if isinstance(scenarios, list) else []


def _live_scenario_id(docs: Docs) -> str | None:
    config = docs.get(CONFIG_FILE)
    if not isinstance(config, dict):
        return None
    return str(config.get("live_scenario_id") or "").strip() or None


def _live_disabled(entry: dict[str, Any], live_id: str | None) -> bool:
    return (
        live_id is not None
        and str(entry.get("id") or "").strip() == live_id
        and entry.get("enabled", True) is False
    )


def detect(docs: Docs) -> bool:
    live_id = _live_scenario_id(docs)
    return any(
        REMOVED_SCENARIO_KEY in entry or _live_disabled(entry, live_id)
        for entry in _entries(docs.get(SCENARIOS_FILE))
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    if not detect(out):
        return StepResult(docs=out, changed_files=())
    live_id = _live_scenario_id(out)
    doc = out[SCENARIOS_FILE]
    for entry in _entries(doc):
        entry.pop(REMOVED_SCENARIO_KEY, None)
        if _live_disabled(entry, live_id):
            entry["enabled"] = True
    stamp_data_model(doc)
    return StepResult(docs=out, changed_files=(SCENARIOS_FILE,))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=6,
    title_de=(
        "Szenario-Schalter „Eigene Referenz ohne Optimierung“ entfernen (Referenzen wählt "
        "jetzt der Szenario-Explorer je Lauf); Live-Szenario ist im Szenario-Explorer immer aktiv"
    ),
    files=(SCENARIOS_FILE,),
    detect=detect,
    apply=apply,
    questions=(),
)
