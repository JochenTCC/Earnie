"""Unit tests for ui.tariff_filter_helpers pure filter helpers."""
from __future__ import annotations

from ui.tariff_filter_helpers import (
    EXPORT_TYPE_LABELS,
    filter_tariffs,
    lands_present,
    lands_union,
    tariff_parameter_rows,
    type_caption,
    types_present,
    with_current_tariff,
)
_SAMPLE = [
    {"id": "at_spot", "land": "AT", "type": "spot_hourly", "label": "AT Spot"},
    {"id": "at_fix", "land": "AT", "type": "fixed_cent", "label": "AT Fix"},
    {"id": "de_spot", "land": "DE", "type": "spot_hourly", "label": "DE Spot"},
    {"id": "legacy", "type": "fixed", "label": "No land"},
]

_EXPORT_MONTHLY = [
    {"id": "sunny", "land": "AT", "type": "monthly_table", "label": "SUNNY"},
    {"id": "oemag", "land": "AT", "type": "monthly_table", "label": "OeMAG"},
    {"id": "at_spot", "land": "AT", "type": "spot_hourly", "label": "AT Spot"},
    {"id": "de_float", "land": "DE", "type": "monthly_table", "label": "DE Float"},
]


def test_filter_by_land() -> None:
    result = filter_tariffs(_SAMPLE, land="AT")
    assert [item["id"] for item in result] == ["at_spot", "at_fix"]


def test_filter_by_type() -> None:
    result = filter_tariffs(_SAMPLE, tariff_type="spot_hourly")
    assert [item["id"] for item in result] == ["at_spot", "de_spot"]


def test_filter_combined() -> None:
    result = filter_tariffs(_SAMPLE, land="AT", tariff_type="fixed_cent")
    assert [item["id"] for item in result] == ["at_fix"]


def test_filter_all_keeps_missing_land() -> None:
    result = filter_tariffs(_SAMPLE)
    assert len(result) == 4
    assert "legacy" in {item["id"] for item in result}


def test_filter_land_excludes_missing_land() -> None:
    result = filter_tariffs(_SAMPLE, land="AT")
    assert "legacy" not in {item["id"] for item in result}


def test_lands_and_types_present() -> None:
    assert lands_present(_SAMPLE) == ["AT", "DE"]
    assert types_present(_SAMPLE) == ["fixed", "fixed_cent", "spot_hourly"]


def test_lands_union_across_catalogs() -> None:
    imports = [{"id": "a", "land": "AT"}, {"id": "b", "land": "DE"}]
    exports = [{"id": "c", "land": "CH"}, {"id": "d", "land": "AT"}]
    assert lands_union(imports, exports) == ["AT", "CH", "DE"]


def test_types_present_after_land_cascade() -> None:
    after_land = filter_tariffs(_SAMPLE, land="DE")
    assert types_present(after_land) == ["spot_hourly"]


def test_export_types_present_collapses_monthly() -> None:
    assert types_present(_EXPORT_MONTHLY, kind="export") == [
        "monthly_table",
        "spot_hourly",
    ]


def test_export_filter_monthly_table() -> None:
    result = filter_tariffs(
        _EXPORT_MONTHLY, tariff_type="monthly_table", kind="export"
    )
    assert [item["id"] for item in result] == ["sunny", "oemag", "de_float"]


def test_export_monthly_ui_label() -> None:
    assert type_caption({"type": "monthly_table"}, EXPORT_TYPE_LABELS) == "Monatspreis"
    assert EXPORT_TYPE_LABELS["monthly_table"] == "Monatspreis"


def test_with_current_inside_filters() -> None:
    filtered = filter_tariffs(_SAMPLE, land="AT")
    result, outside = with_current_tariff(filtered, _SAMPLE, "at_spot")
    assert outside is False
    assert [item["id"] for item in result] == ["at_spot", "at_fix"]


def test_with_current_outside_filters_unions() -> None:
    filtered = filter_tariffs(_SAMPLE, land="DE")
    result, outside = with_current_tariff(filtered, _SAMPLE, "at_spot")
    assert outside is True
    assert [item["id"] for item in result] == ["at_spot", "de_spot"]


def test_with_current_unknown_id() -> None:
    filtered = filter_tariffs(_SAMPLE, land="DE")
    result, outside = with_current_tariff(filtered, _SAMPLE, "missing")
    assert outside is False
    assert [item["id"] for item in result] == ["de_spot"]


def test_parameter_rows_fixed_cent() -> None:
    rows = dict(
        tariff_parameter_rows(
            {
                "type": "fixed_cent",
                "land": "AT",
                "currency": "EUR",
                "price_cent_kwh": 28.5,
                "notes": "Test",
            },
            kind="import",
        )
    )
    assert rows["Typ"] == "Fixpreis Bezug"
    assert rows["Land"] == "AT"
    assert rows["Währung"] == "EUR"
    assert rows["Arbeitspreis"] == "28.50 Cent/kWh"
    assert rows["Hinweis"] == "Test"
    assert "Abwicklungsgebühr" not in rows


def test_parameter_rows_awattar() -> None:
    rows = dict(
        tariff_parameter_rows(
            {
                "type": "awattar",
                "land": "AT",
                "settlement_fee_cent_kwh": 1.5,
                "markup_percent": 3,
                "prices_include_vat": True,
                "vat_percent": 20,
                "fix_aufschlag_cent": 1.44,
            },
            kind="import",
        )
    )
    assert rows["Typ"].startswith("aWATTar")
    assert rows["Abwicklungsgebühr"] == "1.50 Cent/kWh"
    assert rows["Aufschlag"] == "3 %"
    assert rows["Preise inkl. USt"] == "ja"
    assert rows["USt"] == "20 %"
    assert rows["Fix-Aufschlag"] == "1.44 Cent/kWh"
    assert "Arbeitspreis" not in rows


def test_parameter_rows_export_fixed() -> None:
    rows = dict(
        tariff_parameter_rows(
            {"type": "fixed", "land": "DE", "k_push_cent": 8.2},
            kind="export",
        )
    )
    assert rows["Typ"] == "Fixpreis Einspeise"
    assert rows["Einspeisevergütung"] == "8.20 Cent/kWh"


def test_parameter_rows_monthly_table_summary() -> None:
    rows = dict(
        tariff_parameter_rows(
            {
                "type": "monthly_table",
                "land": "AT",
                "monthly_rates": [
                    {"year": 2025, "month": 1, "tariff_cent_kwh": 5.0},
                    {"year": 2025, "month": 2, "tariff_cent_kwh": 7.5},
                ],
            },
            kind="export",
        )
    )
    assert rows["Typ"] == "Monatspreis"
    assert rows["Monatsraten"] == "2"
    assert rows["Monatsraten Min–Max (Cent/kWh)"] == "5.00 – 7.50"


def test_parameter_rows_omits_missing_optional() -> None:
    rows = dict(tariff_parameter_rows({"type": "spot_hourly"}, kind="import"))
    assert rows["Typ"] == "Spot stündlich"
    assert set(rows) == {"Typ"}
