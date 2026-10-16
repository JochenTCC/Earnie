"""Step dm4.pool_filter — MILP pool_filter + deviation scope rewrite."""
from __future__ import annotations

import copy

from house_config.migrate_pool_filter import (
    needs_pool_filter_migration,
    promote_pool_filter_milp,
    rewrite_deviation_filter_scopes,
)
from runtime_store.data_model import stamp_data_model
from runtime_store.migration.types import Answers, Docs, MigrationStep, StepResult

STEP_ID = "dm4.pool_filter"


def detect(docs: Docs) -> bool:
    return needs_pool_filter_migration(
        docs.get("house_profiles.json"),
        docs.get("deviation_rules.json"),
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed_files: list[str] = []

    house = out.get("house_profiles.json")
    if isinstance(house, dict):
        house_out, changed, _warnings = promote_pool_filter_milp(house)
        if changed:
            stamp_data_model(house_out)
            out["house_profiles.json"] = house_out
            changed_files.append("house_profiles.json")

    deviation = out.get("deviation_rules.json")
    if isinstance(deviation, dict):
        rules_out, rules_changed = rewrite_deviation_filter_scopes(deviation)
        if rules_changed:
            stamp_data_model(rules_out)
            out["deviation_rules.json"] = rules_out
            changed_files.append("deviation_rules.json")

    return StepResult(docs=out, changed_files=tuple(changed_files))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Pool-Filter MILP-Felder",
    files=("house_profiles.json", "deviation_rules.json"),
    detect=detect,
    apply=apply,
)
