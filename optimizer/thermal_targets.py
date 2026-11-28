"""Thermisches Ziel (Phase 0: Observability) für flexible Verbraucher."""
from __future__ import annotations

import logging
from typing import Any

import config
from data.outdoor_forecast import get_outdoor_forecast_with_fallback
from data.thermal_power import resolve_live_heating_power_kw
from integrations import ehal_live
from optimizer.slot_duration import wall_hours_from_slots
from optimizer.thermal_model import (
    ThermalBand,
    capacity_kwh_per_k_from_volume,
    plan_minimum_heating,
)

logger = logging.getLogger(__name__)


def thermal_horizon_hours_from_slots(n_slots: int, *, dt_h: float | None = None) -> int:
    """Hourly RC-model horizon from a QH (or other) planning-matrix length.

    ``plan_minimum_heating`` steps one hour at a time. Passing slot count
    (e.g. 162 QH) as ``horizon`` overstates cooling by ~1/dt_h.
    """
    if n_slots <= 0:
        return 24
    return max(1, wall_hours_from_slots(n_slots, dt_h))


def _resolve_band(thermal: dict, readings: dict) -> ThermalBand:
    setpoint = readings.get("setpoint_c")
    if setpoint is None:
        setpoint = thermal.get("setpoint_c")
    tolerance = readings.get("tolerance_c")
    if tolerance is None:
        tolerance = thermal.get("tolerance_c")
    if setpoint is None:
        raise ValueError("Solltemperatur fehlt (Loxone und Config-Fallback).")
    if tolerance is None:
        raise ValueError("Temperatur-Toleranz fehlt (Loxone und Config-Fallback).")
    tolerance = float(tolerance)
    if tolerance < 0:
        raise ValueError("Temperatur-Toleranz muss >= 0 sein.")
    return ThermalBand(setpoint_c=float(setpoint), tolerance_c=tolerance)


def _resolve_heat_loss(thermal: dict) -> float:
    configured = thermal.get("heat_loss_kw_per_k")
    if configured is None:
        raise ValueError(
            "heat_loss_kw_per_k fehlt – zuerst "
            "'python -m scripts.tune_thermal_model' ausführen und Wert im Hausprofil eintragen."
        )
    configured = float(configured)
    if configured < 0:
        raise ValueError("heat_loss_kw_per_k muss >= 0 sein.")
    return configured


def _resolve_subtracted_filter_kw(consumer: dict) -> float:
    subtract_ids = (consumer.get("loxone_inputs") or {}).get("subtract_consumer_ids") or []
    if not subtract_ids:
        return 0.0
    total = 0.0
    for sub_id in subtract_ids:
        sub = next(
            (c for c in config.get_flexible_consumers() if c.get("id") == sub_id),
            None,
        )
        if sub is None:
            continue
        measured = ehal_live.read_consumer_meter_kw(sub)
        if measured is not None:
            total += float(measured)
    return total


def _build_thermal_plan(consumer: dict, *, horizon: int = 24):
    """Liefert ThermalPlanResult oder wirft bei fehlenden Live-Daten.

    Built once per Live cycle (``optimizer.live_cycle_scope``): the horizon target and the
    MILP store level of the same cycle share one set of readings and one forecast.
    """
    from optimizer.live_cycle_scope import cycle_memo
    from optimizer.thermal_year_cache import fingerprint_json

    key = ("thermal_rc_plan", fingerprint_json(consumer), int(horizon))
    return cycle_memo(key, lambda: _compute_thermal_plan(consumer, horizon=horizon))


def _compute_thermal_plan(consumer: dict, *, horizon: int):
    thermal = consumer.get("thermal_control")
    if not thermal or not thermal.get("enabled"):
        raise ValueError(f"Verbraucher '{consumer.get('id')}' hat kein aktives thermal_control.")

    readings = ehal_live.fetch_thermal_readings(consumer)
    if readings.get("actual_c") is None:
        raise ValueError("Ist-Temperatur konnte nicht gelesen werden.")

    band = _resolve_band(thermal, readings)
    heat_loss_kw_per_k = _resolve_heat_loss(thermal)
    capacity = capacity_kwh_per_k_from_volume(thermal["water_volume_liters"])
    ambient_live = readings.get("ambient_c")
    if ambient_live is None:
        raise ValueError(
            "Außentemperatur (Live) fehlt – sens_temperature_outside / ambient Merker prüfen."
        )

    ambient_forecast, ambient_source = get_outdoor_forecast_with_fallback(
        horizon=horizon,
        fallback_ambient_c=float(ambient_live),
    )
    plan = plan_minimum_heating(
        start_temp_c=float(readings["actual_c"]),
        ambient_forecast_c=ambient_forecast,
        band=band,
        heat_power_kw=float(consumer["nominal_power_kw"]),
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        heating_efficiency=float(thermal["heating_efficiency"]),
        extra_heat_paths=thermal.get("heat_paths"),
    )
    return plan, band, readings, ambient_forecast, ambient_source, capacity, heat_loss_kw_per_k


def resolve_thermal_daily_target_kwh(consumer: dict, *, horizon: int = 24) -> float:
    """Mindest-Heizenergie (kWh) über den Horizont, damit das Band gehalten wird."""
    if horizon < 1:
        raise ValueError("horizon muss mindestens 1 sein.")
    thermal = consumer.get("thermal_control") or {}
    if not thermal.get("enabled"):
        raise ValueError(
            f"Verbraucher '{consumer.get('id')}': daily_target_source=thermal "
            "erfordert thermal_control.enabled=true."
        )
    if thermal.get("mode") != "active":
        raise ValueError(
            f"Verbraucher '{consumer.get('id')}': daily_target_source=thermal "
            "erfordert thermal_control.mode=active."
        )
    plan, *_ = _build_thermal_plan(consumer, horizon=horizon)
    return float(plan.required_kwh)


def _slot_hours(matrix: list) -> list[int]:
    """Hour of the RC forecast (0 = the plan's first hour) for each matrix slot."""
    from optimizer.charging_schedule import matrix_slot_datetime

    start = matrix_slot_datetime(matrix, 0)
    return [
        int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        for index in range(len(matrix))
    ]


def thermal_rc_horizon_hours(matrix: list) -> int:
    """RC forecast hours for a matrix: its slot count, and at least every hour a slot touches.

    A Live matrix starting at :15 / :30 / :45 reaches one wall hour more than its slot count
    says; the RC target and the Live store need the same hours (one memoized plan per cycle).
    """
    if not matrix:
        return thermal_horizon_hours_from_slots(0)
    return max(thermal_horizon_hours_from_slots(len(matrix)), _slot_hours(matrix)[-1] + 1)


def thermal_rc_live_store(consumer: dict, matrix: list, dt_h: float):
    """Live store level of a ``thermal_rc`` consumer (pool / SwimSpa) over the matrix.

    Same RC model as ``plan_minimum_heating`` (same readings and forecast in a Live cycle),
    written as the linear store level of ``optimizer.thermal_store_model``: the level is the
    heat above the band minimum, ``x = C · (T − T_min)``, the band is ``[0, C · (T_max −
    T_min)]``. The loss ``H · (T − T_amb)`` splits into the leak ``H · Δt / C`` of the level
    and the drain ``H · Δt · (T_min − T_amb)`` per slot, so the plan may heat in any slot of
    the horizon as long as the water stays in the band (no calendar-day window).
    """
    from optimizer.thermal_store_model import StoreLevelModel

    if not matrix:
        raise ValueError("thermal_rc Live-Speicher: leere Planungsmatrix.")
    horizon = thermal_rc_horizon_hours(matrix)
    _plan, band, readings, ambient_forecast, _src, capacity, heat_loss = _build_thermal_plan(
        consumer, horizon=horizon
    )
    thermal = consumer.get("thermal_control") or {}
    leak_kw_per_k = float(heat_loss)
    fixed_paths: list[tuple[float, float]] = []
    for path in thermal.get("heat_paths") or []:
        coeff = float(path.get("heat_loss_kw_per_k", 0.0) or 0.0)
        if coeff <= 0:
            continue
        if str(path.get("reference", "ambient")).strip().lower() == "fixed":
            if path.get("reference_temp_c") is None:
                raise ValueError(
                    f"thermal_rc '{consumer.get('id')}': Wärmepfad mit reference=fixed "
                    "braucht reference_temp_c."
                )
            fixed_paths.append((coeff, float(path["reference_temp_c"])))
        else:
            leak_kw_per_k += coeff
    hours = _slot_hours(matrix)
    if hours[-1] >= len(ambient_forecast):
        raise ValueError(
            f"thermal_rc Live-Speicher '{consumer.get('id')}': Außentemperatur-Prognose "
            f"({len(ambient_forecast)} h) deckt den Horizont ({hours[-1] + 1} h) nicht ab."
        )
    fixed_loss_at_min_kw = sum(coeff * (band.min_c - ref) for coeff, ref in fixed_paths)
    drain = [
        float(dt_h)
        * (
            leak_kw_per_k * (band.min_c - float(ambient_forecast[hour]))
            + fixed_loss_at_min_kw
        )
        for hour in hours
    ]
    leak_kw_per_k += sum(coeff for coeff, _ref in fixed_paths)
    return StoreLevelModel(
        capacity_kwh=float(capacity) * (band.max_c - band.min_c),
        start_kwh=float(capacity) * (float(readings["actual_c"]) - band.min_c),
        efficiency=float(thermal["heating_efficiency"]),
        drain_kwh=drain,
        leak_per_slot=float(dt_h) * leak_kw_per_k / float(capacity),
    )


def build_thermal_observability(
    consumer: dict,
    *,
    active_target_kwh: float | None = None,
    baseline_target_kwh: float | None = None,
    horizon: int = 24,
) -> dict[str, Any]:
    """
    Berechnet thermisches Mindest-Ziel und Vergleich zum Referenz-Tagesziel.
    mode=active: active_target_kwh = thermal_target; baseline optional (historical).
    """
    plan, band, readings, ambient_forecast, ambient_source, capacity, heat_loss_kw_per_k = (
        _build_thermal_plan(consumer, horizon=horizon)
    )
    thermal = consumer.get("thermal_control") or {}

    thermal_target = round(float(plan.required_kwh), 3)
    if thermal.get("mode") == "active":
        reference = thermal_target
        if baseline_target_kwh is not None:
            delta = round(thermal_target - float(baseline_target_kwh), 3)
        else:
            delta = 0.0
    else:
        reference = round(float(active_target_kwh or 0.0), 3)
        delta = round(thermal_target - reference, 3)
    snapshot: dict[str, Any] = {
        "consumer_id": consumer["id"],
        "mode": thermal.get("mode", "observe"),
        "readings_c": {
            "actual": readings.get("actual_c"),
            "setpoint": band.setpoint_c,
            "tolerance": band.tolerance_c,
            "ambient_live": readings.get("ambient_c"),
            "band_min": band.min_c,
            "band_max": band.max_c,
        },
        "active_target_kwh": reference,
        "thermal_target_kwh": thermal_target,
        "delta_kwh": delta,
        "heating_hours": plan.heating_hours,
        "heating_schedule": plan.heating_schedule,
        "ambient_forecast_source": ambient_source,
        "ambient_forecast_c": ambient_forecast,
        "forecast_temp_with_heat_c": plan.forecast_temp_c,
        "forecast_temp_no_heat_c": plan.forecast_temp_no_heat_c,
        "model": {
            "capacity_kwh_per_k": round(capacity, 4),
            "heat_loss_kw_per_k": round(heat_loss_kw_per_k, 5),
            "heating_efficiency": thermal["heating_efficiency"],
            "heat_power_kw": consumer["nominal_power_kw"],
        },
    }
    if baseline_target_kwh is not None:
        snapshot["baseline_target_kwh"] = round(float(baseline_target_kwh), 3)
    if readings.get("missing_signals"):
        snapshot["missing_signals"] = readings["missing_signals"]
    if readings.get("heating_active") is not None:
        _attach_live_heating_readings(snapshot, consumer, readings)
    _attach_heat_content(snapshot, plan, band, readings.get("actual_c"), capacity)
    return snapshot


def _attach_live_heating_readings(
    snapshot: dict[str, Any], consumer: dict, readings: dict
) -> None:
    """Add ``heating_active`` and, when derivable, live total/heating kW."""
    snapshot["readings_c"]["heating_active"] = readings["heating_active"]
    total_kw = ehal_live.read_consumer_meter_kw(consumer)
    heating_kw = resolve_live_heating_power_kw(
        total_kw=total_kw,
        filter_kw=_resolve_subtracted_filter_kw(consumer),
        heating_active=readings["heating_active"],
    )
    if heating_kw is not None:
        snapshot["readings_kw"] = {
            "total": total_kw,
            "heating": heating_kw,
        }


def _attach_heat_content(
    snapshot: dict[str, Any], plan, band, actual_c: float | None, capacity: float
) -> None:
    """Add measured/simulated heat content and the simulated horizon profile."""
    from optimizer.thermal_model import heat_content_kwh

    q_meas = (
        round(heat_content_kwh(float(actual_c), capacity), 3)
        if actual_c is not None
        else None
    )
    forecast = plan.forecast_temp_c or []
    q_sim_temp = float(forecast[0]) if forecast else float(actual_c or band.setpoint_c)
    snapshot["heat_content_kwh"] = {
        "q_meas": q_meas,
        "q_sim": round(heat_content_kwh(q_sim_temp, capacity), 3),
    }
    snapshot["horizon_q_sim_kwh"] = [
        round(heat_content_kwh(float(temp_c), capacity), 3) for temp_c in forecast
    ]


def collect_thermal_observability(
    consumers: list[dict],
    *,
    active_targets_kwh: dict[str, float],
    baseline_targets_kwh: dict[str, float] | None = None,
    horizon: int = 24,
) -> list[dict[str, Any]]:
    """Observability für alle Verbraucher mit thermal_control.enabled."""
    baselines = baseline_targets_kwh or {}
    results: list[dict[str, Any]] = []
    for consumer in consumers:
        thermal = consumer.get("thermal_control")
        if not thermal or not thermal.get("enabled"):
            continue
        cid = consumer["id"]
        baseline = baselines.get(cid)
        try:
            results.append(
                build_thermal_observability(
                    consumer,
                    active_target_kwh=float(active_targets_kwh.get(cid, 0.0)),
                    baseline_target_kwh=baseline,
                    horizon=horizon,
                )
            )
        except Exception as exc:
            logger.warning(
                "Thermische Observability für '%s' fehlgeschlagen: %s",
                cid,
                exc,
            )
            results.append({
                "consumer_id": cid,
                "mode": thermal.get("mode", "observe"),
                "error": str(exc),
            })
    return results
