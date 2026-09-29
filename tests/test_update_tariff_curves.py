"""Tests für scripts/update_tariff_curves.py (Katalog-Wartung monthly_seed)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.monthly_float_rates import build_seeded_monthly_rates
from scripts.update_tariff_curves import (
    check_catalog,
    main,
    parse_tariff_value,
    update_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "share" / "config" / "tariffs.json"


def _curve(start_month: int, values: list[float], year: int = 2025) -> list[dict]:
    rows = []
    for offset, cent in enumerate(values):
        month = start_month + offset
        rows.append(
            {"year": year + (month - 1) // 12, "month": (month - 1) % 12 + 1, "tariff_cent_kwh": cent}
        )
    return rows


def _doc() -> dict:
    oemag = _curve(7, [6.0] * 12)
    refmarkt = _curve(7, [5.0] * 12)
    return {
        "oemag_monthly_feed_in_rates": oemag,
        "monthly_float_reference_cent_kwh": 7.15,
        "econtrol_referenzmarktwert_pv_monthly": refmarkt,
        "import_tariffs": [],
        "export_tariffs": [
            {
                "id": "oemag_like",
                "type": "monthly_table",
                "settlement_fee_cent_kwh": 0.0,
                "monthly_seed": {"curve": "oemag", "arbeitspreis_kwh_cent": 7.15},
                "monthly_rates": [dict(r) for r in oemag],
            },
            {
                "id": "oemag_scaled_fee",
                "type": "monthly_table",
                "settlement_fee_cent_kwh": 1.5,
                "monthly_seed": {"curve": "oemag", "arbeitspreis_kwh_cent": 5.85},
                "monthly_rates": [
                    {**r, "tariff_cent_kwh": round(6.0 * 5.85 / 7.15 - 1.5, 4)} for r in oemag
                ],
            },
            {
                "id": "refmarkt_minus_fee",
                "type": "monthly_table",
                "settlement_fee_cent_kwh": 0.6,
                "monthly_seed": {"curve": "econtrol_refmarkt_pv"},
                "monthly_rates": [{**r, "tariff_cent_kwh": 4.4} for r in refmarkt]
                + [{"year": 2026, "month": 7, "tariff_cent_kwh": 4.4}],
            },
            {
                "id": "manual_table",
                "type": "monthly_table",
                "monthly_rates": [{"year": 2026, "month": 6, "tariff_cent_kwh": 5.0}],
            },
        ],
    }


def _rate(doc: dict, tariff_id: str, year: int, month: int) -> float | None:
    tariff = next(t for t in doc["export_tariffs"] if t["id"] == tariff_id)
    for row in tariff["monthly_rates"]:
        if (row["year"], row["month"]) == (year, month):
            return row["tariff_cent_kwh"]
    return None


def test_shipped_catalog_matches_monthly_seeds():
    doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    report = check_catalog(doc)
    assert report.changes == [], report.format()


def test_shipped_catalog_seeds_all_oemag_proportional_floats():
    doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    for tariff in doc["export_tariffs"]:
        if "Seed: OeMAG" in tariff.get("notes", ""):
            assert tariff.get("monthly_seed", {}).get("curve") == "oemag", tariff["id"]


def test_new_oemag_month_propagates_to_seeded_tariffs():
    doc = _doc()
    report = update_catalog(doc, oemag={(2026, 7): 8.0})
    assert _rate(doc, "oemag_like", 2026, 7) == pytest.approx(8.0)
    assert _rate(doc, "oemag_scaled_fee", 2026, 7) == pytest.approx(
        round(8.0 * 5.85 / 7.15 - 1.5, 4)
    )
    # RefMarkt-Tarif und manuelle Tabelle bleiben unberührt.
    assert _rate(doc, "refmarkt_minus_fee", 2026, 7) == pytest.approx(4.4)
    assert _rate(doc, "manual_table", 2026, 7) is None
    assert any("oemag_monthly_feed_in_rates 2026-07" in line for line in report.changes)


def test_refmarkt_month_replaces_placeholder_and_stays_sorted():
    doc = _doc()
    update_catalog(doc, refmarkt={(2026, 7): 3.1})
    assert _rate(doc, "refmarkt_minus_fee", 2026, 7) == pytest.approx(2.5)
    curve = doc["econtrol_referenzmarktwert_pv_monthly"]
    keys = [(r["year"], r["month"]) for r in curve]
    assert keys == sorted(keys)
    assert keys[-1] == (2026, 7)


def test_update_is_idempotent():
    doc = _doc()
    update_catalog(doc, oemag={(2026, 7): 8.0}, refmarkt={(2026, 7): 3.1})
    again = update_catalog(doc, oemag={(2026, 7): 8.0}, refmarkt={(2026, 7): 3.1})
    assert again.changes == []


def test_non_positive_seed_warns_and_keeps_old_value():
    doc = _doc()
    report = update_catalog(doc, refmarkt={(2026, 7): 0.5})
    assert _rate(doc, "refmarkt_minus_fee", 2026, 7) == pytest.approx(4.4)
    assert any("manuell entscheiden" in w for w in report.warnings)


def test_set_value_on_manual_table():
    doc = _doc()
    update_catalog(doc, tariff_values=[("export", "manual_table", (2026, 7), 5.9)])
    assert _rate(doc, "manual_table", 2026, 7) == pytest.approx(5.9)


def test_set_value_on_seeded_tariff_is_rejected():
    doc = _doc()
    with pytest.raises(ValueError, match="monthly_seed"):
        update_catalog(doc, tariff_values=[("export", "oemag_like", (2026, 7), 5.9)])


def test_check_reports_drift():
    doc = _doc()
    doc["export_tariffs"][0]["monthly_rates"][0]["tariff_cent_kwh"] = 9.99
    report = check_catalog(doc)
    assert any("oemag_like 2025-07" in line for line in report.changes)
    # check_catalog ändert das Dokument nicht.
    assert doc["export_tariffs"][0]["monthly_rates"][0]["tariff_cent_kwh"] == 9.99


def test_build_seeded_requires_arbeitspreis_for_oemag():
    doc = _doc()
    tariff = {"id": "x", "monthly_seed": {"curve": "oemag"}}
    with pytest.raises(ValueError, match="arbeitspreis_kwh_cent"):
        build_seeded_monthly_rates(doc, tariff)


def test_parse_tariff_value_accepts_decimal_comma():
    assert parse_tariff_value("export:foo:2026-09=5,9") == ("export", "foo", (2026, 9), 5.9)


def test_cli_writes_catalog_copy(tmp_path: Path):
    path = tmp_path / "tariffs.json"
    path.write_text(json.dumps(_doc()), encoding="utf-8")
    assert main(["--path", str(path), "--oemag", "2026-07=8", "--catalog-as-of", "2026-10-01"]) == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["catalog_as_of"] == "2026-10-01"
    assert _rate(written, "oemag_like", 2026, 7) == pytest.approx(8.0)
    assert main(["--path", str(path), "--check"]) == 0


def test_cli_dry_run_does_not_write(tmp_path: Path):
    path = tmp_path / "tariffs.json"
    original = json.dumps(_doc())
    path.write_text(original, encoding="utf-8")
    assert main(["--path", str(path), "--oemag", "2026-07=8", "--dry-run"]) == 0
    assert path.read_text(encoding="utf-8") == original
