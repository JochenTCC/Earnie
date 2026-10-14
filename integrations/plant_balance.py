"""Topology P2: generator-side coverage and derived house-load balance."""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from ehal.ess_fields import ess_field
from house_config.powerstation import BATTERY_TYPE_HOUSE
from integrations.pv_attribution import (
    grid_tied_inverters_with_pv,
    plant_pv_derive_coverage_complete,
)
from optimizer.milp_inverter import filter_house_balance_batteries

logger = logging.getLogger(__name__)

DEFAULT_BALANCE_TOLERANCE_PCT = 5.0
DEFAULT_BALANCE_TOLERANCE_W = 100.0

ReadEssPowerW = Callable[[str], float | None]


def balance_tolerances_from_plant(
    plant: Mapping[str, Any] | None,
) -> tuple[float, float]:
    """Return (pct, w) from plant or Topology P2 defaults."""
    raw = plant if isinstance(plant, Mapping) else {}
    pct = raw.get("balance_tolerance_pct")
    watts = raw.get("balance_tolerance_w")
    try:
        pct_f = (
            float(pct)
            if pct is not None and pct != ""
            else DEFAULT_BALANCE_TOLERANCE_PCT
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"plant.balance_tolerance_pct ungültig: {pct!r}."
        ) from exc
    try:
        w_f = (
            float(watts)
            if watts is not None and watts != ""
            else DEFAULT_BALANCE_TOLERANCE_W
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"plant.balance_tolerance_w ungültig: {watts!r}."
        ) from exc
    if pct_f < 0.0:
        raise ValueError("plant.balance_tolerance_pct muss >= 0 sein.")
    if w_f < 0.0:
        raise ValueError("plant.balance_tolerance_w muss >= 0 sein.")
    return pct_f, w_f


def pv_covers_all_inverters_from_plant(plant: Mapping[str, Any] | None) -> bool:
    raw = plant if isinstance(plant, Mapping) else {}
    return bool(raw.get("pv_covers_all_inverters"))


def grid_tied_house_batteries(
    batteries: list[dict],
    inverters: list[dict],
) -> list[dict]:
    """House batteries that participate in the house AC balance."""
    house = [
        bat
        for bat in batteries
        if isinstance(bat, dict)
        and str(bat.get("type") or BATTERY_TYPE_HOUSE).strip().lower()
        == BATTERY_TYPE_HOUSE
    ]
    return filter_house_balance_batteries(house, inverters)


def sum_grid_tied_house_ess_power_w(
    *,
    batteries: list[dict],
    inverters: list[dict],
    read_power_w: ReadEssPowerW,
) -> float:
    """Plant ``sens_ess_power`` = Σ grid-tied house ``ess.{id}.sens_ess_power``.

    Zero eligible batteries → ``0.0``. Missing binding/value for any eligible
    battery fails loud (same pattern as plant PV derive).
    """
    eligible = grid_tied_house_batteries(batteries, inverters)
    if not eligible:
        return 0.0
    total = 0.0
    missing: list[str] = []
    for bat in eligible:
        bid = str(bat.get("id") or "").strip()
        if not bid:
            missing.append("?")
            continue
        value = read_power_w(bid)
        if value is None:
            missing.append(bid)
            continue
        total += float(value)
    if missing:
        fields = ", ".join(ess_field(bid, "sens_ess_power") for bid in missing)
        raise ValueError(
            "Cannot derive plant sens_ess_power: incomplete grid-tied house "
            f"ESS power coverage (missing: {fields}). Map "
            "ess.{id}.sens_ess_power for every grid-tied house battery."
        )
    return total


def derive_sens_power_consumers_w(
    telemetry: dict[str, Any],
    *,
    tolerance_pct: float = DEFAULT_BALANCE_TOLERANCE_PCT,
    tolerance_w: float = DEFAULT_BALANCE_TOLERANCE_W,
) -> float:
    """House load W: mapped value if present, else PV + grid + ESS with tolerance.

    EHAL signs: grid ``+`` = import, ESS ``+`` = discharge.
    Raw balance below ``-max(w, pct/100 · P_PV)`` is a telemetry error, not ``0``.
    """
    mapped = telemetry.get("sens_power_consumers")
    if mapped is not None:
        return max(0.0, float(mapped))
    pv = float(telemetry["sens_pv_production_active"])
    grid = float(telemetry["sens_grid_power_active"])
    # Battery-less plants may omit ESS (→ 0). Plants with grid-tied house
    # batteries must set sens_ess_power via sum_grid_tied_house_ess_power_w.
    ess = float(telemetry.get("sens_ess_power") or 0.0)
    raw = pv + grid + ess
    floor = -max(float(tolerance_w), float(tolerance_pct) / 100.0 * pv)
    if raw < floor:
        raise ValueError(
            "House balance telemetry error: derived load "
            f"{raw:.1f} W is below floor {floor:.1f} W "
            f"(tolerance_pct={tolerance_pct}, tolerance_w={tolerance_w}, "
            f"P_PV={pv:.1f} W)."
        )
    if raw < 0.0:
        return 0.0
    return raw


def assert_mapped_plant_pv_coverage(
    *,
    inverters: list[dict],
    pv_systems: list[dict],
    scoped_live: dict[str, Any] | None = None,
    pv_covers_all_inverters: bool = False,
) -> None:
    """When plant PV is mapped and several grid-tied inverters own PV, require coverage or ack."""
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if len(eligible) <= 1:
        return
    if plant_pv_derive_coverage_complete(
        inverters, pv_systems, scoped_live=scoped_live
    ):
        return
    if pv_covers_all_inverters:
        logger.info(
            "plant.pv_covers_all_inverters=true: accepting mapped plant PV "
            "without complete inv/pv coverage (%s grid-tied inverters with PV).",
            len(eligible),
        )
        return
    ids = ", ".join(
        str(inv.get("id") or "?").strip() or "?" for inv in eligible
    )
    raise ValueError(
        "Mapped plant sens_pv_production_active with multiple grid-tied "
        f"inverters owning PV requires complete inv.*/pv.* coverage or "
        f"plant.pv_covers_all_inverters=true (inverters: {ids})."
    )
