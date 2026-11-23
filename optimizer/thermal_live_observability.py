"""Heat-storage observability snapshots for optimization_history (split from thermal_live_store).

Shared names resolve through the ``thermal_live_store`` facade at call time (``live``), so
patches on that module stay effective.
"""
from __future__ import annotations

from typing import Any

from optimizer.thermal_coupled import heat_storage_enabled, normalize_heat_storage
from optimizer.thermal_live_cop import efficiency_observability
from optimizer.thermal_live_ref import live
from optimizer.thermal_model import capacity_kwh_per_k_from_volume, heat_content_kwh

EQ_SOURCE_MEASURED = "measured"
EQ_SOURCE_SETPOINT_NO_VALUE = "setpoint_no_value"
"""Observability ``eq_source``: T_eq had no value, the store plan started at the setpoint."""


def build_heat_storage_observability(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    house_doc: dict | None = None,
    solar_forecast_kw: list[float] | None = None,
) -> dict[str, Any] | None:
    """Snapshot for optimization_history: T_eq/T_low + Q_meas/Q_sim."""
    plan = live.plan_live_store_for_thermal_consumer(
        consumer,
        house_profile=house_profile,
        ambient_forecast_c=ambient_forecast_c,
        solar_forecast_kw=solar_forecast_kw,
        house_doc=house_doc,
    )
    if plan is None:
        return None
    thermal = consumer.get("thermal") or consumer
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        return None
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    q_meas = heat_content_kwh(plan.start_temp_c, capacity)
    q_sim = (
        float(plan.q_sim_kwh[0])
        if plan.q_sim_kwh
        else heat_content_kwh(plan.start_temp_c, capacity)
    )
    return {
        "consumer_id": consumer.get("id"),
        "kind": "heat_storage",
        "readings_c": {
            "temp_eq": plan.start_temp_c,
            "temp_low": plan.temp_low_c,
            "setpoint": plan.band.setpoint_c,
            "tolerance": plan.band.tolerance_c,
            "band_min": plan.band.min_c,
            "band_max": plan.band.max_c,
            # HeatControl P2: an Earnie charge ends at setpoint + boost.
            "boost": plan.boost_k,
            "charge_max": plan.charge_max_c,
        },
        # "backend": Live planned with the band the backend reports, not the configured one.
        "band_source": plan.band_source,
        "feedback": dict(plan.feedback),
        # HeatControl P5: JAZ or COP curve, and where the source temperature comes from.
        "efficiency": efficiency_observability(plan.efficiency, plan.jaz),
        "heat_content_kwh": {
            "q_meas": round(q_meas, 3),
            "q_sim": round(q_sim, 3),
        },
        "model": {
            "capacity_kwh_per_k": round(capacity, 4),
            "volume_liters": float(storage["volume_liters"]),
            "heat_loss_kw_per_k": float(storage["heat_loss_kw_per_k"]),
        },
        "used_measured_eq": plan.used_measured_eq,
        # Start of the store plan: the measured T_eq, or the setpoint when T_eq has no value.
        "eq_source": EQ_SOURCE_MEASURED if plan.used_measured_eq else EQ_SOURCE_SETPOINT_NO_VALUE,
        "used_measured_low": plan.used_measured_low,
        "collector_solar_source": plan.solar_source,
        "horizon_q_sim_kwh": [round(v, 3) for v in plan.q_sim_kwh],
    }


def collect_heat_storage_observability(
    consumers: list[dict],
    *,
    house_profile: dict,
    horizon: int = 24,
    house_doc: dict | None = None,
) -> list[dict[str, Any]]:
    """Observability for thermal_annual consumers with active heat_storage."""
    results: list[dict[str, Any]] = []
    ambient_forecast: list[float] | None = None
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if consumer.get("type") != "thermal_annual":
            continue
        thermal = consumer.get("thermal") or consumer
        if not heat_storage_enabled(thermal.get("heat_storage")):
            continue
        cid = consumer.get("id") or "?"
        try:
            # Only with a store; a missing outdoor temperature is this item's error.
            if ambient_forecast is None:
                ambient_forecast = live._live_ambient_forecast(
                    max(1, int(horizon)), house_doc=house_doc
                )
            item = live.build_heat_storage_observability(
                consumer,
                house_profile=house_profile,
                ambient_forecast_c=ambient_forecast,
                house_doc=house_doc,
            )
            if item is not None:
                results.append(item)
        except Exception as exc:
            results.append(
                {
                    "consumer_id": cid,
                    "kind": "heat_storage",
                    "error": str(exc),
                }
            )
    return results
