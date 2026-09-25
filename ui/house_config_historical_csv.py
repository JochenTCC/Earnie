"""Hauskonfigurator: historische Jahres-Leistungsprofile (Last / PV / Energiemonitor / Bilanz)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.form_layout import labeled_text_input
from ui.house_config_io import (
    apply_csv_path_pending,
    csv_upload_widget_key,
    queue_csv_path_update,
    save_balance_total_from_component_paths,
    save_energiemonitor_profile_csvs,
    save_profile_consumption_csv,
    single_csv_upload,
)

_SOURCE_SEPARATE = "separate"
_SOURCE_ENERGIEMONITOR = "energiemonitor"
_SOURCE_BALANCE = "balance"
_SOURCE_LABELS = {
    _SOURCE_SEPARATE: (
        "Getrennte CSVs (Lastprofil + optional PV-Erzeugungsprofil)"
    ),
    _SOURCE_ENERGIEMONITOR: (
        "Loxone Energiemonitor - Leistungsprofile "
        "(PV + Batterie + Netz + Last)"
    ),
    _SOURCE_BALANCE: (
        "Bilanz - Leistungsprofile (PV + Batterie + Netz → Last)"
    ),
}
_VALID_SOURCES = frozenset(_SOURCE_LABELS)

_DIST_EQUAL = "equal"
_DIST_MONTHLY = "monthly"
_DIST_LABELS = {
    _DIST_EQUAL: "Jahres-Rest gleichmäßig",
    _DIST_MONTHLY: "Monats-Rest je Monat",
}




def init_historical_csv_session(preview_id: str, existing: dict) -> None:
    from house_config.baseload import normalize_baseload_distribution

    keys = session_keys(preview_id)
    if keys["source"] not in st.session_state:
        raw = str(existing.get("historical_csv_source", "") or "").strip().lower()
        st.session_state[keys["source"]] = (
            raw if raw in _VALID_SOURCES else _SOURCE_SEPARATE
        )
    if keys["verbrauch"] not in st.session_state:
        st.session_state[keys["verbrauch"]] = str(
            existing.get("total_profile_csv", "") or ""
        ).strip()
    if keys["pv"] not in st.session_state:
        st.session_state[keys["pv"]] = str(existing.get("pv_profile_csv", "") or "").strip()
    if keys["battery"] not in st.session_state:
        st.session_state[keys["battery"]] = str(
            existing.get("battery_profile_csv", "") or ""
        ).strip()
    if keys["grid"] not in st.session_state:
        st.session_state[keys["grid"]] = str(
            existing.get("grid_profile_csv", "") or ""
        ).strip()
    if keys["baseload_dist"] not in st.session_state:
        st.session_state[keys["baseload_dist"]] = normalize_baseload_distribution(
            existing.get("baseload_distribution")
        )


def historical_csv_save_fields(preview_id: str, existing: dict) -> dict[str, str]:
    """Fields to persist on house-profile save."""
    from house_config.baseload import normalize_baseload_distribution

    keys = session_keys(preview_id)
    return {
        "total_profile_csv": st.session_state.get(
            keys["verbrauch"], existing.get("total_profile_csv", "")
        ),
        "pv_profile_csv": st.session_state.get(
            keys["pv"], existing.get("pv_profile_csv", "")
        ),
        "battery_profile_csv": st.session_state.get(
            keys["battery"], existing.get("battery_profile_csv", "")
        ),
        "grid_profile_csv": st.session_state.get(
            keys["grid"], existing.get("grid_profile_csv", "")
        ),
        "historical_csv_source": st.session_state.get(
            keys["source"], existing.get("historical_csv_source", _SOURCE_SEPARATE)
        ),
        "baseload_distribution": normalize_baseload_distribution(
            st.session_state.get(
                keys["baseload_dist"],
                existing.get("baseload_distribution"),
            )
        ),
    }


def _historical_csv_state(preview_id: str, keys: dict[str, str]) -> dict:
    """Current CSV paths and Bilanz sign flags from session state."""
    return {
        "verbrauch": str(st.session_state.get(keys["verbrauch"], "") or "").strip(),
        "pv": str(st.session_state.get(keys["pv"], "") or "").strip(),
        "battery": str(st.session_state.get(keys["battery"], "") or "").strip(),
        "grid": str(st.session_state.get(keys["grid"], "") or "").strip(),
        "invert_pv": bool(
            st.session_state.get(f"house_profile_balance_invert_pv_{preview_id}", False)
        ),
        "invert_battery": bool(
            st.session_state.get(
                f"house_profile_balance_invert_batt_{preview_id}", False
            )
        ),
        "invert_grid": bool(
            st.session_state.get(
                f"house_profile_balance_invert_grid_{preview_id}", False
            )
        ),
    }


def _render_historical_csv_intro() -> None:
    st.subheader("Historische Jahres-Leistungsprofile [kW]")
    st.caption(
        "Optional — für Ist-vs-Modell, Bilanz-Import und realistischere "
        "Explorer-Rechnungen. Ohne CSV gilt nur das modellierte Hausprofil."
    )


def _render_csv_import_expander(preview_id: str, keys: dict[str, str]) -> None:
    """Import-mode radio, per-mode upload widgets and the QC block."""
    with st.expander("Historische Jahres-Leistungsprofile [kW] (CSV)", expanded=True):
        st.caption(
            "Lastprofil [kW] (für Ist in Gesamt-Lastverhalten) und optional "
            "PV-Erzeugungsprofil [kW]. "
            "Bevorzugt: Leistungsdaten (`timestamp;power_kw`, stündlich). "
            "Energiezähler [kWh] (kumuliert) werden ebenfalls akzeptiert und "
            "automatisch in mittlere Leistung [kW] umgerechnet. "
            "Kurze Serien sind für visuelle Kontrolle erlaubt; "
            "Szenario-Explorer braucht ≥12 Monate, sonst synthetische Werte. "
            "Alternativ: Bilanz aus PV + Netz (Batterie optional) "
            "(`P_Ges = P_PV + P_Batt + P_Grid`, positiv = in das Haussystem). "
            "SOC wird nicht importiert."
        )

        source = st.radio(
            "Datenimport",
            options=[_SOURCE_SEPARATE, _SOURCE_ENERGIEMONITOR, _SOURCE_BALANCE],
            format_func=lambda value: _SOURCE_LABELS[value],
            key=keys["source"],
            horizontal=False,
        )

        if source == _SOURCE_ENERGIEMONITOR:
            _render_energiemonitor_mode(preview_id, keys)
        elif source == _SOURCE_BALANCE:
            _render_balance_mode(preview_id, keys)
        else:
            _render_separate_mode(preview_id, keys)

        state = _historical_csv_state(preview_id, keys)
        if state["verbrauch"] or state["pv"] or state["battery"] or state["grid"]:
            from ui.house_config_import_qc import render_import_power_qc

            render_import_power_qc(
                preview_id=preview_id,
                verbrauch_path=state["verbrauch"],
                pv_path=state["pv"],
                battery_path=state["battery"],
                grid_path=state["grid"],
                invert_pv=state["invert_pv"],
                invert_battery=state["invert_battery"],
                invert_grid=state["invert_grid"],
            )


def _load_balance_series(state: dict) -> list[tuple[str, float]] | None:
    if not (state["pv"] and state["grid"]):
        return None
    from ui.house_config_import_qc import load_balance_gesamt_series

    balance_series, _clipped = load_balance_gesamt_series(
        state["pv"],
        state["battery"],
        state["grid"],
        invert_pv=state["invert_pv"],
        invert_battery=state["invert_battery"],
        invert_grid=state["invert_grid"],
    )
    return balance_series


def _balance_reset_extra(state: dict) -> str:
    return (
        f"{state['invert_pv']:d}{state['invert_battery']:d}{state['invert_grid']:d}:"
        f"{state['pv']}:{state['battery']}:{state['grid']}"
    )


def render_historical_csv_section(
    *,
    existing: dict,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
) -> None:
    """CSV imports (collapsible) + always-visible Gesamt-Lastverhalten charts."""
    init_historical_csv_session(preview_id, existing)
    keys = session_keys(preview_id)

    _render_historical_csv_intro()
    _render_csv_import_expander(preview_id, keys)

    state = _historical_csv_state(preview_id, keys)
    balance_series = _load_balance_series(state)

    _render_gesamtverbraeuche(
        preview_id=preview_id,
        annual_kwh=annual_kwh,
        resolved=resolved,
        preview=preview,
        active_path=state["verbrauch"],
        pv_path=state["pv"],
        battery_path=state["battery"],
        grid_path=state["grid"],
        balance_series=balance_series,
        reset_extra=(
            _balance_reset_extra(state) if balance_series is not None else ""
        ),
    )






















def _load_ist_series(
    active_path: str,
    csv_series: list[tuple[str, float]] | None,
) -> list[tuple[str, float]]:
    if csv_series is not None:
        return csv_series
    from house_config.consumption_csv import (
        load_hourly_profile_csv,
        normalize_profile_csv_file,
    )

    try:
        return load_hourly_profile_csv(active_path)
    except ValueError:
        return normalize_profile_csv_file(active_path)


def _render_baseload_dist_radio(preview_id: str) -> str:
    return st.radio(
        "Basislast-Verteilung",
        options=[_DIST_EQUAL, _DIST_MONTHLY],
        format_func=lambda value: _DIST_LABELS[value],
        key=f"house_profile_baseload_dist_{preview_id}",
        horizontal=True,
        help=(
            "Jahres-Rest: konstante Grundlast (SE-Pfad A flat). "
            "Monats-Rest: pro Kalendermonat Ist − Verbraucher (≥ 0) — "
            "gilt für Gesamt-Lastverhalten-Charts und SE-Pfad A, wenn eine "
            "Gesamt-CSV vorhanden ist. SE-Pfad B (alle Gesteuert/Manual "
            "mit CSV) bleibt der stündliche Meter-Rest."
        ),
    )


def _resolve_baseload_display(
    probe,
    series: list[tuple[str, float]],
    *,
    dist_mode: str,
    annual_kwh: float,
    resolved: list[dict],
):
    if dist_mode == _DIST_MONTHLY:
        return _baseload_display_monthly(probe, series)
    return _baseload_display_equal(
        probe,
        annual_kwh=annual_kwh,
        resolved=resolved,
    )


def _render_ist_vs_modell(
    *,
    active_path: str,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
    pv_path: str,
    csv_series: list[tuple[str, float]] | None = None,
    reset_extra: str = "",
) -> None:
    from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display
    from ui.consumption_display.adapters import bundle_from_csv_validation

    try:
        modeled_profile = {
            "annual_kwh": annual_kwh,
            "baseload_kwh": preview["baseload_kwh"],
            "consumers": resolved,
            "total_profile_csv": (
                active_path if not active_path.startswith("bilanz:") else ""
            ),
            "pv_profile_csv": pv_path,
        }
        series = _load_ist_series(active_path, csv_series)
        probe = bundle_from_csv_validation(
            series,
            {**modeled_profile, "baseload_kwh": 0.0},
        )
        dist_mode = _render_baseload_dist_radio(preview_id)
        display_bundle, display_bl_kwh, caption = _resolve_baseload_display(
            probe,
            series,
            dist_mode=dist_mode,
            annual_kwh=annual_kwh,
            resolved=resolved,
        )
        st.caption(caption)
        render_consumption_display(
            ConsumptionDisplayMode.CSV_VALIDATION,
            key_prefix=f"house_profile_csv_{preview_id}",
            profile={
                **modeled_profile,
                "baseload_kwh": display_bl_kwh,
            },
            csv_series=series,
            annual_kwh=float(annual_kwh),
            bundle=display_bundle,
            reset_token=(
                f"{active_path}:{pv_path}:{dist_mode}:{display_bl_kwh:.3f}:"
                f"{reset_extra}"
            ),
        )
    except (ValueError, OSError) as exc:
        st.error(f"CSV konnte nicht ausgewertet werden: {exc}")

from ui.house_config_historical_modes import (  # noqa: E402
    _SOURCE_BALANCE,
    _SOURCE_ENERGIEMONITOR,
    _SOURCE_LABELS,
    _SOURCE_SEPARATE,
    _VALID_SOURCES,
    _DIST_EQUAL,
    _DIST_LABELS,
    _DIST_MONTHLY,
    _baseload_display_equal,
    _baseload_display_monthly,
    _hourly_consumer_sum,
    _maybe_persist_balance_total,
    _render_balance_mode,
    _render_component_upload,
    _render_energiemonitor_mode,
    _render_gesamtverbraeuche,
    _render_separate_mode,
    _save_signed_component_csv,
    session_keys,
)

__all__ = [
    "historical_csv_save_fields",
    "init_historical_csv_session",
    "render_historical_csv_section",
    "session_keys",
]
