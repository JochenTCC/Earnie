"""E-Auto-MILP-Moduswahl: Modus A (power_setpoint) vs. Modus B (binär, Backtesting)."""
from __future__ import annotations

from optimizer.consumer_power import power_limits_kw, uses_power_setpoint


def is_logged_day_matrix(matrix: list | None) -> bool:
    if not matrix:
        return False
    return matrix[0].get("consumption_mode") == "logged_day"


def milp_uses_power_setpoint(consumer: dict, matrix: list | None) -> bool:
    """True, wenn der MILP kontinuierliche kW-Variablen (power_setpoint) nutzt."""
    if not uses_power_setpoint(consumer):
        return False
    if is_logged_day_matrix(matrix):
        return False
    return True


def milp_binary_charge_kw(consumer: dict, matrix: list | None) -> float:
    """
    Feste kW pro Einschalt-Stunde im binären MILP-Modus.

    E-Auto Modus B (Backtesting): P_nom (max_kw).
    Übrige binäre Verbraucher: nominal_power_kw.
    """
    if consumer.get("id") == "eauto" and is_logged_day_matrix(matrix):
        _, max_kw = power_limits_kw(consumer)
        return max_kw
    return float(consumer["nominal_power_kw"])
