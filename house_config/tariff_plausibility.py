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

    import_map = tariffs.get("import_tariffs", {})
    export_map = tariffs.get("export_tariffs", {})
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
            elif import_id not in import_map:
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
            elif export_id not in export_map:
                errors.append(
                    f"Szenario '{scenario_id}': unbekannte export_tariff_id '{export_id}'."
                )
    return errors


def scenarios_using_tariff(scenarios_path: str, direction: str, tariff_id: str) -> list[str]:
    """IDs der Szenarien, die ``tariff_id`` als Bezugs- (``import``) bzw. Einspeisetarif nutzen."""
    if direction not in ("import", "export"):
        raise ValueError(f"direction muss 'import' oder 'export' sein, nicht {direction!r}.")
    if not os.path.isfile(scenarios_path):
        return []
    scenarios = load_backtesting_scenarios_document(scenarios_path).get("scenarios") or []
    users: list[str] = []
    for index, entry in enumerate(scenarios):
        settings = entry.get("settings") if isinstance(entry, dict) else None
        if not isinstance(settings, dict):
            continue
        used = str(settings.get(f"{direction}_tariff_id", "") or "").strip()
        if direction == "export":
            used = resolve_export_tariff_id(used)
        if used == tariff_id:
            users.append(str(entry.get("id", "") or "").strip() or f"index_{index}")
    return users


def collect_tariff_plausibility_errors(
    *,
    tariffs_path: str,
    scenarios_path: str | None = None,
    schema_path: str | None = None,
    with_edibert: bool = False,
    grid_fees_path: str | None = None,
    house_profiles_path: str | None = None,
) -> list[str]:
    """Sammelt alle Plausibilitätsfehler (leer = ok).

    ``with_edibert``: zusätzlich lädt Edibert Katalog, Benutzertarife, ``grid_fees.json`` mit
    ``user_grid_fees.json``, den Netzbereich (``netznutzung``) und den Preis-Kontext jedes
    Hausprofils (dieselben Dateien, mit denen Edibert bepreist). Start-Check und
    ``scripts.validate_tariffs``.
    """
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

    if with_edibert:
        errors.extend(
            _collect_edibert_errors(
                tariffs_path=tariffs_path,
                grid_fees_path=grid_fees_path,
                house_profiles_path=house_profiles_path,
            )
        )

    if scenarios_path and os.path.isfile(scenarios_path):
        errors.extend(collect_scenario_tariff_ref_errors(scenarios_path, tariffs_path))
    return errors


def _collect_edibert_errors(
    *,
    tariffs_path: str,
    grid_fees_path: str | None,
    house_profiles_path: str | None,
) -> list[str]:
    from house_config.edibert_tariffs import collect_edibert_load_errors
    from runtime_store.persist_paths import user_grid_fees_path_for, user_tariffs_path_for

    profiles: dict = {}
    if house_profiles_path and os.path.isfile(house_profiles_path):
        from house_config.profiles_store import load_house_profiles_document

        try:
            profiles = load_house_profiles_document(house_profiles_path).get("profiles", {})
        except ValueError as exc:
            return [f"house_profiles.json: {exc}"]
    return collect_edibert_load_errors(
        tariffs_path=tariffs_path,
        user_tariffs_path=user_tariffs_path_for(tariffs_path),
        grid_fees_path=grid_fees_path,
        user_grid_fees_path=user_grid_fees_path_for(grid_fees_path) if grid_fees_path else None,
        profiles=profiles,
    )


def format_tariff_plausibility_errors(errors: list[str]) -> str:
    if not errors:
        return ""
    if len(errors) == 1:
        return errors[0]
    return "Tarif-Plausibilität:\n" + "\n".join(f"- {item}" for item in errors)
