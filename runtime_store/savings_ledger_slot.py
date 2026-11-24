"""Savings ledger: slot engine (one closed slot vs. the shadow plant) and the day replay.

Split from ``runtime_store.savings_ledger`` (KPI refactor); that module re-exports these
names. Sign conventions and spec references: see ``runtime_store.savings_ledger``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.live_consumption import is_dead_telemetry_snapshot
from optimizer import battery as bat
from optimizer.milp_horizon import (
    coerce_battery_params_list,
    plant_battery_params,
    plant_soc_percent,
)
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from runtime_store.power_interval_sampler import MIN_SAMPLE_COUNT_FOR_MEAN


# 3 (decided 2026-11-19, maintainer): v2 with the plant battery over all house batteries in the
# shadow plant (spec § 3, § 9 item 15). Houses with one battery book the same as v2, but every
# chain restarts once.
# 4 (decided 2026-11-24, maintainer): the shadow plant runs the plan battery's limits of each
# slot's cycle (live charge/discharge limits, virtual reserve floor; spec § 3, § 9 item 16),
# as the cycle's baselines do. Every chain restarts once.
SAVINGS_V = 4


# First version with the day replay (flex re-timing, spec § 7); ``SAVINGS_V`` reaches it in Ledger P9d.
SAVINGS_V_REPLAY = 2


# Sources a slot may have per plant channel (spec § 4): energy counters exist for pv and grid only.
_SOURCE_MEAN = "mean"


_SOURCE_COUNTER = "counter"


_MEAN_OR_COUNTER_CHANNELS = ("pv", "grid")


_MEAN_ONLY_CHANNELS = ("battery", "house")


_REQUIRED_POWER_KEYS = ("pv_kw", "grid_kw", "house_kw")


SKIP_MISSING = "missing"


SKIP_FEW_SAMPLES = "few_samples"


SKIP_NOT_MEAN = "not_mean"


SKIP_NO_POWER = "no_power"


SKIP_NO_PRICE = "no_price"


SKIP_DEAD_TELEMETRY = "dead_telemetry"


SKIP_ERROR = "error"


# Slots of the day that were never booked (counted only at the day close, spec § 4).
SKIP_BEFORE_CHAIN = "before_chain"


SKIP_NO_CYCLE = "no_cycle"


@dataclass(frozen=True)
class LedgerSlot:
    """Result of one closed slot. A skipped slot leaves both sides and the shadow SoC unchanged."""

    counted: bool
    skip_reason: str | None
    cost_with_eur: float
    cost_without_eur: float
    shadow_soc_next: float | None
    import_kwh_with: float
    import_kwh_without: float
    export_kwh_with: float
    export_kwh_without: float
    shadow_battery_kw: float

    @property
    def saving_eur(self) -> float:
        return self.cost_without_eur - self.cost_with_eur


def _has_counter_source(closed: dict[str, Any]) -> bool:
    sources = closed["ist_power_source"]
    return any(sources[channel] == _SOURCE_COUNTER for channel in _MEAN_OR_COUNTER_CHANNELS)


def _sources_allowed(sources: Any) -> bool:
    if not isinstance(sources, dict):
        return False
    return all(
        sources.get(channel) in (_SOURCE_MEAN, _SOURCE_COUNTER)
        for channel in _MEAN_OR_COUNTER_CHANNELS
    ) and all(sources.get(channel) == _SOURCE_MEAN for channel in _MEAN_ONLY_CHANNELS)


def ledger_house_kw(closed: dict[str, Any]) -> float:
    """House load the ledger books for a counted slot (spec § 4).

    All means: the logged ``house_kw``. With an energy counter on pv or grid the logged
    value is a sample mean that no longer fits the counter deltas, and the shadow
    plant would see another load than the real one. The balance
    ``pv + grid + battery`` keeps the load equal on both sides.
    """
    if _has_counter_source(closed):
        return float(closed["pv_kw"]) + float(closed["grid_kw"]) + float(closed["battery_kw"])
    return float(closed["house_kw"])


def slot_skip_reason(closed: dict[str, Any] | None) -> str | None:
    """Why a ``closed_interval`` does not count, or ``None`` when it does.

    A slot counts when it is present, has at least ``MIN_SAMPLE_COUNT_FOR_MEAN``
    samples (same bar as "Ist bisher"), pv and grid are slot means or energy
    counters, battery and house are slot means, and the powers the slot needs are
    present (``battery_kw`` too with a counter, see ``ledger_house_kw``). A slot whose
    plant powers all read exactly zero is a meter outage (``is_dead_telemetry_snapshot``,
    as the history chart treats it) and does not count either.
    """
    if not isinstance(closed, dict) or not closed:
        return SKIP_MISSING
    try:
        samples = int(closed.get("sample_count") or 0)
    except (TypeError, ValueError):
        return SKIP_FEW_SAMPLES
    if samples < MIN_SAMPLE_COUNT_FOR_MEAN:
        return SKIP_FEW_SAMPLES
    if not _sources_allowed(closed.get("ist_power_source")):
        return SKIP_NOT_MEAN
    required = _REQUIRED_POWER_KEYS
    if _has_counter_source(closed):
        required = (*_REQUIRED_POWER_KEYS, "battery_kw")
    for key in required:
        value = closed.get(key)
        if value is None or isinstance(value, bool):
            return SKIP_NO_POWER
        try:
            float(value)
        except (TypeError, ValueError):
            return SKIP_NO_POWER
    if is_dead_telemetry_snapshot(closed):
        return SKIP_DEAD_TELEMETRY
    return None


def shadow_battery_params(battery_params: dict | list[dict] | None) -> dict:
    """Battery the shadow plant runs: one ESS as is; several as the plant battery of the
    optimized run and the baselines (``plant_battery_params``; spec § 3).

    ``battery_params`` are the house-balance batteries
    (``optimizer.sim_horizon_chart_soc.house_balance_batteries``); the caller filters them,
    because this module reads no config.
    """
    batteries = coerce_battery_params_list(battery_params)
    if not batteries:
        raise ValueError("savings ledger: no house battery parameters for the shadow plant")
    if len(batteries) == 1:
        return batteries[0]
    return plant_battery_params(batteries)


_SOC_EDGES = ("start", "end")


def with_plant_soc(closed: dict[str, Any] | None, batteries: list[dict]) -> dict[str, Any] | None:
    """``closed`` with ``soc_start_percent`` / ``soc_end_percent`` of the plant battery.

    The sampler logs the SoC of the first house battery there. With one house battery that is
    the plant's and ``closed`` is returned as is. With several (``batteries``: the
    house-balance batteries) the plant SoC is the energy-weighted SoC of the battery maps
    ``soc_<edge>_percent_by_ess``. When a map is missing or lacks a battery, the plant SoC of
    that edge is unknown and the key is removed: the ledger treats the slot as one without
    SoC (a chain start waits for the next slot, the day close carries the correction).
    """
    if not isinstance(closed, dict) or len(batteries) < 2:
        return closed
    out = dict(closed)
    for edge in _SOC_EDGES:
        key = f"soc_{edge}_percent"
        by_ess = closed.get(f"{key}_by_ess")
        out.pop(key, None)
        if not isinstance(by_ess, dict):
            continue
        try:
            soc = plant_soc_percent(batteries, {str(k): float(v) for k, v in by_ess.items()})
        except ValueError:
            continue
        out[key] = round(soc, 2)
    return out


def _cost_eur(grid_kwh: float, k_act_cent: float, k_push_cent: float) -> float:
    if grid_kwh >= 0.0:
        return grid_kwh * k_act_cent / 100.0
    return grid_kwh * k_push_cent / 100.0


def _shadow_step(
    pv_kw: float,
    house_kw: float,
    shadow_soc: float | None,
    battery_params: dict | None,
    dt: float,
    limits: dict[str, float] | None = None,
) -> tuple[float | None, float, float]:
    """``(soc_next, battery_kw, grid_kwh)`` of the shadow plant in one slot.

    With a battery: vendor mode on the load plus standby, under ``limits``: the plan
    battery's limits of the slot's cycle (``shadow_battery_limits`` of its log entry; v4,
    spec § 3). ``None``: a log entry from before v4, the configured battery's own limits.
    Without a battery (v2, spec § 7): ``grid = load - pv`` and no SoC. The causal step and
    the day replay share this function, so a replay on the logged timing gives the causal
    slots to the bit.
    """
    from optimizer.sim_baseline import limited_vendor_step

    if battery_params is None:
        return None, 0.0, (house_kw - pv_kw) * dt
    params = {**battery_params, **limits} if limits else battery_params
    load_kw = house_kw + bat.standby_power_kw(params)
    soc_next, batt_kw = limited_vendor_step(float(shadow_soc), pv_kw - load_kw, params, dt_h=dt)
    grid_shadow_kw = load_kw - pv_kw + batt_kw
    return soc_next, batt_kw, grid_shadow_kw * dt


def advance_slot(
    closed: dict[str, Any] | None,
    shadow_soc: float | None,
    battery_params: dict | None,
    *,
    k_act_cent: float,
    k_push_cent: float,
    dt_h: float = DEFAULT_DT_H,
    shadow_limits: dict[str, float] | None = None,
) -> LedgerSlot:
    """Price one closed slot with and without Earnie and step the shadow battery.

    ``battery_params`` is the shadow battery (``shadow_battery_params``); ``None`` (with
    ``shadow_soc`` ``None``) is a house without battery, v2 only. ``shadow_limits``: the
    plan battery's limits of the slot's cycle (``_shadow_step``).
    ``k_act_cent`` / ``k_push_cent`` are the buy and sell prices of that slot's
    cycle. A slot that does not count (``slot_skip_reason``) is skipped on both
    sides: zero cost, shadow SoC unchanged, ``skip_reason`` set.
    """
    dt = validate_dt_h(dt_h)
    reason = slot_skip_reason(closed)
    if reason is not None:
        return LedgerSlot(
            counted=False,
            skip_reason=reason,
            cost_with_eur=0.0,
            cost_without_eur=0.0,
            shadow_soc_next=shadow_soc,
            import_kwh_with=0.0,
            import_kwh_without=0.0,
            export_kwh_with=0.0,
            export_kwh_without=0.0,
            shadow_battery_kw=0.0,
        )
    assert closed is not None
    pv_kw = float(closed["pv_kw"])
    house_kw = ledger_house_kw(closed)
    grid_kw = float(closed["grid_kw"])
    soc_next, batt_kw, grid_shadow_kwh = _shadow_step(
        pv_kw, house_kw, shadow_soc, battery_params, dt, shadow_limits
    )
    grid_kwh = grid_kw * dt
    k_act = float(k_act_cent)
    k_push = float(k_push_cent)
    return LedgerSlot(
        counted=True,
        skip_reason=None,
        cost_with_eur=_cost_eur(grid_kwh, k_act, k_push),
        cost_without_eur=_cost_eur(grid_shadow_kwh, k_act, k_push),
        shadow_soc_next=soc_next,
        import_kwh_with=max(grid_kwh, 0.0),
        import_kwh_without=max(grid_shadow_kwh, 0.0),
        export_kwh_with=max(-grid_kwh, 0.0),
        export_kwh_without=max(-grid_shadow_kwh, 0.0),
        shadow_battery_kw=batt_kw,
    )


def _delivered_kw(row: dict[str, Any], dt_h: float) -> dict[str, float]:
    return {cid: float(kwh) / dt_h for cid, kwh in (row.get("flex_delivered_kwh") or {}).items()}


def replay_day(
    slots: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    start_soc: float | None,
    battery_params: dict | None,
    flex_retimed_kw: list[dict[str, float]] | None,
    *,
    dt_h: float,
    fuel_eur_per_slot: list[float] | None = None,
) -> tuple[tuple[dict[str, Any], ...], float | None]:
    """Shadow plant over one day's slot rows from ``start_soc``; returns the replayed rows and the end SoC.

    ``flex_retimed_kw`` (one dict per row, kW per consumer) replaces each consumer's delivered
    power: ``house_without = house + sum(retimed - delivered)`` per counted slot (plan § 1).
    ``None`` keeps the logged timing, which gives the causal slots to the bit.
    ``fuel_eur_per_slot`` adds the fuel the shadow plant buys for a rod's heat to that slot's
    ``cost_without_eur`` (plan § 4.4), so the slots still add up to the row. Skipped rows stay
    zero and keep the SoC. A counted row without ``house_kwh``, ``pv_kwh`` or the prices raises
    ``KeyError`` (a row from before Ledger P9b; v2 starts a new chain, so none reaches here).
    """
    if flex_retimed_kw is not None and len(flex_retimed_kw) != len(slots):
        raise ValueError(f"savings ledger replay: {len(flex_retimed_kw)} flex rows for {len(slots)} slots")
    if fuel_eur_per_slot is not None and len(fuel_eur_per_slot) != len(slots):
        raise ValueError(f"savings ledger replay: {len(fuel_eur_per_slot)} fuel values for {len(slots)} slots")
    dt = validate_dt_h(dt_h)
    soc = start_soc
    out: list[dict[str, Any]] = []
    for index, row in enumerate(slots):
        replayed = dict(row)
        if not row["counted"]:
            replayed["shadow_soc_end"] = soc
            out.append(replayed)
            continue
        house_kw = float(row["house_kwh"]) / dt
        if flex_retimed_kw is not None:
            delivered = _delivered_kw(row, dt)
            retimed = flex_retimed_kw[index]
            shift = sum(retimed.get(cid, 0.0) - delivered.get(cid, 0.0) for cid in set(retimed) | set(delivered))
            house_kw += shift
        soc, _batt_kw, grid_kwh = _shadow_step(
            float(row["pv_kwh"]) / dt, house_kw, soc, battery_params, dt, row.get("shadow_limits")
        )
        k_act = float(row["k_act_cent"])
        k_push = float(row["k_push_cent"])
        replayed["cost_without_eur"] = _cost_eur(grid_kwh, k_act, k_push)
        if fuel_eur_per_slot is not None:
            replayed["cost_without_eur"] += fuel_eur_per_slot[index]
        replayed["import_kwh_without"] = max(grid_kwh, 0.0)
        replayed["export_kwh_without"] = max(-grid_kwh, 0.0)
        replayed["shadow_soc_end"] = soc
        out.append(replayed)
    return tuple(out), soc
