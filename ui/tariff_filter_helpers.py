"""Land/Typ filters for Bezugs- and Einspeisetarif pickers."""
from __future__ import annotations

from typing import Literal

import streamlit as st

ALL_FILTER = "Alle"

# Month-constant feed-in is catalog type monthly_table (owned monthly_rates).
EXPORT_MONTHLY_UI_TYPES = frozenset({"monthly_table"})
EXPORT_MONTHLY_UI_KEY = "monthly_table"

IMPORT_TYPE_LABELS = {
    "awattar": "aWATTar (EPEX + Aufschlag aus tariffs.json)",
    "fixed_cent": "Fixpreis Bezug",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
    "monthly_market": "Monatsmarkt",
    "monthly_table": "Monatstabelle Bezug",
}

EXPORT_TYPE_LABELS = {
    "fixed": "Fixpreis Einspeise",
    "dynamic_epex": "Dynamisch EPEX (Legacy)",
    "monthly_table": "Monatspreis",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
}


def _canonicalize_export_type(tariff_type: str) -> str:
    if tariff_type in EXPORT_MONTHLY_UI_TYPES:
        return EXPORT_MONTHLY_UI_KEY
    return tariff_type


def _export_type_matches(item_type: str, filter_type: str) -> bool:
    if filter_type in EXPORT_MONTHLY_UI_TYPES:
        return item_type in EXPORT_MONTHLY_UI_TYPES
    return item_type == filter_type


def type_caption(tariff: dict, labels: dict[str, str]) -> str:
    tariff_type = str(tariff.get("type", "")).strip().lower()
    return labels.get(tariff_type, tariff_type or "unbekannt")


def tariff_meta_caption(tariff: dict) -> str:
    parts: list[str] = []
    land = tariff.get("land")
    currency = tariff.get("currency")
    if land:
        parts.append(f"Land: {land}")
    if currency:
        parts.append(f"Währung: {currency}")
    notes = tariff.get("notes")
    if notes:
        parts.append(str(notes))
    return " · ".join(parts)


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
        "awattar",
        "spot_hourly",
        "ex_post_spot",
        "monthly_market",
    }:
        _append_fee_vat_fields(rows, tariff)
        if tariff_type == "awattar":
            _append_if_present(
                rows, tariff, "fix_aufschlag_cent", "Fix-Aufschlag", suffix=" Cent/kWh"
            )
            _append_if_present(rows, tariff, "netzverlust_faktor", "Netzverlust-Faktor")
            _append_if_present(
                rows, tariff, "mwst_austria_faktor", "USt-Faktor (AT)"
            )
    elif tariff_type == "monthly_table":
        _append_fee_vat_fields(rows, tariff)
        _append_monthly_rates_summary(rows, tariff)
    elif tariff_type == "fixed":
        _append_if_present(
            rows, tariff, "k_push_cent", "Einspeisevergütung", suffix=" Cent/kWh"
        )
        _append_fee_vat_fields(rows, tariff)
    elif tariff_type == "dynamic_epex":
        _append_if_present(rows, tariff, "feed_in_fee_factor", "Einspeise-Gebührenfaktor")
        _append_if_present(
            rows, tariff, "feed_in_fix_cent", "Einspeise-Fix", suffix=" Cent/kWh"
        )
        _append_fee_vat_fields(rows, tariff)
    else:
        _append_fee_vat_fields(rows, tariff)


def tariff_parameter_rows(
    tariff: dict,
    *,
    kind: Literal["import", "export"],
) -> list[tuple[str, str]]:
    """German label/value pairs for present catalog fields (read-only preview)."""
    rows: list[tuple[str, str]] = []
    tariff_type = str(tariff.get("type", "")).strip().lower()
    labels = _type_labels_for(kind)
    type_label = type_caption(tariff, labels)
    if type_label:
        rows.append(("Typ", type_label))
    _append_common_meta(rows, tariff)
    _append_type_specific_rows(rows, tariff, tariff_type)
    return rows


def render_tariff_parameter_preview(
    tariff: dict,
    *,
    title: str,
    kind: Literal["import", "export"],
) -> None:
    """Show compact read-only tariff parameters under a Scenario Editor select."""
    rows = tariff_parameter_rows(tariff, kind=kind)
    if not rows:
        return
    st.caption(title)
    for label, value in rows:
        st.caption(f"{label}: {value}")


def lands_present(tariffs: list[dict]) -> list[str]:
    lands = {
        str(item.get("land") or "").strip().upper()
        for item in tariffs
        if str(item.get("land") or "").strip()
    }
    return sorted(lands)


def lands_union(*tariff_lists: list[dict]) -> list[str]:
    """Sorted unique lands across multiple tariff catalogs (import + export)."""
    combined: list[dict] = []
    for tariffs in tariff_lists:
        combined.extend(tariffs)
    return lands_present(combined)


def types_present(
    tariffs: list[dict],
    *,
    kind: Literal["import", "export"] | None = None,
) -> list[str]:
    """Sorted unique types; export month-constant is monthly_table."""
    types: set[str] = set()
    for item in tariffs:
        raw = str(item.get("type") or "").strip().lower()
        if not raw:
            continue
        if kind == "export":
            raw = _canonicalize_export_type(raw)
        types.add(raw)
    return sorted(types)


def filter_tariffs(
    tariffs: list[dict],
    *,
    land: str | None = None,
    tariff_type: str | None = None,
    kind: Literal["import", "export"] | None = None,
) -> list[dict]:
    """Filter by land and/or type. None / empty means no restriction on that axis."""
    land_key = (land or "").strip().upper() or None
    type_key = (tariff_type or "").strip().lower() or None
    result: list[dict] = []
    for item in tariffs:
        if land_key is not None:
            item_land = str(item.get("land") or "").strip().upper()
            if item_land != land_key:
                continue
        if type_key is not None:
            item_type = str(item.get("type") or "").strip().lower()
            if kind == "export":
                if not _export_type_matches(item_type, type_key):
                    continue
            elif item_type != type_key:
                continue
        result.append(item)
    return result


def with_current_tariff(
    filtered: list[dict],
    all_tariffs: list[dict],
    current_id: str | None,
) -> tuple[list[dict], bool]:
    """Ensure current_id remains in the list. Returns (list, was_outside_filters)."""
    cid = (current_id or "").strip()
    if not cid:
        return list(filtered), False
    if any(str(item.get("id", "")).strip() == cid for item in filtered):
        return list(filtered), False
    match = next(
        (item for item in all_tariffs if str(item.get("id", "")).strip() == cid),
        None,
    )
    if match is None:
        return list(filtered), False
    return [match, *filtered], True


def _type_labels_for(kind: Literal["import", "export"]) -> dict[str, str]:
    return IMPORT_TYPE_LABELS if kind == "import" else EXPORT_TYPE_LABELS


def _format_type_option(type_key: str, labels: dict[str, str]) -> str:
    if type_key == ALL_FILTER:
        return ALL_FILTER
    return labels.get(type_key, type_key)


def render_shared_land_filter(
    *,
    key: str,
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> str | None:
    """Single Land selectbox for import and export. Returns None if Alle."""
    land_options = [ALL_FILTER, *lands_union(import_tariffs, export_tariffs)]
    land_pick = st.selectbox("Land", options=land_options, key=key)
    return None if land_pick == ALL_FILTER else land_pick


def render_tariff_type_filter(
    *,
    key_prefix: str,
    tariffs: list[dict],
    kind: Literal["import", "export"],
    land: str | None = None,
    current_id: str | None = None,
    label_prefix: str = "",
) -> list[dict]:
    """Render Typ filter (after shared Land); return filtered tariffs."""
    type_labels = _type_labels_for(kind)
    after_land = filter_tariffs(tariffs, land=land, kind=kind)
    type_options = [ALL_FILTER, *types_present(after_land, kind=kind)]
    type_key = f"{key_prefix}_type"
    if type_key in st.session_state and st.session_state[type_key] not in type_options:
        st.session_state[type_key] = ALL_FILTER
    type_pick = st.selectbox(
        f"{label_prefix}Typ".strip(),
        options=type_options,
        key=type_key,
        format_func=lambda t: _format_type_option(t, type_labels),
    )
    type_filter = None if type_pick == ALL_FILTER else type_pick
    filtered = filter_tariffs(after_land, tariff_type=type_filter, kind=kind)
    result, outside = with_current_tariff(filtered, tariffs, current_id)
    if outside:
        st.caption(
            "Aktuelle Auswahl liegt außerhalb der Filter — Tarif bleibt wählbar."
        )
    return result
