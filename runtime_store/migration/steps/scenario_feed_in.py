"""Step dm5.scenario_feed_in — flat feed-in settings → tariffs (Edibert P3b, decision D2).

Before Edibert P3b a scenario could price feed-in without an export tariff (``k_push_cent`` with
``feed_in_mode`` ``fixed`` / ``dynamic_epex``, optionally ``monthly_fixed_feed_in_rates``) and
import without an import tariff (the live scenario's tariff was used). Since P3b only tariffs
price slots, so these keys are rejected on load. This step removes them:

* scenario with an export tariff already: the flat keys had no effect (the tariff overwrote
  them) and are dropped without a question;
* otherwise a required question per scenario for the export tariff — *Eigener Festpreis*
  (``__user_fixed__``, cent value = the scenario's ``k_push_cent``) or a catalog / user tariff;
* a scenario without import tariff gets a required question as well (suggestion: the live
  scenario's import tariff, which priced it so far). Never a silent default.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from runtime_store.migration.types import (
    Answers,
    Blocker,
    Docs,
    MigrationStep,
    Question,
    StepResult,
)

STEP_ID = "dm5.scenario_feed_in"
SCENARIOS_FILE = "backtesting_scenarios.json"
LEGACY_KEYS = ("k_push_cent", "feed_in_mode", "monthly_fixed_feed_in_rates")
USER_FIXED = "__user_fixed__"
USER_EXPORT_CENT_KEY = "user_export_cent_kwh"
Q_EXPORT_PREFIX = f"{STEP_ID}.export_tariff_id:"
Q_IMPORT_PREFIX = f"{STEP_ID}.import_tariff_id:"


def export_question_id(scenario_id: str) -> str:
    return f"{Q_EXPORT_PREFIX}{scenario_id}"


def import_question_id(scenario_id: str) -> str:
    return f"{Q_IMPORT_PREFIX}{scenario_id}"


def _iter_scenarios(doc: Any) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    scenarios = doc.get("scenarios") if isinstance(doc, dict) else None
    for entry in scenarios if isinstance(scenarios, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("settings"), dict):
            continue
        scenario_id = str(entry.get("id") or "").strip()
        if scenario_id:
            yield scenario_id, entry, entry["settings"]


def _has_legacy_keys(settings: dict[str, Any]) -> bool:
    return any(key in settings for key in LEGACY_KEYS)


def _tariff_id(settings: dict[str, Any], key: str) -> str | None:
    return str(settings.get(key) or "").strip() or None


def _tariff_ids(docs: Docs, section: str) -> list[str]:
    ids: list[str] = []
    for name in ("tariffs.json", "user_tariffs.json"):
        items = (docs.get(name) or {}).get(section)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("id") and str(item["id"]) not in ids:
                ids.append(str(item["id"]))
    return ids


def _live_import_id(docs: Docs) -> str | None:
    live_id = str((docs.get("config.json") or {}).get("live_scenario_id") or "live").strip()
    for scenario_id, _entry, settings in _iter_scenarios(docs.get(SCENARIOS_FILE)):
        if scenario_id == live_id:
            return _tariff_id(settings, "import_tariff_id")
    return None


def _label(scenario_id: str, entry: dict[str, Any]) -> str:
    return str(entry.get("label") or scenario_id).strip() or scenario_id


def questions_for(docs: Docs) -> tuple[Question, ...]:
    questions: list[Question] = []
    export_choices = (USER_FIXED, *_tariff_ids(docs, "export_tariffs"))
    import_choices = tuple(_tariff_ids(docs, "import_tariffs"))
    live_import = _live_import_id(docs)
    for scenario_id, entry, settings in _iter_scenarios(docs.get(SCENARIOS_FILE)):
        if not _has_legacy_keys(settings):
            continue
        label = _label(scenario_id, entry)
        if _tariff_id(settings, "export_tariff_id") is None:
            mode = str(settings.get("feed_in_mode") or "fixed").strip().lower()
            fixed = mode == "fixed" and "monthly_fixed_feed_in_rates" not in settings
            cent = settings.get("k_push_cent")
            questions.append(
                Question(
                    id=export_question_id(scenario_id),
                    step_id=STEP_ID,
                    prompt_de=(
                        f"Szenario „{label}“ legt die Einspeisevergütung ohne Einspeisetarif "
                        f"fest (feed_in_mode={mode}, k_push_cent={cent}). Seit der "
                        "Edibert-Umstellung bepreist nur noch ein Einspeisetarif. "
                        f"„{USER_FIXED}“ = Eigener Festpreis mit {cent} ct/kWh, oder einen "
                        "Tarif aus dem Katalog wählen."
                    ),
                    kind="choice",
                    required=True,
                    choices=export_choices,
                    default=USER_FIXED if fixed and cent is not None else None,
                )
            )
        if _tariff_id(settings, "import_tariff_id") is None:
            questions.append(
                Question(
                    id=import_question_id(scenario_id),
                    step_id=STEP_ID,
                    prompt_de=(
                        f"Szenario „{label}“ hat keinen Bezugstarif; bisher galt der Tarif "
                        "des Live-Szenarios. Bezugstarif wählen."
                    ),
                    kind="choice",
                    required=True,
                    choices=import_choices,
                    default=live_import if live_import in import_choices else None,
                )
            )
    return tuple(questions)


def detect(docs: Docs) -> bool:
    return any(
        _has_legacy_keys(settings)
        for _sid, _entry, settings in _iter_scenarios(docs.get(SCENARIOS_FILE))
    )


def _answer(answers: Answers, question_id: str, choices: tuple[str, ...]) -> tuple[str | None, Blocker | None]:
    raw = answers.get(question_id)
    if raw in (None, ""):
        return None, None
    value = str(raw).strip()
    if value not in choices:
        return None, Blocker(
            step_id=STEP_ID,
            message_de=(
                f"Unbekannte Antwort '{value}' für {question_id} "
                f"(erlaubt: {', '.join(choices)})."
            ),
        )
    return value, None


def _migrate_settings(
    scenario_id: str, settings: dict[str, Any], answers: Answers, docs: Docs
) -> tuple[bool, Blocker | None]:
    """Rewrite ``settings`` in place; ``False`` = an answer is missing (planner dry run)."""
    export_choices = (USER_FIXED, *_tariff_ids(docs, "export_tariffs"))
    import_choices = tuple(_tariff_ids(docs, "import_tariffs"))
    new: dict[str, Any] = {}
    if _tariff_id(settings, "export_tariff_id") is None:
        export_id, blocker = _answer(answers, export_question_id(scenario_id), export_choices)
        if blocker is not None or export_id is None:
            return False, blocker
        new["export_tariff_id"] = export_id
        if export_id == USER_FIXED:
            if settings.get("k_push_cent") is None:
                return False, Blocker(
                    step_id=STEP_ID,
                    message_de=(
                        f"Szenario '{scenario_id}': Eigener Festpreis braucht k_push_cent "
                        "als Cent-Wert — bitte einen Einspeisetarif aus dem Katalog wählen."
                    ),
                )
            new[USER_EXPORT_CENT_KEY] = float(settings["k_push_cent"])
    if _tariff_id(settings, "import_tariff_id") is None:
        import_id, blocker = _answer(answers, import_question_id(scenario_id), import_choices)
        if blocker is not None or import_id is None:
            return False, blocker
        new["import_tariff_id"] = import_id
    for key in LEGACY_KEYS:
        settings.pop(key, None)
    settings.update(new)
    return True, None


def apply(docs: Docs, answers: Answers) -> StepResult:
    out = {k: copy.deepcopy(v) for k, v in docs.items()}
    doc = out.get(SCENARIOS_FILE)
    for scenario_id, _entry, settings in _iter_scenarios(doc):
        if not _has_legacy_keys(settings):
            continue
        _done, blocker = _migrate_settings(scenario_id, settings, answers, docs)
        if blocker is not None:
            return StepResult(docs=docs, changed_files=(), blockers=(blocker,))
    changed = (SCENARIOS_FILE,) if doc != docs.get(SCENARIOS_FILE) else ()
    return StepResult(docs=out, changed_files=changed)


STEP = MigrationStep(
    id=STEP_ID,
    data_model=5,
    title_de="Datenmodell 5: Einspeise-Einstellungen ohne Tarif → Einspeise-/Bezugstarif (Edibert)",
    files=(SCENARIOS_FILE,),
    detect=detect,
    apply=apply,
    questions_for=questions_for,
)
