"""Edibert library access (epic Edibert, P1: load and check; P2: user grid areas, migration;
P3a: slot prices for the parity harness and ``EARNIE_PRICING_ENGINE=edibert``).

The only module that calls ``edibert.api``. Earnie still prices with its own engine
(``data/tariff_pricing.py``, ``data/grid_fees.py``) until Edibert P3b; here the tariff
files, the grid-fee files and the pricing context of each house profile are loaded
through Edibert so format problems surface now. Every ``EdibertError`` becomes an
:class:`EdibertLoadError` with a German message; nothing is skipped silently.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import holidays as holidays_lib  # Edibert dependency; same calendar Edibert uses
from edibert import api

from house_config.geo_timezone import timezone_for_land

AT_STATES = {
    "1": "Burgenland",
    "2": "Kärnten",
    "3": "Niederösterreich",
    "4": "Oberösterreich",
    "5": "Salzburg",
    "6": "Steiermark",
    "7": "Tirol",
    "8": "Vorarlberg",
    "9": "Wien",
}

_MESSAGES_DE: dict[str, str] = {
    "TARIFF_UNKNOWN_FIELD": "unbekanntes Feld '{field}'",
    "RULE_UNKNOWN_FIELD": "Regel '{rule_id}': unbekanntes Feld '{field}'",
    "FIELD_MISSING": "Pflichtfeld '{field}' fehlt",
    "VALUE_INVALID": "ungültiger Wert {value!r} für '{field}'",
    "UNSUPPORTED_FEATURE": "Tarif '{tariff_id}': '{feature}' wird nicht unterstützt",
    "RULE_VALUE_MISSING": "Regel '{rule_id}': Wert fehlt",
    "GRID_AREA_UNKNOWN": "unbekannter Netzbereich '{area_id}'",
    "FILE_INVALID": "Datei nicht lesbar: {path}",
    "ID_COLLISION": "Tarif-ID '{tariff_id}' ist doppelt (Katalog und Benutzertarife?)",
    "ID_PREFIX_MISSING": "Benutzertarif '{tariff_id}' muss mit 'user_' beginnen",
    "ID_PREFIX_RESERVED": "Katalogtarif '{tariff_id}' darf nicht mit 'user_' beginnen",
    "HOLIDAY_REGION_MISSING": "Region (Bundesland/Kanton) fehlt",
    "HOLIDAY_REGION_UNKNOWN": "unbekannte Region '{region}' für Land {land}",
    "VAT_PERCENT_MISSING": "Tarif '{tariff_id}': USt-Satz (vat_percent) fehlt",
    "GRID_ID_COLLISION": "Netzbereich-ID '{grid_id}' ist doppelt (Katalog und Benutzer-Netzbereiche?)",
    "GRID_ID_PREFIX_MISSING": "Benutzer-Netzbereich '{grid_id}' muss mit 'user_' beginnen",
    "GRID_ID_PREFIX_RESERVED": "Katalog-Netzbereich '{grid_id}' darf nicht mit 'user_' beginnen",
    "FORMAT_MISSING": (
        "tariff_format fehlt — Konfiguration zuerst migrieren (Streamlit-Seite "
        "„Konfigurations-Migration“ oder python -m scripts.migrate_config)"
    ),
    "FORMAT_UNSUPPORTED": "tariff_format={value!r} wird nicht unterstützt (unterstützt: {supported})",
    "MIGRATION_ANSWER_MISSING": "Migrationsfrage '{question_id}' ist nicht beantwortet",
    "PRICE_MISSING": "Tarif '{tariff_id}': kein Preis für Slot {slot}",
    "MARKET_PRICE_REQUIRED": "Tarif '{tariff_id}': Börsenpreis für Slot {slot} erforderlich",
}


class EdibertLoadError(ValueError):
    """A coded Edibert error with a German message (``code``/``params`` kept for tests and logs)."""

    def __init__(self, source: str, exc: api.EdibertError) -> None:
        self.code = str(exc.code)
        self.params: dict[str, Any] = dict(exc.params)
        template = _MESSAGES_DE.get(self.code)
        try:
            detail = template.format(**self.params) if template else str(exc)
        except (KeyError, IndexError):
            detail = str(exc)
        super().__init__(f"{source}: {detail} (Edibert {self.code}).")


def load_tariff_set(tariffs_path: str, user_path: str | None = None) -> api.TariffSet:
    """Catalog and optional user file as one Edibert set (missing user file = no user tariffs)."""
    source = "tariffs.json" if user_path is None else "tariffs.json / user_tariffs.json"
    try:
        return api.load_tariffs(
            Path(tariffs_path), Path(user_path) if user_path else None
        )
    except api.EdibertError as exc:
        raise EdibertLoadError(source, exc) from exc


def load_user_tariff_set(user_path: str) -> api.TariffSet:
    """Only the user file, strictly checked by Edibert (prefix, unknown fields, duplicates)."""
    try:
        return api.load_tariffs(None, Path(user_path))
    except api.EdibertError as exc:
        raise EdibertLoadError(f"user_tariffs.json ({user_path})", exc) from exc


def load_grid_fees(grid_fees_path: str, user_path: str | None = None) -> api.GridFeeCatalog:
    """Catalog and optional user grid areas as one view (missing user file = no user areas)."""
    source = "grid_fees.json" if user_path is None else "grid_fees.json / user_grid_fees.json"
    try:
        return api.load_grid_fees(Path(grid_fees_path), Path(user_path) if user_path else None)
    except api.EdibertError as exc:
        raise EdibertLoadError(f"{source} ({grid_fees_path})", exc) from exc


def flat_user_grid_area(
    area_id: str, base_cent_kwh: float, *, label: str, land: str | None
) -> dict:
    """One own work price for both metering types, no rules (Edibert shape)."""
    return api.flat_user_grid_area(area_id, float(base_cent_kwh), label=label, land=land or None)


def save_user_grid_area(user_path: str, area: dict) -> None:
    """Add or replace one area in ``user_grid_fees.json``; the file stays unchanged on error."""
    try:
        api.save_user_grid_area(Path(user_path), area)
    except api.EdibertError as exc:
        raise EdibertLoadError(f"user_grid_fees.json ({user_path})", exc) from exc


def user_grid_area_id(profile_id: str) -> str:
    """ID of the own grid area of one house profile (*Eigener Arbeitspreis*)."""
    return f"{api.USER_PREFIX}{profile_id}"


# --- Tariff-track migration (Edibert P2, wrapped by tf1.tariff_format) -------------

EDIBERT_TARIFF_FORMAT = api.TARIFF_FORMAT
EDIBERT_TARIFF_TRACK_FILES = tuple(api.TARIFF_TRACK_FILES)
STANDARD_VAT_PERCENT = dict(api.STANDARD_VAT_PERCENT)


def plan_tariff_migration(
    docs: dict[str, dict], *, user_grid_areas: tuple[dict, ...] = ()
) -> api.MigrationPlan:
    """Pure: what Edibert's migration would change, its questions and blockers."""
    return api.plan_migration(docs, user_grid_areas=user_grid_areas)


def migrate_tariff_files(
    docs: dict[str, dict],
    answers: dict[str, Any],
    *,
    user_grid_areas: tuple[dict, ...] = (),
) -> api.MigrationResult:
    """Pure: tariff-track files brought to the current ``tariff_format``."""
    try:
        return api.migrate(docs, answers, user_grid_areas=user_grid_areas)
    except api.EdibertError as exc:
        raise EdibertLoadError("Tarif-Migration", exc) from exc


def migration_blocker_de(blocker: api.MigrationBlocker) -> str:
    """German text of one Edibert migration blocker (file + coded message)."""
    code = str(blocker.code)
    template = _MESSAGES_DE.get(code)
    try:
        detail = template.format(**dict(blocker.params)) if template else blocker.message
    except (KeyError, IndexError):
        detail = blocker.message
    source = blocker.file or "Tarifdateien"
    return f"{source}: {detail} (Edibert {code})."


def profile_timezone(profile: dict) -> str:
    """Same rule as the scenario resolution: explicit ``timezone_name``, else by country."""
    explicit = str(profile.get("timezone_name", "") or "").strip()
    return explicit or timezone_for_land(profile.get("land", "AT"))


def pricing_context_for_profile(profile_id: str, profile: dict) -> api.PricingContext:
    """Edibert pricing context of one house profile; an unknown region is an error."""
    region = str(profile.get("region", "") or "").strip() or None
    land = str(profile.get("land", "") or "").strip() or None
    try:
        return api.pricing_context(profile_timezone(profile), land, region)
    except api.EdibertError as exc:
        raise EdibertLoadError(f"Hausprofil '{profile_id}'", exc) from exc


def holiday_regions(land: str) -> list[str]:
    """Region codes (Bundesland/Kanton) of the holiday calendar for ``land``."""
    try:
        return sorted(holidays_lib.country_holidays(land).subdivisions)
    except NotImplementedError:
        return []


def region_label(land: str, code: str) -> str:
    if not code:
        return "– keine –"
    if land == "AT" and code in AT_STATES:
        return f"{code} – {AT_STATES[code]}"
    return code


def collect_edibert_load_errors(
    *,
    tariffs_path: str,
    user_tariffs_path: str | None = None,
    grid_fees_path: str | None = None,
    user_grid_fees_path: str | None = None,
    profiles: dict[str, dict] | None = None,
) -> list[str]:
    """All files and profile contexts through Edibert; one German message per problem."""
    errors: list[str] = []
    user = user_tariffs_path if user_tariffs_path and os.path.isfile(user_tariffs_path) else None
    try:
        load_tariff_set(tariffs_path, user)
    except EdibertLoadError as exc:
        errors.append(str(exc))
    grid_catalog: api.GridFeeCatalog | None = None
    if grid_fees_path and os.path.isfile(grid_fees_path):
        user_grid = (
            user_grid_fees_path
            if user_grid_fees_path and os.path.isfile(user_grid_fees_path)
            else None
        )
        try:
            grid_catalog = load_grid_fees(grid_fees_path, user_grid)
        except EdibertLoadError as exc:
            errors.append(str(exc))
    for profile_id, profile in (profiles or {}).items():
        if not isinstance(profile, dict):
            continue
        try:
            pricing_context_for_profile(str(profile_id), profile)
        except EdibertLoadError as exc:
            errors.append(str(exc))
        if grid_catalog is not None:
            try:
                profile_grid_fee(str(profile_id), profile, grid_catalog)
            except EdibertLoadError as exc:
                errors.append(str(exc))
    return errors


def profile_grid_fee(profile_id: str, profile: dict, catalog: api.GridFeeCatalog) -> api.GridFee:
    """``netznutzung`` of one house profile resolved against catalog plus user areas."""
    try:
        config = api.parse_grid_fee_config(profile.get("netznutzung"))
        return api.resolve_grid_fee(config, catalog)
    except api.EdibertError as exc:
        raise EdibertLoadError(f"Hausprofil '{profile_id}' (netznutzung)", exc) from exc


# --- Slot prices (Edibert P3a) --------------------------------------------------------

IMPORT = api.IMPORT
EXPORT = api.EXPORT
PricePoint = api.PricePoint
PriceResult = api.PriceResult


def _mtime_ns(path: str | None) -> int | None:
    if not path or not os.path.isfile(path):
        return None
    return os.stat(path).st_mtime_ns


@lru_cache(maxsize=8)
def _tariff_set_cached(
    tariffs_path: str, user_path: str, _mtime: int | None, _user_mtime: int | None
) -> api.TariffSet:
    return load_tariff_set(tariffs_path, user_path if _user_mtime is not None else None)


@lru_cache(maxsize=8)
def _grid_fees_cached(
    grid_fees_path: str, user_path: str, _mtime: int | None, _user_mtime: int | None
) -> api.GridFeeCatalog:
    return load_grid_fees(grid_fees_path, user_path if _user_mtime is not None else None)


def cached_tariff_set(tariffs_path: str) -> api.TariffSet:
    """Catalog plus ``user_tariffs.json`` next to it; reloaded when either file changes."""
    from runtime_store.persist_paths import user_tariffs_path_for

    user_path = user_tariffs_path_for(tariffs_path)
    return _tariff_set_cached(
        tariffs_path, user_path, _mtime_ns(tariffs_path), _mtime_ns(user_path)
    )


def cached_grid_fees(grid_fees_path: str) -> api.GridFeeCatalog:
    """Grid catalog plus ``user_grid_fees.json`` next to it; reloaded when either file changes."""
    from runtime_store.persist_paths import user_grid_fees_path_for

    user_path = user_grid_fees_path_for(grid_fees_path)
    return _grid_fees_cached(
        grid_fees_path, user_path, _mtime_ns(grid_fees_path), _mtime_ns(user_path)
    )


USER_FIXED_ID = "__user_fixed__"


def synthetic_fixed_tariff(
    direction: str, cent: float, *, vat_percent: float, land: str | None
) -> api.Tariff:
    """*Eigener Festpreis* (scenario shortcut, no tariff file) as an Edibert tariff.

    Gross price as entered; import carries the land's VAT rate (VAT on the net grid fee),
    export ``vat_percent`` 0 — the same values Earnie's own synthetic specs use.
    """
    raw: dict[str, Any] = {
        "id": USER_FIXED_ID,
        "label": "Eigener Festpreis",
        "supplier_id": "user",
        "prices_include_vat": True,
        "vat_percent": float(vat_percent),
    }
    if land:
        raw["land"] = land
    if direction == IMPORT:
        raw.update(type="fixed_cent", fix_cent_kwh=float(cent))
    else:
        raw.update(type="fixed", k_push_cent=float(cent))
    try:
        return api.parse_tariff(raw, direction)
    except api.EdibertError as exc:
        raise EdibertLoadError("Eigener Festpreis", exc) from exc


def tariff_by_id(tariff_set: api.TariffSet, direction: str, tariff_id: str) -> api.Tariff:
    """One tariff of the set; an unknown ID is an error."""
    try:
        return tariff_set.get(direction, tariff_id)
    except api.EdibertError as exc:
        raise EdibertLoadError(f"Tarif '{tariff_id}' ({direction})", exc) from exc


def price_series(
    tariff: api.Tariff,
    ctx: api.PricingContext,
    start: datetime,
    end: datetime,
    *,
    market: Mapping[datetime, float] | None,
    grid_fee: api.GridFee | None,
) -> api.PriceSeries:
    """15-min prices for ``[start, end)``; a missing market or month price is an error."""
    try:
        return api.tariff_price_series(
            tariff, ctx, start, end, resolution_min=15, market=market, grid_fee=grid_fee
        )
    except api.EdibertError as exc:
        raise EdibertLoadError(f"Preisreihe Tarif '{tariff.id}'", exc) from exc


def evaluate_slot(
    tariff: api.Tariff,
    slot: datetime,
    ctx: api.PricingContext,
    *,
    epex_cent: float | None,
    grid_fee: api.GridFee | None,
) -> api.PriceResult:
    """One slot with the intermediate steps (no hourly averaging; used for diff reports)."""
    try:
        return api.evaluate(tariff, slot, ctx, epex_cent, grid_fee)
    except api.EdibertError as exc:
        raise EdibertLoadError(f"Preis Tarif '{tariff.id}'", exc) from exc


def warning_text(warning: api.EdibertWarning) -> str:
    """Code plus params of one Edibert warning, for logs and reports."""
    params = ", ".join(f"{key}={value}" for key, value in sorted(dict(warning.params).items()))
    return f"{warning.code}({params})" if params else str(warning.code)
