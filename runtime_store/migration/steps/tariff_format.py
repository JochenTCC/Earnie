"""Step tf1.tariff_format — tariff-track files to ``tariff_format: 1`` (Edibert P2).

Thin wrapper around Edibert's pure migration (``edibert.api.plan_migration`` / ``migrate``
through ``house_config.edibert_tariffs``): tags ``tariffs.json``, ``user_tariffs.json``,
``grid_fees.json`` and ``user_grid_fees.json``, drops ``earnie_data_model`` from them, writes
the user grid areas handed over by ``dm5.netznutzung_split`` and asks for the VAT rate of
every user tariff without one (required, the country rate is only a suggestion).
Since the Edibert pin ``v0.1.12`` it also moves a ``grid_monthly_fee_eur`` of the user tariffs
into the grid area the house profiles use (``grid_fee_area``): only when every profile names the
same area; Edibert blocks a catalog area, an area missing from ``user_grid_fees.json`` and
differing values, so nothing is guessed.
Runs after the Earnie-track steps in the same wizard run and backup.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from house_config.edibert_tariffs import (
    EdibertLoadError,
    migrate_tariff_files,
    migration_blocker_de,
    plan_tariff_migration,
)
from runtime_store.data_model import TARIFF_TRACK_FILES
from runtime_store.migration.types import (
    HANDOFF_USER_GRID_AREAS,
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "tf1.tariff_format"
USER_TARIFFS = "user_tariffs.json"
HOUSE_PROFILES = "house_profiles.json"
_DIRECTION_DE = {"import": "Bezug", "export": "Einspeisung"}
_PRICES_DE = {"gross": "Preise brutto", "net": "Preise netto"}


def _tariff_docs(docs: Docs) -> dict[str, dict[str, Any]]:
    return {
        name: docs[name]
        for name in sorted(TARIFF_TRACK_FILES)
        if isinstance(docs.get(name), dict)
    }


def _handed_areas(docs: Docs) -> tuple[dict[str, Any], ...]:
    handoff = docs.get(HANDOFF_USER_GRID_AREAS)
    if not isinstance(handoff, dict):
        return ()
    return tuple(handoff.get("areas") or ())


def _grid_fee_area(docs: Docs) -> str | None:
    """The grid area every house profile uses; ``None`` when they differ or none is named."""
    house = docs.get(HOUSE_PROFILES)
    if not isinstance(house, dict):
        return None
    areas = {
        (profile.get("netznutzung") or {}).get("area_id")
        for profile in house.get("profiles") or ()
        if isinstance(profile, dict)
    }
    if len(areas) != 1:
        return None
    (area,) = areas
    return area if isinstance(area, str) and area else None


def _plan(docs: Docs):
    return plan_tariff_migration(
        _tariff_docs(docs),
        user_grid_areas=_handed_areas(docs),
        grid_fee_area=_grid_fee_area(docs),
    )


def detect(docs: Docs) -> bool:
    if _handed_areas(docs):
        return True
    if not _tariff_docs(docs):
        return False
    return _plan(docs).needed


def _prompt_de(params: dict[str, Any], default: float | None) -> str:
    label = params.get("label") or params.get("tariff_id")
    direction = _DIRECTION_DE.get(str(params.get("direction")), str(params.get("direction")))
    prices = _PRICES_DE.get(str(params.get("prices")), str(params.get("prices")))
    text = (
        f"Benutzertarif „{label}“ ({params.get('tariff_id')}, {direction}, {prices}): "
        "USt-Satz in Prozent angeben (Pflicht ab Tarifformat 1, 0 erlaubt)."
    )
    if default is not None:
        text += f" Vorschlag für {params.get('land')}: {default:g} %."
    return text


def questions_for(docs: Docs) -> tuple[Question, ...]:
    if not _tariff_docs(docs):
        return ()
    return tuple(
        Question(
            id=question.id,
            step_id=STEP_ID,
            prompt_de=_prompt_de(dict(question.params), question.default),
            kind="number",
            required=bool(question.required),
            default=question.default,
        )
        for question in _plan(docs).questions
    )


def _number(question_id: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{question_id}: '{value}' ist keine Zahl.")
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"{question_id}: '{value}' ist keine Zahl.") from exc
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{question_id}: USt-Satz muss eine Zahl >= 0 sein (war {value!r}).")
    return float(value)


def _blocked(docs: Docs, messages: list[str]) -> StepResult:
    return StepResult(
        docs=docs,
        changed_files=(),
        blockers=tuple(Blocker(step_id=STEP_ID, message_de=m) for m in messages),
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    tariff_docs = _tariff_docs(docs)
    areas = _handed_areas(docs)
    target = _grid_fee_area(docs)
    plan = plan_tariff_migration(tariff_docs, user_grid_areas=areas, grid_fee_area=target)
    if plan.blockers:
        return _blocked(docs, [migration_blocker_de(b) for b in plan.blockers])
    vat: dict[str, float] = {}
    try:
        for question in plan.questions:
            if answers.get(question.id) not in (None, ""):
                vat[question.id] = _number(question.id, answers[question.id])
    except ValueError as exc:
        return _blocked(docs, [str(exc)])
    if len(vat) < len(plan.questions):
        # Planner dry run (the runner requires every answer): leave the user tariffs as they
        # are, migrate the other files so the preview shows them.
        tariff_docs = {k: v for k, v in tariff_docs.items() if k != USER_TARIFFS}
    try:
        result = migrate_tariff_files(
            tariff_docs, vat, user_grid_areas=areas, grid_fee_area=target
        )
    except EdibertLoadError as exc:
        return _blocked(docs, [str(exc)])
    if result.blockers:
        return _blocked(docs, [migration_blocker_de(b) for b in result.blockers])
    out = {
        k: copy.deepcopy(v) for k, v in docs.items() if k != HANDOFF_USER_GRID_AREAS
    }
    for name in result.changed_files:
        out[name] = copy.deepcopy(result.docs[name])
    return StepResult(docs=out, changed_files=tuple(result.changed_files))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de=(
        "Tarifformat 1 (Tarif- und Netzentgeltdateien, Benutzer-Netzbereiche, USt-Satz, "
        "Netz-Grundgebühr in den Netzbereich)"
    ),
    files=tuple(sorted(TARIFF_TRACK_FILES)),
    detect=detect,
    apply=apply,
    questions_for=questions_for,
)
