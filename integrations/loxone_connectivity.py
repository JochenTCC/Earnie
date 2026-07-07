"""Loxone-Verbindungsprüfung für Integrationstests und Installations-Checks."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Callable

import config
from integrations import loxone_client


@dataclass(frozen=True)
class LoxoneCheck:
    """Einzelprüfung: Label, IO-Name (optional), Erfolg, Detailtext."""

    label: str
    io_name: str
    passed: bool
    detail: str
    severity: str = "error"


def _check_counts_as_ok(item: LoxoneCheck) -> bool:
    """True wenn die Prüfung den Gesamtstatus nicht negativ beeinflusst."""
    return item.passed or item.severity == "warning"


def loxone_env_configured() -> bool:
    """True wenn Miniserver-Zugangsdaten in der Umgebung gesetzt sind."""
    return all(
        str(os.getenv(key, "")).strip()
        for key in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS")
    )


def ensure_live_config(config_path: str = config.CONFIG_JSON_PATH) -> None:
    """Lädt config.json mit Pflicht auf Loxone-Credentials (kein Offline-Modus)."""
    config.CONFIG = config.Config(
        config_path=config_path,
        require_loxone_credentials=True,
    )


def _read_check(
    label: str,
    io_name: str,
    *,
    validate: Callable[[float], str | None] | None = None,
    read_raw: bool = False,
    warn_if_missing: bool = False,
    validate_filter_start_hour: bool = False,
) -> LoxoneCheck:
    io_name = str(io_name or "").strip()
    if not io_name:
        return LoxoneCheck(label, io_name, False, "IO-Name fehlt in config.json")

    if read_raw:
        raw = loxone_client.fetch_loxone_raw_value(io_name)
        if raw is None:
            detail = "Lesen fehlgeschlagen (kein Wert)"
            if warn_if_missing:
                return LoxoneCheck(label, io_name, False, detail, severity="warning")
            return LoxoneCheck(label, io_name, False, detail)
        return LoxoneCheck(label, io_name, True, f"raw={raw!r}")

    if validate_filter_start_hour:
        hour, fmt, raw = loxone_client.fetch_filter_native_start_hour(io_name)
        if hour is None:
            detail = f"Start-Stunde nicht parsebar (raw={raw!r}, format={fmt})"
            return LoxoneCheck(label, io_name, False, detail)
        return LoxoneCheck(
            label,
            io_name,
            True,
            f"Start={hour:.0f} h, Format={fmt}, raw={raw!r}",
        )

    value = loxone_client.fetch_loxone_generic_value(io_name)
    if value is None:
        return LoxoneCheck(label, io_name, False, "Lesen oder Parsen fehlgeschlagen")
    if validate is not None:
        error = validate(float(value))
        if error:
            return LoxoneCheck(label, io_name, False, error)
    return LoxoneCheck(label, io_name, True, f"Wert={value}")


def _soc_valid(value: float) -> str | None:
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        return f"SoC außerhalb 0–100 %: {value}"
    return None


def _power_valid(value: float) -> str | None:
    if not math.isfinite(value):
        return f"Leistung nicht numerisch: {value}"
    if abs(value) > 500.0:
        return f"Leistung unrealistisch hoch: {value} kW"
    return None


def _binary_valid(value: float) -> str | None:
    if value in (0.0, 1.0):
        return None
    return f"Erwartet 0 oder 1, erhalten: {value}"


def _non_negative_hours(value: float) -> str | None:
    if not math.isfinite(value) or value < 0.0:
        return f"Stundenwert ungültig: {value}"
    return None


def _filter_duration_hours_valid(value: float) -> str | None:
    err = _non_negative_hours(value)
    if err:
        return err
    if value <= 0.0:
        return f"Dauer muss > 0 sein: {value}"
    return None


def _consumer_power_validate(consumer: dict) -> Callable[[float], str | None]:
    inputs = consumer.get("loxone_inputs") or {}
    signal = inputs.get("signal_type") or consumer.get("signal_type", "power")
    if signal == "binary":
        return _binary_valid
    return _power_valid


def collect_read_checks() -> list[tuple[str, str, dict]]:
    """(Label, IO-Name, Optionen) für alle konfigurierten Loxone-Eingänge."""
    checks: list[tuple[str, str, dict]] = [
        ("Batterie-SoC", config.get("LOXONE_SOC_NAME"), {"validate": _soc_valid}),
        ("PV-Leistung", config.get("LOXONE_PV_POWER_NAME"), {"validate": _power_valid}),
        ("Batterie-Leistung", config.get("LOXONE_BATTERY_POWER_NAME"), {"validate": _power_valid}),
        ("Netz-Leistung", config.get("LOXONE_GRID_POWER_NAME"), {"validate": _power_valid}),
        ("PV-Zähler", config.get("LOXONE_PV_COUNTER_NAME"), {}),
    ]
    for block_key, label in (
        ("LOXONE_TARGET_SOC_NAME", "Soll-SoC (Merker)"),
        ("LOXONE_TARGET_CHARGE_POWER_NAME", "Soll-Ladeleistung (Merker)"),
        ("LOXONE_TARGET_DISCHARGE_POWER_NAME", "Soll-Entladeleistung (Merker)"),
        ("LOXONE_CONTROL_CMD_NAME", "Steuerbefehl (Merker)"),
    ):
        io_name = config.get(block_key)
        if io_name:
            checks.append((label, io_name, {}))

    for consumer in config.get_flexible_consumers():
        cid = consumer["id"]
        inputs = consumer.get("loxone_inputs") or {}
        outputs = consumer.get("loxone_outputs") or {}
        power_name = inputs.get("power_name", "")
        if power_name:
            checks.append(
                (
                    f"Verbraucher {cid} Leistung",
                    power_name,
                    {"validate": _consumer_power_validate(consumer)},
                )
            )
        enable_name = outputs.get("enable_name", "")
        if enable_name:
            checks.append((f"Verbraucher {cid} Freigabe", enable_name, {"validate": _binary_valid}))
        setpoint_name = outputs.get("power_setpoint_name", "")
        if setpoint_name:
            checks.append(
                (f"Verbraucher {cid} Soll-Leistung", setpoint_name, {"validate": _power_valid})
            )
        pv_follow_name = outputs.get("pv_follow_name", "")
        if pv_follow_name:
            checks.append(
                (f"Verbraucher {cid} pv_follow", pv_follow_name, {"validate": _binary_valid})
            )

        sched = consumer.get("charging_schedule") or {}
        lox = sched.get("loxone") or {}
        for key, label in (
            ("plugged_in_name", f"Verbraucher {cid} angeschlossen"),
            ("soc_at_plug_in_name", f"Verbraucher {cid} Rest-SoC"),
            ("nominal_power_kw_name", f"Verbraucher {cid} Nennleistung"),
            ("battery_capacity_kwh_name", f"Verbraucher {cid} Akkukapazität"),
            ("charge_immediate_name", f"Verbraucher {cid} Sofort laden"),
            ("charge_immediate_remaining_name", f"Verbraucher {cid} Restladezeit Sofort"),
        ):
            io_name = lox.get(key, "")
            if io_name:
                opts: dict = {}
                if key in ("plugged_in_name", "charge_immediate_name"):
                    opts["validate"] = _binary_valid
                checks.append((label, io_name, opts))
        ready_name = lox.get("ready_by_time_name", "")
        if ready_name:
            checks.append(
                (
                    f"Verbraucher {cid} Fertig-um",
                    ready_name,
                    {"read_raw": True, "warn_if_missing": True},
                )
            )

        if consumer.get("daily_target_source") == "loxone_remaining_hours":
            hours_name = consumer.get("loxone_target_hours_name", "")
            if hours_name:
                checks.append(
                    (
                        f"Verbraucher {cid} Sollstunden",
                        hours_name,
                        {"validate": _non_negative_hours},
                    )
                )

        filter_sched = consumer.get("filter_schedule") or {}
        if filter_sched.get("enabled"):
            flox = filter_sched.get("loxone") or {}
            start_name = flox.get("native_start_hour_name", "")
            if start_name:
                checks.append(
                    (
                        f"Verbraucher {cid} Filter Start-Stunde",
                        start_name,
                        {"validate_filter_start_hour": True},
                    )
                )
            duration_name = flox.get("native_duration_hours_name", "")
            if duration_name:
                checks.append(
                    (
                        f"Verbraucher {cid} Filter Dauer (h)",
                        duration_name,
                        {"validate": _filter_duration_hours_valid},
                    )
                )

        thermal = consumer.get("thermal_control") or {}
        if thermal.get("enabled"):
            tlox = thermal.get("loxone") or {}
            for key, label in (
                ("actual_temp_name", f"Verbraucher {cid} Ist-Temp"),
                ("setpoint_temp_name", f"Verbraucher {cid} Soll-Temp"),
                ("ambient_temp_name", f"Verbraucher {cid} Außen-Temp"),
                ("tolerance_c_name", f"Verbraucher {cid} Temp-Toleranz"),
            ):
                io_name = tlox.get(key, "")
                if io_name:
                    checks.append((label, io_name, {}))

    for trigger in config.get_event_triggers():
        label = trigger.get("label") or trigger["id"]
        io_name = trigger["loxone_name"]
        if trigger["signal_type"] == "text":
            checks.append(
                (
                    f"Event-Trigger {label}",
                    io_name,
                    {"read_raw": True, "warn_if_missing": True},
                )
            )
        elif trigger["signal_type"] == "analog":
            checks.append((f"Event-Trigger {label}", io_name, {"validate": _soc_valid}))
        else:
            checks.append((f"Event-Trigger {label}", io_name, {"validate": _binary_valid}))

    return checks


def run_read_checks() -> list[LoxoneCheck]:
    """Liest alle konfigurierten IOs live vom Miniserver."""
    results: list[LoxoneCheck] = []
    for label, io_name, opts in collect_read_checks():
        results.append(_read_check(label, io_name, **opts))
    return results


def verify_loxone_setup() -> tuple[bool, list[LoxoneCheck]]:
    """
    Führt alle Lese-Prüfungen gegen den Miniserver aus.

    Returns:
        (alle_ok, einzelergebnisse)
    """
    ensure_live_config()
    results = run_read_checks()
    return all(_check_counts_as_ok(item) for item in results), results
