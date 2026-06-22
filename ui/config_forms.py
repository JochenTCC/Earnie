"""Sidebar-Formulare für PV-, Batterie- und Tuning-Parameter."""
from __future__ import annotations

import streamlit as st

from data import pv_tuner
from ui.runtime_config import get_runtime_settings, update_config_file


def render_pv_config_inputs(settings: dict) -> tuple[float, int, int, float]:
    st.markdown("#### ☀️ PV-Anlage")
    kwp = st.number_input(
        "PV Leistung (kWp)",
        min_value=0.0,
        value=float(settings["PV_KWP"]),
        step=0.1,
        format="%.2f",
    )
    tilt = st.number_input(
        "Dachneigung (°)",
        min_value=0,
        max_value=90,
        value=int(settings["PV_TILT"]),
    )
    azimuth = st.number_input(
        "Ausrichtung (Azimut °)",
        min_value=-180,
        max_value=180,
        value=int(settings["PV_AZIMUTH"]),
        help="0=Süd, -90=Ost, 90=West",
    )
    k_push = st.number_input(
        "Einspeisevergütung (Cent/kWh)",
        min_value=0.0,
        value=float(settings["K_PUSH_CENT"]),
        step=0.1,
        format="%.2f",
    )
    return kwp, tilt, azimuth, k_push


def render_battery_config_inputs(settings: dict) -> tuple[float, float, float, float, float]:
    st.markdown("#### 🔋 Batterie-Speicher")
    bat_capacity = st.number_input(
        "Speicher-Kapazität (kWh)",
        min_value=0.1,
        value=float(settings["BATTERY_CAPACITY_KWH"]),
        step=0.5,
        format="%.1f",
    )
    bat_min_soc = st.number_input(
        "Minimaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(settings["BATTERY_MIN_SOC"]),
        step=1.0,
    )
    bat_max_soc = st.number_input(
        "Maximaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(settings["BATTERY_MAX_SOC"]),
        step=1.0,
    )
    bat_max_power = st.number_input(
        "Max. Lade-/Entladeleistung (kW)",
        min_value=0.1,
        value=float(settings["BATTERY_MAX_POWER_KW"]),
        step=0.1,
        format="%.2f",
    )
    threshold_percent = st.number_input(
        "Leistungs-Schwelle (%)",
        min_value=5.0,
        max_value=100.0,
        value=float(settings["THRESHOLD_POWER"]) * 100.0,
        step=5.0,
        format="%.0f",
        help="Anteil der max. Lade-/Entladeleistung (z. B. 5 % = 0,05 × max. kW). "
        "Gilt für Modus-Umschaltung und Zwangsentladen vs. Automatik.",
    )
    threshold_power = threshold_percent / 100.0
    return bat_capacity, bat_min_soc, bat_max_soc, bat_max_power, threshold_power


def render_config_form(settings: dict) -> None:
    with st.sidebar.form("config_form"):
        kwp, tilt, azimuth, k_push = render_pv_config_inputs(settings)
        bat_capacity, bat_min_soc, bat_max_soc, bat_max_power, threshold_power = (
            render_battery_config_inputs(settings)
        )

        submit_btn = st.form_submit_button("Alle Änderungen übernehmen")
        if submit_btn:
            update_config_file({
                "PV_KWP": kwp,
                "PV_TILT": tilt,
                "PV_AZIMUTH": azimuth,
                "K_PUSH_CENT": k_push,
                "BATTERY_CAPACITY_KWH": bat_capacity,
                "BATTERY_MIN_SOC": bat_min_soc,
                "BATTERY_MAX_SOC": bat_max_soc,
                "BATTERY_MAX_POWER_KW": bat_max_power,
                "THRESHOLD_POWER": threshold_power,
            })
            st.rerun()


def render_pv_tuning_sidebar() -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📈 Adaptives PV-Tuning")

    try:
        tuning_factor = pv_tuner.calculate_tuning_factor(days_back=14)
        deviation_pct = (tuning_factor - 1.0) * 100

        if tuning_factor == 1.0:
            delta_text = "Keine Abweichung (Basis)"
            delta_color = "off"
        elif tuning_factor > 1.0:
            delta_text = f"+{deviation_pct:.1f}% Mehrertrag vs. Prognose"
            delta_color = "normal"
        else:
            delta_text = f"{deviation_pct:.1f}% Minderertrag vs. Prognose"
            delta_color = "inverse"

        st.sidebar.metric(
            label="Aktueller Korrekturfaktor",
            value=f"{tuning_factor:.2f}",
            delta=delta_text,
            delta_color=delta_color,
        )
    except Exception as e:
        st.sidebar.warning(f"⚠️ Tuning-Faktor konnte nicht berechnet werden: {e}")

    st.sidebar.caption(
        "Errechnet aus dem automatischen Abgleich zwischen Forecast.Solar "
        "und deine realen Loxone-Zählerständen der vergangenen 2 Wochen."
    )


def render_parameter_input(mode: str) -> None:
    if mode == "Backtesting":
        return
    st.sidebar.header("⚙️ System-Parameter")
    st.sidebar.markdown("Änderungen werden direkt über das Konfigurationsmodul angewendet.")

    render_config_form(get_runtime_settings())
    if mode == "Echtzeit":
        render_pv_tuning_sidebar()
