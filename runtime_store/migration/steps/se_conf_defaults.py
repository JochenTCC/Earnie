"""Step dm4.se_conf_defaults — fill missing scenario_explorer_conf keys from example.

Detect-based (no data-model bump). Existing keys stay unchanged; only keys
present in the bundled ``config.example.json`` block are added when missing.
Legacy SE path keys are never copied.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime_store.data_model import CURRENT_DATA_MODEL, read_data_model, stamp_data_model
from runtime_store.migration.types import (
    Answers,
    Docs,
    MigrationStep,
    StepResult,
)

STEP_ID = "dm4.se_conf_defaults"
_BLOCK = "scenario_explorer_conf"
_LEGACY_KEYS = frozenset({"path_consumption", "path_production"})
# Absolute: import/migrate may run after chdir (config-pack tests, containers).
_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[3] / "share" / "config" / "config.example.json"
)


@lru_cache(maxsize=1)
def _example_se_conf() -> dict[str, Any]:
    path = _EXAMPLE_PATH
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} muss ein JSON-Objekt sein.")
    block = data.get(_BLOCK)
    if not isinstance(block, dict):
        raise ValueError(f"{path}: {_BLOCK} fehlt oder ist kein Objekt.")
    return {
        key: copy.deepcopy(value)
        for key, value in block.items()
        if key not in _LEGACY_KEYS
    }


def _missing_keys(actual: dict[str, Any] | None) -> list[str]:
    example = _example_se_conf()
    if not isinstance(actual, dict):
        return sorted(example.keys())
    return sorted(key for key in example if key not in actual)


def detect(docs: Docs) -> bool:
    config = docs.get("config.json")
    if not isinstance(config, dict):
        return False
    # Only after structural dm4 migration — never stamp v1/v2 packs via this fill.
    if read_data_model(config) != CURRENT_DATA_MODEL:
        return False
    block = config.get(_BLOCK)
    return bool(_missing_keys(block if isinstance(block, dict) else None))


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    config = out.get("config.json")
    if not isinstance(config, dict):
        return StepResult(docs=out, changed_files=())
    block = config.get(_BLOCK)
    actual = dict(block) if isinstance(block, dict) else {}
    missing = _missing_keys(actual)
    if not missing:
        return StepResult(docs=out, changed_files=())
    example = _example_se_conf()
    for key in missing:
        actual[key] = copy.deepcopy(example[key])
    config = dict(config)
    config[_BLOCK] = actual
    stamp_data_model(config)
    out["config.json"] = config
    return StepResult(docs=out, changed_files=("config.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Szenario-Explorer-Defaults ergänzen",
    files=("config.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
