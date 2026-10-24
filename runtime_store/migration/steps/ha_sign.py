"""Step dm4.ha_sign — keep or remove a leftover ``ehal.ha.sign`` (issue #56).

Only offered when the chain starts at earnie_data_model 3 (``detect_on_start``), HA
backend, non-empty ``ehal.ha.sign``. In 2.6.x Earnie read raw HA states and flipped them
with ``sign``; in 2.7 HA pushes the values and ``sign`` is applied on top of the push
(``integrations/ha_push_read.py``). Where the pushed values already carry the EHAL sign,
the old entry flips them twice. ``sign`` stays a supported setting for hub-native signs,
so the choice is the user's. After the run the pack is model 4 and the question never
comes back, also when the user keeps the entry.
"""
from __future__ import annotations

import copy
from typing import Any

from runtime_store.data_model import stamp_data_model
from runtime_store.ehal_setup import BACKEND_HA, normalize_backend
from runtime_store.migration.steps.loxone_binding_names import detect_on_start
from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    ManualTodo,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "dm4.ha_sign"
Q_SIGN = "ha_sign.remove"
CHOICE_KEEP = "Behalten"
CHOICE_REMOVE = "Entfernen"

QUESTIONS = (
    Question(
        id=Q_SIGN,
        step_id=STEP_ID,
        prompt_de=(
            "Home Assistant: In `config.json` steht noch `ehal.ha.sign` aus 2.6. "
            "Earnie wendet dieses Vorzeichen in 2.7 zusätzlich auf die von HA "
            "gepushten Werte an. Liefert HA die Werte bereits im EHAL-Vorzeichen "
            "(Netz + = Bezug, Batterie + = Entladen), werden sie doppelt gedreht "
            "(Live-Lesen zeigt +1130 W, die Live-Leistungszeile −1,13 kW). "
            "„Entfernen“ leert `ehal.ha.sign`. „Behalten“ ist nur richtig, wenn Ihre "
            "gepushten Werte noch das Hersteller-Vorzeichen tragen."
        ),
        kind="choice",
        required=True,
        choices=(CHOICE_KEEP, CHOICE_REMOVE),
    ),
)


def _ha_block(docs: Docs) -> dict[str, Any] | None:
    config = docs.get("config.json")
    ehal = config.get("ehal") if isinstance(config, dict) else None
    if not isinstance(ehal, dict) or normalize_backend(ehal.get("backend")) != BACKEND_HA:
        return None
    ha = ehal.get("ha")
    return ha if isinstance(ha, dict) else None


def _sign_entries(ha: dict[str, Any] | None) -> dict[str, Any]:
    sign = ha.get("sign") if isinstance(ha, dict) else None
    if not isinstance(sign, dict):
        return {}
    return {k: v for k, v in sign.items() if str(v or "").strip()}


def detect(docs: Docs) -> bool:
    return bool(_sign_entries(_ha_block(docs)))


def apply(docs: Docs, answers: Answers) -> StepResult:
    choice = answers.get(Q_SIGN)
    if choice in (None, "", CHOICE_KEEP):
        # No answer: planner dry run, the runner requires it. Keep: nothing to change.
        return StepResult(docs=docs, changed_files=())
    if choice != CHOICE_REMOVE:
        return StepResult(
            docs=docs,
            changed_files=(),
            blockers=(
                Blocker(
                    step_id=STEP_ID,
                    message_de=(
                        f"Unbekannte Antwort '{choice}' für {Q_SIGN} "
                        f"(erlaubt: {CHOICE_KEEP}, {CHOICE_REMOVE})."
                    ),
                ),
            ),
        )
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    config = out["config.json"]
    config["ehal"]["ha"]["sign"] = {}
    stamp_data_model(config)
    return StepResult(docs=out, changed_files=("config.json",))


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    if not _sign_entries(_ha_block(before)) or _sign_entries(_ha_block(after)):
        return []
    return [
        ManualTodo(
            step_id=STEP_ID,
            text_de=(
                "Home Assistant: `ehal.ha.sign` wurde entfernt. Nach der Migration "
                "unter Echtzeit-Umgebung → EHAL-Com → Live-Lesen prüfen, dass "
                "Netzleistung (+ = Bezug) und Batterieleistung (+ = Entladen) mit der "
                "Live-Leistungszeile übereinstimmen. Trägt ein gepushter Wert noch das "
                "Hersteller-Vorzeichen, `ehal.ha.sign` für dieses Feld wieder auf "
                "`negate` setzen."
            ),
        )
    ]


STEP = MigrationStep(
    id=STEP_ID,
    data_model=4,
    title_de="Alte HA-Vorzeichen (ehal.ha.sign) behalten oder entfernen",
    files=("config.json",),
    detect=detect,
    apply=apply,
    questions=QUESTIONS,
    manual_todos=manual_todos,
    detect_on_start=detect_on_start,
)
