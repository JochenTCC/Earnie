"""Step dm5.vat_deductible — house-profile VAT flag (D3a), written explicitly as ``false``.

Every profile without ``vat_deductible`` gets ``false`` ("the operator cannot deduct input
VAT"), the documented schema default. The code does not read the flag until the VAT model
lands; the step only makes the field visible in every pack of the 2.8 wizard run (SUSI P6
step). Decision memo: ``docs/dev/data-model-stability-decisions.md`` § D3.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.profiles_store import VAT_DEDUCTIBLE_KEY
from runtime_store.migration.types import Answers, Docs, MigrationStep, StepResult

STEP_ID = "dm5.vat_deductible"
HOUSE_FILE = "house_profiles.json"


def _iter_profiles(house: Any) -> Iterator[dict[str, Any]]:
    profiles = house.get("profiles") if isinstance(house, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    for profile in items:
        if isinstance(profile, dict):
            yield profile


def detect(docs: Docs) -> bool:
    return any(VAT_DEDUCTIBLE_KEY not in p for p in _iter_profiles(docs.get(HOUSE_FILE)))


def apply(docs: Docs, answers: Answers) -> StepResult:
    del answers
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    for profile in _iter_profiles(out.get(HOUSE_FILE)):
        profile.setdefault(VAT_DEDUCTIBLE_KEY, False)
    changed = (HOUSE_FILE,) if out.get(HOUSE_FILE) != docs.get(HOUSE_FILE) else ()
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 5: Hausprofil-Feld vat_deductible (Vorsteuerabzug, noch nicht ausgewertet)",
    files=(HOUSE_FILE,),
    detect=detect,
    apply=apply,
)
