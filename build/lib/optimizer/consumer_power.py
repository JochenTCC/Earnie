"""Hilfen für flexible Verbraucher: Binär (Ein/Aus) vs. kW-Sollwert."""
from __future__ import annotations


def uses_power_setpoint(consumer: dict) -> bool:
    """True, wenn die Optimierung einen kW-Sollwert an Loxone sendet."""
    outputs = consumer.get("loxone_outputs") or {}
    return bool(str(outputs.get("power_setpoint_name", "")).strip())


def uses_pv_follow(consumer: dict) -> bool:
    """True, wenn Loxone zwischen fester Leistung und PV-Überschuss umschalten soll."""
    if not uses_power_setpoint(consumer):
        return False
    outputs = consumer.get("loxone_outputs") or {}
    return bool(str(outputs.get("pv_follow_name", "")).strip())


def power_limits_kw(consumer: dict) -> tuple[float, float]:
    """
    (min_kw, max_kw) für MILP und Loxone-Clamping.
    Binärmodus: min=0, max=nominal_power_kw.
    """
    max_kw = float(consumer["nominal_power_kw"])
    if not uses_power_setpoint(consumer):
        return 0.0, max_kw

    min_kw = consumer.get("min_power_kw")
    if min_kw is None:
        raise ValueError(
            f"Verbraucher '{consumer.get('id', '?')}': min_power_kw fehlt "
            "(Pflicht bei loxone_outputs.power_setpoint_name)."
        )
    min_kw = float(min_kw)
    if min_kw < 0.0:
        raise ValueError(
            f"Verbraucher '{consumer.get('id', '?')}': min_power_kw muss >= 0 sein."
        )
    if min_kw > max_kw + 1e-9:
        raise ValueError(
            f"Verbraucher '{consumer.get('id', '?')}': min_power_kw ({min_kw}) "
            f"darf nicht größer als nominal_power_kw ({max_kw}) sein."
        )
    return min_kw, max_kw


def estimate_pv_surplus_kw(matrix_row: dict, max_kw: float) -> float:
    """Stündlicher PV-Überschuss (kW) für die MILP-Planung, gedeckelt auf P_max."""
    surplus = max(
        0.0,
        float(matrix_row.get("expected_p_pv", 0.0) or 0.0)
        - float(matrix_row.get("expected_p_act", 0.0) or 0.0),
    )
    return min(float(max_kw), surplus)


def clamp_setpoint_kw(consumer: dict, power_kw: float) -> float:
    """Soll-Leistung für Loxone im Modus fester Leistung: 0 oder [min, max]."""
    min_kw, max_kw = power_limits_kw(consumer)
    power_kw = max(0.0, float(power_kw or 0.0))
    if power_kw <= 1e-3:
        return 0.0
    return round(max(min_kw, min(max_kw, power_kw)), 3)


def loxone_control_outputs(
    consumer: dict,
    planned_kw: float,
    pv_follow: int,
) -> tuple[float, int]:
    """
    Loxone-Ausgaben aus MILP-Plan (aktuelle Stunde).
    pv_follow=1: Soll = P_max, Loxone regelt live am Überschuss.
    pv_follow=0: Soll = geplante feste Leistung.
    """
    planned_kw = max(0.0, float(planned_kw or 0.0))
    if planned_kw <= 1e-3:
        return 0.0, 0
    _, max_kw = power_limits_kw(consumer)
    if int(pv_follow) == 1:
        return round(max_kw, 3), 1
    return clamp_setpoint_kw(consumer, planned_kw), 0
