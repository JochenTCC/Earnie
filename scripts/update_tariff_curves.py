#!/usr/bin/env python3
"""CLI: Monatliche Referenzkurven im Tarifkatalog nachziehen (Katalog-Wartung).

Trägt neue OeMAG-Marktpreise / E-Control-Referenzmarktwerte PV in die Shared-Kurven
ein und rechnet alle Tarife mit ``monthly_seed`` für die betroffenen Monate nach.

Beispiele::

    python -m scripts.update_tariff_curves --oemag 2026-07=6.146 --refmarkt 2026-07=4.21
    python -m scripts.update_tariff_curves --set export:monthly_sunny_web_recherche:2026-09=5.9
    python -m scripts.update_tariff_curves --check        # Drift Katalog ↔ Seeds, schreibt nichts
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates
from data.monthly_float_rates import (
    SEED_CURVE_KEYS,
    SEED_CURVE_OEMAG,
    SEED_CURVE_REFMARKT_PV,
    build_seeded_monthly_rates,
    monthly_seed_curve,
)

DEFAULT_CATALOG = ROOT / "share" / "config" / "tariffs.json"
_TARIFF_LISTS = {"import": "import_tariffs", "export": "export_tariffs"}
# Abweichungen unterhalb dieser Schwelle gelten als Rundungsrauschen.
_EPS = 5e-5

YearMonth = tuple[int, int]


@dataclass
class UpdateReport:
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = list(self.changes) or ["Keine Änderungen."]
        lines.extend(f"WARNUNG: {w}" for w in self.warnings)
        return "\n".join(lines)


def parse_year_month(text: str) -> YearMonth:
    try:
        year_s, month_s = text.strip().split("-")
        year, month = int(year_s), int(month_s)
    except ValueError as exc:
        raise ValueError(f"Monat muss JJJJ-MM sein, nicht {text!r}.") from exc
    if not 1 <= month <= 12:
        raise ValueError(f"Monat muss 1–12 sein: {text!r}.")
    return year, month


def parse_month_value(text: str) -> tuple[YearMonth, float]:
    """``2026-07=6.146`` → ((2026, 7), 6.146)."""
    if "=" not in text:
        raise ValueError(f"Erwartet JJJJ-MM=CENT, nicht {text!r}.")
    ym_s, cent_s = text.split("=", 1)
    cent = float(cent_s.replace(",", "."))
    if cent <= 0.0:
        raise ValueError(f"Cent/kWh muss > 0 sein: {text!r}.")
    return parse_year_month(ym_s), cent


def parse_tariff_value(text: str) -> tuple[str, str, YearMonth, float]:
    """``export:tariff_id:2026-07=5.9`` → (side, id, (2026, 7), 5.9)."""
    try:
        side, tariff_id, rest = text.split(":", 2)
    except ValueError as exc:
        raise ValueError(f"Erwartet SEITE:TARIF_ID:JJJJ-MM=CENT, nicht {text!r}.") from exc
    side = side.strip().lower()
    if side not in _TARIFF_LISTS:
        raise ValueError(f"Seite muss import oder export sein, nicht {side!r}.")
    ym, cent = parse_month_value(rest)
    return side, tariff_id.strip(), ym, cent


def _rows_by_month(rows: list) -> dict[YearMonth, float]:
    return {
        (int(r["year"]), int(r["month"])): float(r["tariff_cent_kwh"]) for r in rows
    }


def _write_rows(target: dict, key: str, by_month: dict[YearMonth, float]) -> None:
    rows = [
        {"year": y, "month": m, "tariff_cent_kwh": cent}
        for (y, m), cent in sorted(by_month.items())
    ]
    validate_fixed_monthly_feed_in_rates(rows)
    target[key] = rows


def _fmt(cent: float | None) -> str:
    return "—" if cent is None else f"{cent:g}"


def _iter_tariffs(doc: dict):
    for side, list_key in _TARIFF_LISTS.items():
        for tariff in doc.get(list_key, []):
            yield side, tariff


def _find_tariff(doc: dict, side: str, tariff_id: str) -> dict:
    for tariff in doc.get(_TARIFF_LISTS[side], []):
        if tariff.get("id") == tariff_id:
            return tariff
    raise ValueError(f"Unbekannter {side}-Tarif '{tariff_id}'.")


def _upsert_curve(
    doc: dict,
    curve: str,
    values: dict[YearMonth, float],
    report: UpdateReport,
) -> set[YearMonth]:
    key = SEED_CURVE_KEYS[curve]
    by_month = _rows_by_month(doc.get(key, []))
    touched: set[YearMonth] = set()
    for ym, cent in sorted(values.items()):
        old = by_month.get(ym)
        if old is not None and abs(old - cent) < _EPS:
            continue
        by_month[ym] = cent
        touched.add(ym)
        report.changes.append(f"{key} {ym[0]}-{ym[1]:02d}: {_fmt(old)} → {cent:g}")
    if touched:
        _write_rows(doc, key, by_month)
    return touched


def _reseed_tariff(
    doc: dict,
    side: str,
    tariff: dict,
    months: set[YearMonth] | None,
    report: UpdateReport,
) -> bool:
    """Seeded Monatswerte übernehmen; ``months=None`` = alle Monate der Kurve."""
    seeded = build_seeded_monthly_rates(doc, tariff)
    by_month = _rows_by_month(tariff.get("monthly_rates", []))
    changed = False
    for year, month, cent in seeded:
        ym = (year, month)
        if months is not None and ym not in months:
            continue
        old = by_month.get(ym)
        if cent <= 0.0:
            report.warnings.append(
                f"{side}:{tariff['id']} {year}-{month:02d}: Seed ergibt {cent:g} ct "
                "(≤ 0, monthly_rates erlaubt nur > 0) — manuell entscheiden, "
                f"bestehender Wert {_fmt(old)} bleibt."
            )
            continue
        if old is not None and abs(old - cent) < _EPS:
            continue
        by_month[ym] = cent
        changed = True
        report.changes.append(
            f"{side}:{tariff['id']} {year}-{month:02d}: {_fmt(old)} → {cent:g}"
        )
    if changed:
        _write_rows(tariff, "monthly_rates", by_month)
    return changed


def _warn_months_beyond_curve(doc: dict, report: UpdateReport) -> None:
    """Seeded Tarife mit Monaten ohne Kurvenwert (Platzhalter/Fallback) melden."""
    for side, tariff in _iter_tariffs(doc):
        curve = monthly_seed_curve(tariff)
        if curve is None:
            continue
        curve_months = set(_rows_by_month(doc.get(SEED_CURVE_KEYS[curve], [])))
        extra = sorted(set(_rows_by_month(tariff.get("monthly_rates", []))) - curve_months)
        if extra:
            months = ", ".join(f"{y}-{m:02d}" for y, m in extra)
            report.warnings.append(
                f"{side}:{tariff['id']}: Monate ohne {SEED_CURVE_KEYS[curve]}-Wert "
                f"(Platzhalter, beim nächsten Kurven-Update ersetzt): {months}"
            )


def update_catalog(
    doc: dict,
    *,
    oemag: dict[YearMonth, float] | None = None,
    refmarkt: dict[YearMonth, float] | None = None,
    tariff_values: list[tuple[str, str, YearMonth, float]] | None = None,
    resync_all: bool = False,
    catalog_as_of: str | None = None,
) -> UpdateReport:
    """Aktualisiert ``doc`` (roh, list-shaped) in place und liefert den Änderungsbericht."""
    report = UpdateReport()
    touched = {
        SEED_CURVE_OEMAG: _upsert_curve(doc, SEED_CURVE_OEMAG, oemag or {}, report),
        SEED_CURVE_REFMARKT_PV: _upsert_curve(
            doc, SEED_CURVE_REFMARKT_PV, refmarkt or {}, report
        ),
    }
    for side, tariff in _iter_tariffs(doc):
        curve = monthly_seed_curve(tariff)
        if curve is None:
            continue
        if resync_all:
            _reseed_tariff(doc, side, tariff, None, report)
        elif touched[curve]:
            _reseed_tariff(doc, side, tariff, touched[curve], report)
    for side, tariff_id, ym, cent in tariff_values or []:
        tariff = _find_tariff(doc, side, tariff_id)
        if str(tariff.get("type", "")).strip().lower() != "monthly_table":
            raise ValueError(f"Tarif '{tariff_id}' ist kein monthly_table.")
        if monthly_seed_curve(tariff) is not None:
            raise ValueError(
                f"Tarif '{tariff_id}' wird aus monthly_seed berechnet — "
                "Einzelwerte würden beim nächsten Update überschrieben. "
                "Stattdessen monthly_seed entfernen oder Kurve aktualisieren."
            )
        by_month = _rows_by_month(tariff.get("monthly_rates", []))
        old = by_month.get(ym)
        if old is None or abs(old - cent) >= _EPS:
            by_month[ym] = cent
            _write_rows(tariff, "monthly_rates", by_month)
            report.changes.append(
                f"{side}:{tariff_id} {ym[0]}-{ym[1]:02d}: {_fmt(old)} → {cent:g}"
            )
    if catalog_as_of and doc.get("catalog_as_of") != catalog_as_of:
        report.changes.append(
            f"catalog_as_of: {doc.get('catalog_as_of')} → {catalog_as_of}"
        )
        doc["catalog_as_of"] = catalog_as_of
    _warn_months_beyond_curve(doc, report)
    return report


def check_catalog(doc: dict) -> UpdateReport:
    """Drift-Prüfung: seeded Tarife vs. Kurven (ändert ``doc`` nicht)."""
    probe = json.loads(json.dumps(doc))
    return update_catalog(probe, resync_all=True)


def _collect(values: list[str]) -> dict[YearMonth, float]:
    out: dict[YearMonth, float] = {}
    for text in values:
        ym, cent = parse_month_value(text)
        out[ym] = cent
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OeMAG-/RefMarkt-Monatswerte eintragen und seeded Katalog-Tarife nachrechnen."
    )
    parser.add_argument("--path", default=str(DEFAULT_CATALOG), help="tariffs.json (Standard: share/config)")
    parser.add_argument("--oemag", action="append", default=[], metavar="JJJJ-MM=CENT",
                        help="OeMAG-Marktpreis (§ 13 ÖSG), mehrfach möglich")
    parser.add_argument("--refmarkt", action="append", default=[], metavar="JJJJ-MM=CENT",
                        help="E-Control Referenzmarktwert PV (§ 13 EAG), mehrfach möglich")
    parser.add_argument("--set", action="append", default=[], dest="tariff_values",
                        metavar="SEITE:ID:JJJJ-MM=CENT",
                        help="Einzelwert für einen monthly_table-Tarif ohne monthly_seed")
    parser.add_argument("--resync-all", action="store_true",
                        help="Alle Monate aller seeded Tarife aus den Kurven neu rechnen")
    parser.add_argument("--catalog-as-of", default=None, help="catalog_as_of setzen (z. B. 2026-10-01)")
    parser.add_argument("--dry-run", action="store_true", help="Nur Bericht, nicht schreiben")
    parser.add_argument("--check", action="store_true",
                        help="Drift seeded Tarife ↔ Kurven prüfen (Exit 1 bei Abweichung)")
    args = parser.parse_args(argv)

    path = Path(args.path)
    doc = json.loads(path.read_text(encoding="utf-8"))

    if args.check:
        report = check_catalog(doc)
        print(report.format())
        return 1 if report.changes else 0

    try:
        report = update_catalog(
            doc,
            oemag=_collect(args.oemag),
            refmarkt=_collect(args.refmarkt),
            tariff_values=[parse_tariff_value(t) for t in args.tariff_values],
            resync_all=args.resync_all,
            catalog_as_of=args.catalog_as_of,
        )
    except ValueError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    print(report.format())
    if report.changes and not args.dry_run:
        from settings.json_io import write_json_dict

        write_json_dict(str(path), doc)
        print(f"Geschrieben: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
