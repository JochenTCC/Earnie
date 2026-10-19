"""Plausibility: Σ cons_data in the SE window vs. Jahresverbrauch of the house profile.

Fail-loud counterpart to the staleness fingerprint: even when the fingerprint matches,
the synthetic series must add up to the Jahresverbrauch the user entered, otherwise
SE scenarios start from different total loads.
"""
from __future__ import annotations

import pandas as pd

from house_config.baseload import consumer_annual_kwh, profile_baseload_kwh

BALANCE_TOLERANCE_REL = 0.03
# Per-consumer deviations below both thresholds are not worth a line in the message.
_CONSUMER_MIN_ABS_KWH = 50.0
_CONSUMER_MIN_REL = 0.10


def _window_bounds(window: tuple[pd.Timestamp, pd.Timestamp] | None):
    if window is None:
        from data.cons_data_season_mirror import wall_clock_simulation_window

        window = wall_clock_simulation_window()
    start = pd.Timestamp(window[0]).normalize()
    end = pd.Timestamp(window[1]).normalize()
    return start, end


def _consumer_rows(
    sliced: pd.DataFrame, profile: dict, scale: float
) -> list[tuple[str, float, float]]:
    """(id, cons_data kWh in window, profile kWh scaled to the window)."""
    rows: list[tuple[str, float, float]] = []
    for index, consumer in enumerate(profile.get("consumers", [])):
        cid = str(consumer.get("id") or consumer.get("label") or f"consumer_{index}")
        column = f"{cid}_kw"
        if column not in sliced.columns:
            continue
        rows.append(
            (cid, float(sliced[column].sum()), float(consumer_annual_kwh(consumer)) * scale)
        )
    return rows


def cons_data_window_balance(
    cons_df: pd.DataFrame,
    profile: dict,
    *,
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    tolerance: float = BALANCE_TOLERANCE_REL,
    mirror: bool | None = None,
) -> dict:
    """Compare Σ ``total_kw`` (hourly rows, kW == kWh) in the window with ``annual_kwh``.

    ``mirror`` (default: ``season_mirror_to_last_month`` from the config) maps cons_data
    onto the window by calendar month, exactly like the SE does.

    Returns ``{"status": "ok" | "deviation" | "incomplete", "message": str | None, ...}``.
    ``incomplete``: the window is not fully covered by cons_data (no silent partial sum).
    """
    start, end = _window_bounds(window)
    days = (end - start).days + 1
    if cons_df is None or cons_df.empty:
        return {
            "status": "incomplete",
            "message": "Keine Verbrauchsdaten vorhanden — bitte Verbrauchsdaten generieren.",
        }
    from data.cons_data_season_mirror import (
        is_season_mirror_enabled,
        season_mirror_cons_dataframe,
    )

    if is_season_mirror_enabled() if mirror is None else mirror:
        try:
            cons_df = season_mirror_cons_dataframe(
                cons_df, target_start=start, target_end=end
            )
        except ValueError as exc:
            return {"status": "incomplete", "message": str(exc)}
    stop = end + pd.Timedelta(hours=23)
    sliced = cons_df.loc[(cons_df.index >= start) & (cons_df.index <= stop)]
    expected_hours = days * 24
    if len(sliced) < expected_hours:
        return {
            "status": "incomplete",
            "message": (
                f"Verbrauchsdaten decken das Simulationsfenster {start:%Y-%m-%d} – "
                f"{end:%Y-%m-%d} nicht vollständig ab ({len(sliced)} von {expected_hours} "
                "Stunden) — bitte Verbrauchsdaten neu generieren."
            ),
        }
    annual = float(profile["annual_kwh"])
    scale = days / 365.0
    expected = annual * scale
    total = float(sliced["total_kw"].sum())
    deviation = (total - expected) / expected if expected > 0 else 0.0
    result = {
        "status": "ok",
        "message": None,
        "window": (start, end),
        "total_kwh": round(total, 1),
        "expected_kwh": round(expected, 1),
        "deviation_rel": round(deviation, 4),
    }
    if abs(deviation) <= tolerance:
        return result

    baseload_profile = profile_baseload_kwh(profile) * scale
    baseload_cons = float(sliced["baseload_kw"].sum())
    lines = []
    for cid, cons_kwh, profile_kwh in _consumer_rows(sliced, profile, scale):
        delta = cons_kwh - profile_kwh
        base = max(abs(profile_kwh), 1.0)
        if abs(delta) >= _CONSUMER_MIN_ABS_KWH and abs(delta) / base >= _CONSUMER_MIN_REL:
            lines.append(f"{cid}: {cons_kwh:.0f} statt {profile_kwh:.0f} kWh ({delta:+.0f})")
    if abs(baseload_cons - baseload_profile) >= _CONSUMER_MIN_ABS_KWH:
        lines.append(
            f"Grundlast: {baseload_cons:.0f} statt {baseload_profile:.0f} kWh "
            f"({baseload_cons - baseload_profile:+.0f})"
        )
    suggested_baseload = max(0.0, baseload_cons / scale + (expected - total) / scale)
    detail = ("; ".join(lines) + ". ") if lines else ""
    result["status"] = "deviation"
    result["suggested_baseload_kwh"] = round(suggested_baseload, 0)
    result["message"] = (
        f"Verbrauchsdaten im Simulationsfenster ({total:.0f} kWh) weichen um "
        f"{deviation:+.1%} vom Jahresverbrauch ({expected:.0f} kWh) ab. {detail}"
        "Verbrauchsdaten neu generieren; bleibt die Abweichung, Verbraucher prüfen oder "
        f"die Grundlast auf ca. {suggested_baseload:.0f} kWh/a anpassen."
    )
    return result
