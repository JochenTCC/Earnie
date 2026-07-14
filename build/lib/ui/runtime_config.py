"""Laufzeit-Konfiguration und Session-Cache für die Streamlit-UI."""
from __future__ import annotations

import importlib

import streamlit as st

import config


def reload_runtime_config() -> None:
    """config.json vor UI-Aktualisierung neu laden (Änderungen aus main.py / Editor)."""
    config.reload_config()


def get_runtime_settings() -> dict:
    return config.get_runtime_settings()


def simulation_settings_fingerprint() -> str:
    """Stabile Kennung aller Laufzeitparameter, die die 24h-Simulation beeinflussen."""
    runtime = config.get_runtime_settings()
    battery = config.get_battery_params()
    tokens = [f"{key}={runtime[key]!r}" for key in sorted(runtime)]
    tokens.extend(f"b.{key}={battery[key]!r}" for key in sorted(battery))
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        outputs = consumer.get("loxone_outputs") or {}
        sched = consumer.get("charging_schedule") or {}
        lox = sched.get("loxone") or {}
        tokens.append(
            "fc.{id}={enable}|{setpoint}|{pv_follow}|{min_kw}|{immediate}".format(
                id=consumer["id"],
                enable=outputs.get("enable_name", ""),
                setpoint=outputs.get("power_setpoint_name", ""),
                pv_follow=outputs.get("pv_follow_name", ""),
                min_kw=consumer.get("min_power_kw", ""),
                immediate=lox.get("charge_immediate_name", ""),
            )
        )
    return ";".join(tokens)


def invalidate_live_optimization_cache() -> None:
    """Erzwingt Neuberechnung der Live-24h-Simulation."""
    for key in (
        "live_optimization_cache_key",
        "live_optimization_df",
        "live_savings_info",
        "live_display_bundle",
    ):
        st.session_state.pop(key, None)


def update_config_file(settings_dict: dict) -> None:
    """Aktualisiert runtime_settings-Referenzen (IDs + Geo) über config.update_runtime_settings."""
    try:
        config.update_runtime_settings(settings_dict)
        importlib.reload(config)
        invalidate_live_optimization_cache()
        st.success("✅ Alle Parameter erfolgreich gespeichert und im System aktualisiert!")
    except Exception as e:
        st.error(f"🚨 Fehler beim Speichern der Konfiguration: {e}")
