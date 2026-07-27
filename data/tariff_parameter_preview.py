"""Read-only German label/value pairs for tariff catalog fields."""
from __future__ import annotations

from typing import Literal

IMPORT_TYPE_LABELS = {
    "fixed_cent": "Fixpreis Bezug",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
    "monthly_market": "Monatsmarkt",
    "monthly_table": "Monatstabelle Bezug",
}

EXPORT_TYPE_LABELS = {
    "fixed": "Fixpreis Einspeise",
    "monthly_table": "Monatspreis",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
}


def type_caption(tariff: dict, labels: dict[str, str]) -> str:
    tariff_type = str(tariff.get("type", "")).strip().lower()
    return labels.get(tariff_type, tariff_type or "unbekannt")


def _fmt_number(value: float | int, *, suffix: str = "") -> str:
    num = float(value)
    text = f"{num:g}" if num == int(num) else f"{num:.2f}"
    return f"{text}{suffix}" if suffix else text


def _append_if_present(
    rows: list[tuple[str, str]],
    tariff: dict,
    key: str,
    label: str,
    *,
    suffix: str = "",
) -> None:
    raw = tariff.get(key)
    if raw is None:
        return
    rows.append((label, _fmt_number(raw, suffix=suffix)))


def _append_bool_if_present(
    rows: list[tuple[str, str]],
    tariff: dict,
    key: str,
    label: str,
) -> None:
    if key not in tariff or tariff[key] is None:
        return
    rows.append((label, "ja" if tariff[key] else "nein"))


def _append_monthly_rates_summary(
    rows: list[tuple[str, str]], tariff: dict
) -> None:
    rates = tariff.get("monthly_rates")
    if not isinstance(rates, list) or not rates:
        return
    cents: list[float] = []
    for entry in rates:
        if not isinstance(entry, dict) or entry.get("tariff_cent_kwh") is None:
            continue
        cents.append(float(entry["tariff_cent_kwh"]))
    if not cents:
        return
    rows.append(("Monatsraten", str(len(cents))))
    rows.append(
        (
            "Monatsraten Min–Max (Cent/kWh)",
            f"{min(cents):.2f} – {max(cents):.2f}",
        )
    )


def _append_common_meta(rows: list[tuple[str, str]], tariff: dict) -> None:
    land = tariff.get("land")
    if land:
        rows.append(("Land", str(land)))
    currency = tariff.get("currency")
    if currency:
        rows.append(("Währung", str(currency)))
    _append_if_present(
        rows,
        tariff,
        "monthly_fee_eur",
        "Lieferant-Grundpreis (ca.)",
        suffix=" €/Monat",
    )
    _append_if_present(
        rows,
        tariff,
        "grid_monthly_fee_eur",
        "Netzentgelt-Grundpreis (ca.)",
        suffix=" €/Monat",
    )
    _append_if_present(
        rows,
        tariff,
        "metering_monthly_fee_eur",
        "Messstellengebühr (ca.)",
        suffix=" €/Monat",
    )
    _append_if_present(
        rows,
        tariff,
        "other_monthly_fee_eur",
        "Sonstige Fixkosten (ca.)",
        suffix=" €/Monat",
    )
    supplier_id = tariff.get("supplier_id")
    if supplier_id:
        rows.append(("Anbieter (supplier_id)", str(supplier_id)))
    notes = tariff.get("notes")
    if notes:
        rows.append(("Hinweis", str(notes)))


def _append_fee_vat_fields(rows: list[tuple[str, str]], tariff: dict) -> None:
    _append_if_present(
        rows, tariff, "settlement_fee_cent_kwh", "Abwicklungsgebühr", suffix=" Cent/kWh"
    )
    _append_if_present(rows, tariff, "markup_percent", "Aufschlag", suffix=" %")
    _append_bool_if_present(rows, tariff, "prices_include_vat", "Preise inkl. USt")
    _append_if_present(rows, tariff, "vat_percent", "USt", suffix=" %")
    _append_if_present(
        rows, tariff, "netzentgelt_cent_kwh", "Netzentgelt", suffix=" Cent/kWh"
    )


def _append_type_specific_rows(
    rows: list[tuple[str, str]], tariff: dict, tariff_type: str
) -> None:
    if tariff_type == "fixed_cent":
        _append_if_present(
            rows, tariff, "price_cent_kwh", "Arbeitspreis", suffix=" Cent/kWh"
        )
    elif tariff_type in {
        "spot_hourly",
        "ex_post_spot",
        "monthly_market",
    }:
        _append_fee_vat_fields(rows, tariff)
        _append_if_present(
            rows, tariff, "feed_in_fee_factor", "Einspeise-Gebührenfaktor"
        )
        _append_if_present(
            rows, tariff, "feed_in_fix_cent", "Einspeise-Fix", suffix=" Cent/kWh"
        )
    elif tariff_type == "monthly_table":
        _append_fee_vat_fields(rows, tariff)
        _append_monthly_rates_summary(rows, tariff)
    elif tariff_type == "fixed":
        _append_if_present(
            rows, tariff, "k_push_cent", "Einspeisevergütung", suffix=" Cent/kWh"
        )
        _append_fee_vat_fields(rows, tariff)
    else:
        _append_fee_vat_fields(rows, tariff)


def _type_labels_for(kind: Literal["import", "export"]) -> dict[str, str]:
    return IMPORT_TYPE_LABELS if kind == "import" else EXPORT_TYPE_LABELS


def tariff_parameter_rows(
    tariff: dict,
    *,
    kind: Literal["import", "export"],
) -> list[tuple[str, str]]:
    """German label/value pairs for present catalog fields (read-only preview)."""
    rows: list[tuple[str, str]] = []
    tariff_type = str(tariff.get("type", "")).strip().lower()
    labels = _type_labels_for(kind)
    caption = type_caption(tariff, labels)
    if caption:
        rows.append(("Typ", caption))
    _append_common_meta(rows, tariff)
    _append_type_specific_rows(rows, tariff, tariff_type)
    return rows
