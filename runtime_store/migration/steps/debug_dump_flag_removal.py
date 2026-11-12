"""Step dm6.debug_dump_flag_removal — drop ``ui.chart_debug_capture_enabled``.

Detect-based in-model step: the support package ("Sichern & Übertragen" in the
sidebar) is always available, so the old enable switch for the Monitor-page
Debug-Dump button is gone. A leftover key after this step fails loud in the
loader (``settings.system_settings.reject_removed_debug_dump_flag``).
"""
from __future__ import annotations

import copy

from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm6.debug_dump_flag_removal"
REMOVED_UI_KEY = "chart_debug_capture_enabled"


def detect(docs: Docs) -> bool:
    config = docs.get("config.json")
    if not isinstance(config, dict):
        return False
    ui = config.get("ui")
    return isinstance(ui, dict) and REMOVED_UI_KEY in ui


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    if not detect(out):
        return StepResult(docs=out, changed_files=())
    config = dict(out["config.json"])
    ui = dict(config["ui"])
    ui.pop(REMOVED_UI_KEY)
    config["ui"] = ui
    stamp_data_model(config)
    out["config.json"] = config
    return StepResult(docs=out, changed_files=("config.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=6,
    title_de="Schalter für den Debug-Dump entfernen (Support-Paket ist immer verfügbar)",
    files=("config.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
