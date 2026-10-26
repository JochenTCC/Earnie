"""Step dm5.netznutzung_split — data model 4 → 5, house-profile ``netznutzung`` split (Edibert P2).

After this step ``netznutzung`` keeps only the grid selection (``area_id``, required) and the
house-side metering facts. An own base price (``area_id: null`` + ``base_cent_kwh`` > 0) becomes
the user grid area ``user_<profile_id>``; the area is handed to ``tf1.tariff_format``, which writes
it into ``user_grid_fees.json`` through Edibert. A profile without a grid fee (no ``netznutzung``,
or ``area_id: null`` with base missing / 0) gets a required question — never a silent default
(decision 3, ``docs/dev/edibert-integration.md`` § P2). Stamps every Earnie-track file to 5.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from house_config.edibert_tariffs import flat_user_grid_area, user_grid_area_id
from runtime_store.data_model import (
    CURRENT_DATA_MODEL,
    MIGRATABLE_DATA_MODELS,
    read_data_model,
    stamp_data_model,
)
from runtime_store.migration.io_util import EARNIE_TRACK_FILES
from runtime_store.migration.types import (
    HANDOFF_USER_GRID_AREAS,
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "dm5.netznutzung_split"
Q_AREA_PREFIX = f"{STEP_ID}.area_id:"
HOUSE_FILE = "house_profiles.json"
# Fields that stay in the house profile (Edibert ``CONFIG_FIELDS``).
KEPT_FIELDS = ("area_id", "power_metering", "quarter_hour_meter", "include_status")
MOVED_FIELD = "base_cent_kwh"
# Values Earnie's loader used for a profile without ``netznutzung`` (unchanged meaning).
_DEFAULT_FACTS: dict[str, Any] = {
    "power_metering": "unmetered_power",
    "quarter_hour_meter": True,
    "include_status": ["verordnet"],
}


def question_id(profile_id: str) -> str:
    return f"{Q_AREA_PREFIX}{profile_id}"


def _iter_profiles(house: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    profiles = house.get("profiles")
    if isinstance(profiles, dict):
        for key, profile in profiles.items():
            if isinstance(profile, dict):
                yield str(profile.get("id") or key), profile
    elif isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and str(profile.get("id") or "").strip():
                yield str(profile["id"]).strip(), profile


def _area_id(netznutzung: Any) -> str | None:
    if not isinstance(netznutzung, dict):
        return None
    raw = netznutzung.get("area_id")
    return str(raw).strip() or None if raw not in (None, "") else None


def _own_base(netznutzung: Any) -> float:
    if not isinstance(netznutzung, dict) or netznutzung.get(MOVED_FIELD) is None:
        return 0.0
    return float(netznutzung[MOVED_FIELD])


def _needs_split(profile: dict[str, Any]) -> bool:
    netznutzung = profile.get("netznutzung")
    if not isinstance(netznutzung, dict):
        return True
    return _area_id(netznutzung) is None or MOVED_FIELD in netznutzung


def _needs_answer(profile: dict[str, Any]) -> bool:
    """No catalog area and no own price > 0: the user must pick (decision 3)."""
    netznutzung = profile.get("netznutzung")
    return _area_id(netznutzung) is None and _own_base(netznutzung) <= 0.0


def _area_ids(doc: Any) -> list[str]:
    areas = doc.get("areas") if isinstance(doc, dict) else None
    if not isinstance(areas, list):
        return []
    return [
        str(area["id"]) for area in areas if isinstance(area, dict) and area.get("id")
    ]


def _existing_area_ids(docs: Docs) -> list[str]:
    return _area_ids(docs.get("grid_fees.json")) + _area_ids(docs.get("user_grid_fees.json"))


def _choices(docs: Docs, profile_id: str) -> tuple[str, ...]:
    known = _existing_area_ids(docs)
    own = user_grid_area_id(profile_id)
    if own not in known:
        known.append(own)
    return tuple(known)


def _profile_label(profile_id: str, profile: dict[str, Any]) -> str:
    return str(profile.get("label") or profile_id).strip() or profile_id


def questions_for(docs: Docs) -> tuple[Question, ...]:
    house = docs.get(HOUSE_FILE)
    if not isinstance(house, dict):
        return ()
    questions: list[Question] = []
    for profile_id, profile in _iter_profiles(house):
        if not _needs_answer(profile):
            continue
        own = user_grid_area_id(profile_id)
        questions.append(
            Question(
                id=question_id(profile_id),
                step_id=STEP_ID,
                prompt_de=(
                    f"Hausprofil „{_profile_label(profile_id, profile)}“ hat keinen "
                    "Netzbereich und keinen eigenen Arbeitspreis für die Netznutzung. "
                    "Ab Datenmodell 5 ist der Netzbereich Pflicht. Netzbereich aus dem "
                    f"Katalog wählen, oder „{own}“ = eigener Netzbereich mit 0 ct/kWh "
                    "(bewusst kein Netzentgelt)."
                ),
                kind="choice",
                required=True,
                choices=_choices(docs, profile_id),
            )
        )
    return tuple(questions)


def detect(docs: Docs) -> bool:
    for name in EARNIE_TRACK_FILES:
        if read_data_model(docs.get(name)) in MIGRATABLE_DATA_MODELS:
            return True
    house = docs.get(HOUSE_FILE)
    if not isinstance(house, dict):
        return False
    return any(_needs_split(profile) for _pid, profile in _iter_profiles(house))


def _kept_facts(netznutzung: Any) -> dict[str, Any]:
    source = netznutzung if isinstance(netznutzung, dict) else {}
    out = {key: copy.deepcopy(source[key]) for key in KEPT_FIELDS[1:] if key in source}
    for key, value in _DEFAULT_FACTS.items():
        out.setdefault(key, copy.deepcopy(value))
    extra = sorted(set(source) - set(KEPT_FIELDS) - {MOVED_FIELD})
    for key in extra:  # unknown keys stay; the loader rejects them loudly
        out[key] = copy.deepcopy(source[key])
    return out


def _split_profile(
    profile_id: str,
    profile: dict[str, Any],
    answers: Answers,
    docs: Docs,
) -> tuple[dict[str, Any] | None, Blocker | None]:
    """Rewrite ``profile['netznutzung']`` in place; returns a user area to create, or a blocker."""
    netznutzung = profile.get("netznutzung")
    area_id = _area_id(netznutzung)
    facts = _kept_facts(netznutzung)
    own_area: dict[str, Any] | None = None
    if area_id is None:
        base = _own_base(netznutzung)
        own = user_grid_area_id(profile_id)
        label = f"Eigener Arbeitspreis – {_profile_label(profile_id, profile)}"
        land = str(profile.get("land") or "").strip().upper() or None
        if base > 0.0:
            area_id = own
            own_area = flat_user_grid_area(own, base, label=label, land=land)
        else:
            answer = answers.get(question_id(profile_id))
            if answer in (None, ""):
                return None, None  # planner dry run; the runner requires the answer
            answer = str(answer).strip()
            choices = _choices(docs, profile_id)
            if answer not in choices:
                return None, Blocker(
                    step_id=STEP_ID,
                    message_de=(
                        f"Unbekannte Antwort '{answer}' für {question_id(profile_id)} "
                        f"(erlaubt: {', '.join(choices)})."
                    ),
                )
            area_id = answer
            if answer == own and own not in _existing_area_ids(docs):
                own_area = flat_user_grid_area(own, 0.0, label=label, land=land)
    profile["netznutzung"] = {"area_id": area_id, **facts}
    return own_area, None


def apply(docs: Docs, answers: Answers) -> StepResult:
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    changed: list[str] = []
    house = out.get(HOUSE_FILE)
    new_areas: list[dict[str, Any]] = []
    if isinstance(house, dict):
        for profile_id, profile in _iter_profiles(house):
            if not _needs_split(profile):
                continue
            if _needs_answer(profile) and answers.get(question_id(profile_id)) in (None, ""):
                continue  # planner dry run: leave this profile as it is
            area, blocker = _split_profile(profile_id, profile, answers, docs)
            if blocker is not None:
                return StepResult(docs=docs, changed_files=(), blockers=(blocker,))
            if area is not None:
                new_areas.append(area)
    for name in sorted(EARNIE_TRACK_FILES):
        doc = out.get(name)
        if not isinstance(doc, dict):
            continue
        before = docs.get(name)
        if read_data_model(doc) != CURRENT_DATA_MODEL:
            stamp_data_model(doc)
        if doc != before:
            changed.append(name)
    if new_areas:
        handed = out.get(HANDOFF_USER_GRID_AREAS, {"areas": []})
        out[HANDOFF_USER_GRID_AREAS] = {"areas": [*handed.get("areas", []), *new_areas]}
    return StepResult(docs=out, changed_files=tuple(changed))


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 4 → 5: Netznutzung aufteilen (eigener Arbeitspreis → Benutzer-Netzbereich)",
    files=(
        "config.json",
        "backtesting_scenarios.json",
        "components.json",
        "deviation_rules.json",
        "house_profiles.json",
    ),
    detect=detect,
    apply=apply,
    questions_for=questions_for,
)
