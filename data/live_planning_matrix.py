"""Live planning matrix assembly helpers (extracted from profile_manager)."""
from __future__ import annotations

import logging

from data import market_prices
from data import pv_forecast
from data.price_forecast_live import is_extrapolated_source

logger = logging.getLogger(__name__)


def assemble_live_planning_rows(
    market_data: list,
    target_hours: list,
) -> tuple[list, dict[str, list[float]]]:
    """Load forecast vectors and build the optimization matrix with flex columns."""
    from data.profile_manager import (
        _build_optimization_matrix,
        _load_consumption_profile,
        _load_flexible_consumer_hourly_profiles,
        _load_total_consumption_profile,
    )

    logger.info("Matrix-Aufbau: Grundlast-Profil laden …")
    forecast_consumption = _load_consumption_profile(target_hours)
    logger.info("Matrix-Aufbau: Gesamtverbrauchs-Profil laden …")
    forecast_total = _load_total_consumption_profile(target_hours)
    logger.info("Matrix-Aufbau: Flexible Verbraucher-Profile laden …")
    flex_profiles = _load_flexible_consumer_hourly_profiles(target_hours)
    logger.info("Matrix-Aufbau: PV-Prognose laden …")
    forecast_pv = pv_forecast.get_hourly_pv_forecast_for_hours(target_hours)
    logger.info("Matrix-Aufbau: Optimierungsmatrix zusammenstellen …")
    optimization_matrix = _build_optimization_matrix(
        market_data,
        forecast_consumption,
        forecast_pv,
        forecast_total_consumption=forecast_total,
        target_hours=target_hours,
    )
    for i, row in enumerate(optimization_matrix):
        row["expected_flex_kw"] = {
            cid: flex_profiles[cid][i]
            for cid in flex_profiles
        }
    return optimization_matrix, flex_profiles


def log_live_flex_horizon(flex_profiles: dict[str, list[float]]) -> None:
    flex_horizon_sums = {
        cid: round(sum(values), 2)
        for cid, values in flex_profiles.items()
        if round(sum(values), 2) > 0.0
    }
    if flex_horizon_sums:
        logger.info(
            "Flex-Profile im Planungshorizont (kWh): %s",
            ", ".join(f"{cid}={kwh}" for cid, kwh in sorted(flex_horizon_sums.items())),
        )
    else:
        logger.warning(
            "Flex-Profile im Planungshorizont sind leer — SoC BL Ziel kann zu hoch sein."
        )


def warn_live_matrix_price_extrapolation(optimization_matrix: list) -> None:
    mirrored_share = market_prices.mirrored_price_share(
        [
            {
                "price_source": row.get("price_source"),
            }
            for row in optimization_matrix
        ]
    )
    extrapolated_share = sum(
        1 for row in optimization_matrix if is_extrapolated_source(row.get("price_source"))
    ) / len(optimization_matrix)
    if extrapolated_share > 0.2:
        print(
            f"[WARN] Preis-Extrapolation: {extrapolated_share:.0%} der {len(optimization_matrix)} "
            "Planungs-Slots ohne Day-Ahead-Preis "
            f"(gespiegelt: {mirrored_share:.0%})."
        )
