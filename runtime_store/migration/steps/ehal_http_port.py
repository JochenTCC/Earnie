"""Step dm4.ehal_http_port — rename system.ehal_loxone_http_port (Binding Lx3).

Detect-based: packs that still store the Loxone-prefixed key get
``system.ehal_http_port``. Loaders also alias-read the old key until migrated.
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

STEP_ID = "dm4.ehal_http_port"
_OLD = "ehal_loxone_http_port"
_NEW = "ehal_http_port"


def detect(docs: Docs) -> bool:
    config = docs.get("config.json")
    if not isinstance(config, dict):
        return False
    system = config.get("system")
    return isinstance(system, dict) and _OLD in system


def apply(docs: Docs, answers: Answers) -> StepResult:
    _ = answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    config = out.get("config.json")
    if not isinstance(config, dict):
        return StepResult(docs=out, changed_files=())
    system = config.get("system")
    if not isinstance(system, dict) or _OLD not in system:
        return StepResult(docs=out, changed_files=())
    system = dict(system)
    if _NEW not in system:
        system[_NEW] = system[_OLD]
    system.pop(_OLD, None)
    config = dict(config)
    config["system"] = system
    stamp_data_model(config)
    out["config.json"] = config
    return StepResult(docs=out, changed_files=("config.json",))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Daemon-HTTP-Port umbenennen (ehal_http_port)",
    files=("config.json",),
    detect=detect,
    apply=apply,
    questions=(),
)
