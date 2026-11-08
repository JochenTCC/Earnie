"""Step tf1.grid_area_levies — grid loss, levies and fixed amounts into a site's ``grid_fees.json``.

A correction of data, not a format change: ``tariff_format`` stays 1 and Edibert reads both
states. ``runtime_store/bootstrap.py`` copies the catalog only when the site has none, so
without this step existing installs would keep the bare work prices and price lower than new
ones. It changes import prices, so it runs in the wizard only (``attended_only``): a recorder
snapshot keeps the prices its plan was made with.

An area counts as done once it has any of the three keys, so a later catalog correction does
not bring the step back. The values are frozen here for that reason, as of the 2026 regulations.
An area whose work price differs from the regulation may be kept by hand and may already hold
these parts, so the user decides; "Nicht ergänzen" writes ``components: []`` to record that.
User areas (``user_grid_fees.json``) are the user's own values and stay untouched.
"""
from __future__ import annotations

import copy
from typing import Any, NamedTuple

from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    ManualTodo,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "tf1.grid_area_levies"
GRID_FEES = "grid_fees.json"
LEVY_SET_ID = "AT_NE7_LEVIES_2026"
Q_PREFIX = f"{STEP_ID}.area:"
CHOICE_ADD = "Ergänzen"
CHOICE_SKIP = "Nicht ergänzen"
_DONE_KEYS = ("components", "fixed_eur_year", "levy_set")
_OLD_DESCRIPTION_START = "Netznutzungsentgelt-Arbeitspreis je Netzbereich"
_DESCRIPTION = (
    "Netzentgelte je Netzbereich (Netzebene 7): Arbeitspreis, zeitgebundene Regeln, Netzverlustentgelt, "
    "Grundpauschale und bundesweite Abgaben. Preise netto, Cent/kWh und Euro/Jahr. Modell: docs/konfiguration/preise.md."
)
_SNE_V = "SNE-V 2018 - Novelle 2026, BGBl. II Nr. 305/2025 (in Kraft ab 01.01.2026)"
_CHECKED_AT = "2026-11-07"
_FOERDERBEITRAG = "Erneuerbaren-Förderbeitragsverordnung 2026, BGBl. II Nr. 301/2025"

_LEVY_SET: dict[str, Any] = {
    "label": "Bundesweite Abgaben, Netzebene 7, 2026",
    "components": [
        {
            "id": "renewables_contribution",
            "label": "Erneuerbaren-Förderbeitrag auf den Arbeitspreis",
            "cent_kwh": {"unmetered_power": 0.583, "metered_power": 0.364},
            "source": f"{_FOERDERBEITRAG}, § 2 Abs. 2",
        },
        {
            "id": "renewables_contribution_loss",
            "label": "Erneuerbaren-Förderbeitrag auf das Netzverlustentgelt",
            "cent_kwh": 0.037,
            "source": f"{_FOERDERBEITRAG}, § 2 Abs. 3",
        },
        {
            "id": "electricity_levy",
            "label": "Elektrizitätsabgabe (Haushalt)",
            "cent_kwh": 0.1,
            "source": "Elektrizitätsabgabegesetz, geändert durch BGBl. I Nr. 95/2025",
            "note": (
                "Satz für Haushalte, befristet auf 2026. Unternehmen zahlen 0,82 Cent/kWh. "
                "Der Satz ab 2027 ist hier nicht geprüft."
            ),
        },
    ],
    "fixed_eur_year": [
        {
            "id": "renewables_contribution_flat",
            "label": "Erneuerbaren-Förderbeitrag auf die Grundpauschale",
            "eur_year": {"unmetered_power": 3.796, "metered_power": None},
            "source": f"{_FOERDERBEITRAG}, § 2 Abs. 1",
            "note": "Gemessene Leistung zahlt 5,619 Euro/kW. Das ist nicht modelliert.",
        },
        {
            "id": "renewables_flat_fee",
            "label": "Erneuerbaren-Förderpauschale",
            "eur_year": 19.02,
            "source": "Erneuerbaren-Förderpauschale-Verordnung 2025, BGBl. II Nr. 416/2024, § 1 Z 5 (2025 bis 2027)",
        },
    ],
    "source": "Verordnungen für das Kalenderjahr 2026, je Position angegeben",
}


class _Area(NamedTuple):
    letter: str  # of § 5 Abs. 1 Z 6
    unmetered: float
    metered: float
    grid_loss: float  # § 6 lit. b, cent/kWh


_AREAS: dict[str, _Area] = {
    "AT-BGLD": _Area("a", 8.46, 5.83, 0.0),
    "AT-KTN": _Area("b", 9.67, 5.47, 0.368),
    "AT-KLGF": _Area("c", 6.9, 4.36, 0.578),
    "AT-NOE": _Area("d", 8.79, 6.65, 0.384),
    "AT-OOE": _Area("e", 6.29, 4.68, 0.528),
    "AT-LINZ": _Area("f", 5.57, 3.26, 0.487),
    "AT-SBG": _Area("g", 6.59, 3.91, 0.357),
    "AT-STMK": _Area("h", 8.82, 6.78, 0.336),
    "AT-GRAZ": _Area("i", 5.17, 4.23, 0.658),
    "AT-TIROL": _Area("j", 6.81, 3.66, 0.293),
    "AT-IBK": _Area("k", 8.03, 5.72, 0.453),
    "AT-VBG": _Area("l", 4.96, 2.84, 0.393),
    "AT-WIEN": _Area("m", 6.98, 4.21, 0.7),
    "AT-KLWT": _Area("n", 17.73, 11.4, 0.401),
}


def _site_areas(docs: Docs) -> list[dict[str, Any]]:
    doc = docs.get(GRID_FEES)
    areas = doc.get("areas") if isinstance(doc, dict) else None
    return [area for area in areas or () if isinstance(area, dict)]


def _is_open(area: dict[str, Any]) -> bool:
    return str(area.get("id")) in _AREAS and not any(key in area for key in _DONE_KEYS)


def _matches_regulation(area: dict[str, Any]) -> bool:
    reference = _AREAS[str(area["id"])]
    base = area.get("base_cent_kwh")
    return isinstance(base, dict) and (
        base.get("unmetered_power") == reference.unmetered
        and base.get("metered_power") == reference.metered
    )


def detect(docs: Docs) -> bool:
    return any(_is_open(area) for area in _site_areas(docs))


def _question_id(area: dict[str, Any]) -> str:
    return f"{Q_PREFIX}{area['id']}"


def questions_for(docs: Docs) -> tuple[Question, ...]:
    questions = []
    for area in _site_areas(docs):
        if not _is_open(area) or _matches_regulation(area):
            continue
        reference = _AREAS[str(area["id"])]
        questions.append(
            Question(
                id=_question_id(area),
                step_id=STEP_ID,
                prompt_de=(
                    f"Netzbereich „{area.get('label') or area['id']}“ ({area['id']}): Der Arbeitspreis in "
                    f"`grid_fees.json` ({area.get('base_cent_kwh')}) weicht von der Verordnung ab "
                    f"(nicht gemessene Leistung {reference.unmetered}, gemessene Leistung "
                    f"{reference.metered} Cent/kWh). Earnie würde Netzverlustentgelt "
                    f"({reference.grid_loss} Cent/kWh), bundesweite Abgaben und feste Beträge "
                    "ergänzen, der Arbeitspreis bleibt. „Nicht ergänzen“ ist richtig, wenn dein "
                    "Arbeitspreis diese Bestandteile schon enthält."
                ),
                kind="choice",
                required=True,
                choices=(CHOICE_ADD, CHOICE_SKIP),
            )
        )
    return tuple(questions)


def _grid_parts(area: dict[str, Any]) -> None:
    area["components"] = [
        {"id": "grid_loss", "label": "Netzverlustentgelt", "cent_kwh": _AREAS[str(area["id"])].grid_loss}
    ]
    area["fixed_eur_year"] = [
        {
            "id": "grid_base_fee",
            "label": "Netznutzungsentgelt Grundpauschale (nicht gemessene Leistung)",
            "eur_year": {"unmetered_power": 54.0, "metered_power": None},
            "note": (
                "Gemessene Leistung zahlt stattdessen einen Leistungspreis. Das ist nicht modelliert; "
                "ein Haus mit gemessener Leistung trägt eigene Werte ein."
            ),
        }
    ]
    area["levy_set"] = LEVY_SET_ID


def _stamp_source(area: dict[str, Any]) -> None:
    letter = _AREAS[str(area["id"])].letter
    source = f"{_SNE_V}: § 5 Abs. 1 Z 6 lit. {letter} (Netzebene 7), § 6 lit. b (Netzverlustentgelt)"
    area["source"] = source
    area["check"] = {"state": "checked", "checked_at": _CHECKED_AT, "source": source}


def _blocked(docs: Docs, message: str) -> StepResult:
    return StepResult(
        docs=docs, changed_files=(), blockers=(Blocker(step_id=STEP_ID, message_de=message),)
    )


def apply(docs: Docs, answers: Answers) -> StepResult:
    out = {key: copy.deepcopy(value) for key, value in docs.items()}
    doc = out.get(GRID_FEES)
    levy_sets = doc.get("levy_sets") if isinstance(doc, dict) else None
    if isinstance(levy_sets, dict) and levy_sets.get(LEVY_SET_ID, _LEVY_SET) != _LEVY_SET:
        return _blocked(
            docs,
            f"grid_fees.json: Der Abgabensatz {LEVY_SET_ID} ist schon vorhanden und weicht ab. "
            "Bitte den Eintrag prüfen, dann erneut migrieren.",
        )
    needs_levies = False
    for area in _site_areas(out):
        if not _is_open(area):
            continue
        if _matches_regulation(area):
            _grid_parts(area)
            _stamp_source(area)
            needs_levies = True
            continue
        choice = answers.get(_question_id(area))
        if choice in (None, ""):  # planner dry run: the runner requires the answer
            continue
        if choice == CHOICE_ADD:
            _grid_parts(area)
            needs_levies = True
        elif choice == CHOICE_SKIP:
            area["components"] = []
        else:
            return _blocked(
                docs,
                f"Unbekannte Antwort '{choice}' für {_question_id(area)} "
                f"(erlaubt: {CHOICE_ADD}, {CHOICE_SKIP}).",
            )
    if needs_levies:
        doc.setdefault("levy_sets", {})[LEVY_SET_ID] = copy.deepcopy(_LEVY_SET)
        if str(doc.get("description") or "").startswith(_OLD_DESCRIPTION_START):
            doc["description"] = _DESCRIPTION
    return StepResult(docs=out, changed_files=(GRID_FEES,))


def manual_todos(before: Docs, after: Docs) -> list[ManualTodo]:
    if before.get(GRID_FEES) == after.get(GRID_FEES):
        return []
    return [
        ManualTodo(
            step_id=STEP_ID,
            text_de=(
                "Die Bezugspreise enthalten jetzt Netzverlustentgelt und bundesweite Abgaben, in "
                "Vorarlberg rund 1,3 Cent/kWh brutto mehr. Pläne, Spar-Ledger und neue Läufe im "
                "Szenario-Explorer rechnen ab sofort damit. Ältere Ergebnisse sind dadurch nicht "
                "direkt vergleichbar."
            ),
        )
    ]


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Netzbereiche: Netzverlustentgelt, bundesweite Abgaben und feste Beträge ergänzen",
    files=(GRID_FEES,),
    detect=detect,
    apply=apply,
    manual_todos=manual_todos,
    questions_for=questions_for,
    attended_only=True,
)
