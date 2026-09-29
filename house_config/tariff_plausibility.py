"""Tarifkatalog-Plausibilität für Laufzeit und Deploy-Gate."""
from __future__ import annotations

import json
import os

import jsonschema

from house_config.tariffs_store import (
    USER_EXPORT_CENT_KEY,
    USER_IMPORT_CENT_KEY,
    is_user_fixed_tariff_id,
    load_tariffs_document,
    resolve_export_tariff_id,
)
from settings.scenarios import load_backtesting_scenarios_document


def _user_fixed_cent_error(
    *,
    scenario_id: str,
    side: str,
    settings: dict,
) -> str | None:
    """Return error text when user-fixed tariff lacks a valid cent value."""
    if side == "import":
        key = USER_IMPORT_CENT_KEY
        label = "import_tariff_id"
        require_positive = True
    else:
        key = USER_EXPORT_CENT_KEY
        label = "export_tariff_id"
        require_positive = False
    if key not in settings or settings[key] is None:
        return (
            f"Szenario '{scenario_id}': {label} '__user_fixed__' erfordert {key}."
        )
    try:
        value = float(settings[key])
    except (TypeError, ValueError):
        return (
            f"Szenario '{scenario_id}': {key} muss eine Zahl sein."
        )
    if require_positive and value <= 0.0:
        return f"Szenario '{scenario_id}': {key} muss > 0 sein."
    if not require_positive and value < 0.0:
        return f"Szenario '{scenario_id}': {key} muss >= 0 sein."
    return None


def _read_json_object(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise ValueError(f"{path!r} muss ein JSON-Objekt sein.")
    return doc


def validate_tariffs_document(path: str) -> None:
    """Normalisiert tariffs.json; wirft ValueError bei ungültigem Inhalt."""
    load_tariffs_document(path)


def validate_tariffs_against_schema(
    tariffs_path: str,
    schema_path: str,
) -> None:
    """JSON-Schema-Prüfung; wirft ValueError bei Verletzung."""
    if not os.path.isfile(schema_path):
        raise ValueError(f"Tarif-Schema nicht gefunden: {schema_path!r}.")
    doc = _read_json_object(tariffs_path)
    schema = _read_json_object(schema_path)
    try:
        jsonschema.validate(instance=doc, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"tariffs.json entspricht nicht dem Schema ({tariffs_path}): {exc.message}"
        ) from exc


def collect_scenario_tariff_ref_errors(
    scenarios_path: str,
    tariffs_path: str,
) -> list[str]:
    """Prüft import/export_tariff_id aller Szenarien gegen den Katalog."""
    doc = load_backtesting_scenarios_document(scenarios_path)
    scenarios = doc.get("scenarios")
    if scenarios is None:
        return []
    if not isinstance(scenarios, list):
        return [f"'{scenarios_path}': 'scenarios' muss ein Array sein."]

    try:
        tariffs = load_tariffs_document(tariffs_path)
    except ValueError as exc:
        return [str(exc)]

    import_ids = set(tariffs.get("import_tariffs", {}))
    export_ids = set(tariffs.get("export_tariffs", {}))
    errors: list[str] = []

    for index, entry in enumerate(scenarios):
        if not isinstance(entry, dict):
            continue
        scenario_id = str(entry.get("id", "") or "").strip() or f"index_{index}"
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            continue
        import_id = str(settings.get("import_tariff_id", "") or "").strip()
        export_id = resolve_export_tariff_id(
            str(settings.get("export_tariff_id", "") or "").strip()
        )
        if import_id:
            if is_user_fixed_tariff_id(import_id):
                err = _user_fixed_cent_error(
                    scenario_id=scenario_id, side="import", settings=settings
                )
                if err:
                    errors.append(err)
            elif import_id not in import_ids:
                errors.append(
                    f"Szenario '{scenario_id}': unbekannte import_tariff_id '{import_id}'."
                )
        if export_id:
            if is_user_fixed_tariff_id(export_id):
                err = _user_fixed_cent_error(
                    scenario_id=scenario_id, side="export", settings=settings
                )
                if err:
                    errors.append(err)
            elif export_id not in export_ids:
                errors.append(
                    f"Szenario '{scenario_id}': unbekannte export_tariff_id '{export_id}'."
                )
    return errors


def collect_tariff_plausibility_errors(
    *,
    tariffs_path: str,
    scenarios_path: str | None = None,
    schema_path: str | None = None,
) -> list[str]:
    """Sammelt alle Plausibilitätsfehler (leer = ok)."""
    errors: list[str] = []
    if not os.path.isfile(tariffs_path):
        return [f"tariffs.json nicht gefunden: {tariffs_path!r}."]

    try:
        validate_tariffs_document(tariffs_path)
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    if schema_path:
        try:
            validate_tariffs_against_schema(tariffs_path, schema_path)
        except ValueError as exc:
            errors.append(str(exc))

    if scenarios_path and os.path.isfile(scenarios_path):
        errors.extend(collect_scenario_tariff_ref_errors(scenarios_path, tariffs_path))
    return errors


def format_tariff_plausibility_errors(errors: list[str]) -> str:
    if not errors:
        return ""
    if len(errors) == 1:
        return errors[0]
    return "Tarif-Plausibilität:\n" + "\n".join(f"- {item}" for item in errors)
