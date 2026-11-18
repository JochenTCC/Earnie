"""Compute SE reference flows once per physical setup and book them per tariff.

L0 (Referenz ohne Speicher) and L1 (vendor-mode battery) book energy flows that do not
depend on prices: L0 has no control, L1 is the inverter's own self-consumption mode and does
not curtail at negative prices. Two scenarios that differ only in their tariff therefore have
the same flows; only the booking differs. L2 curtails at negative feed-in prices and locks
flex on price, so it is not shared across tariffs.

The run plan keeps one result id per (setup, tariff), so fees, invoices and the log stay as
they are; only the computation is shared (``share_by_physical_setup``), and the other result
ids are booked from the computed series (``rebook_reference_frame``).
"""
from __future__ import annotations

import json
from typing import NamedTuple

import pandas as pd

import config
from data import feed_in_prices
from data.backtesting_prices import market_for_prices
from data.edibert_slot_prices import EDIBERT_PRICING_KEY
from data.market_prices import epex_prices_for_slots

# Resolved scenario keys that only price energy. Everything else counts as physical setup;
# a key missing here only costs a shared run, it never shares two different setups.
PRICE_PARAM_KEYS = frozenset(
    {
        EDIBERT_PRICING_KEY,
        "_import_tariff_spec",
        "_export_tariff_spec",
        "k_push_cent",
        # Set from the import tariff; it picks the spot market the prices come from.
        "market_zone",
    }
)


def physical_setup_key(scenario_params: dict | None) -> str | None:
    """Sharing key of a reference's flows: the resolved params without the price keys.

    ``None`` params (no scenario) have no key and are never shared.
    """
    if scenario_params is None:
        return None
    physical = {k: v for k, v in scenario_params.items() if k not in PRICE_PARAM_KEYS}
    return json.dumps(physical, sort_keys=True, default=str)


class SharedReferencePlan(NamedTuple):
    """``computed``: result ids to compute. ``rebooked``: result id → computed source id."""

    computed: list[str]
    rebooked: dict[str, str]


def share_by_physical_setup(specs: list[tuple[str, dict | None]]) -> SharedReferencePlan:
    """The first result id of each physical setup is computed, the others are rebooked."""
    computed: list[str] = []
    rebooked: dict[str, str] = {}
    owner_by_key: dict[str, str] = {}
    for ref_id, params in specs:
        key = physical_setup_key(params)
        if key is None or key not in owner_by_key:
            computed.append(ref_id)
            if key is not None:
                owner_by_key[key] = ref_id
            continue
        rebooked[ref_id] = owner_by_key[key]
    return SharedReferencePlan(computed, rebooked)


def rebook_reference_frame(
    frame: pd.DataFrame,
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> pd.DataFrame:
    """Book the flows of ``frame`` (``import_kwh`` / ``export_kwh`` per slot) at the tariff of
    ``scenario_params``: end-customer price incl. grid fee and VAT, and feed-in price.

    Same formula as ``_hour_cost_parts_without_optimization`` and
    ``calculate_step_cost_parts_from_row``. Flow columns, SoC and attrs stay as they are.
    """
    from simulation.engine import _brutto_prices_for_slots

    slots = [pd.Timestamp(ts).to_pydatetime() for ts in frame.index]
    buy_cent = _brutto_prices_for_slots(prices_df, slots, scenario_params=scenario_params)
    sell_cent = feed_in_prices.export_cents_for_slots(
        slots,
        epex_prices_for_slots(prices_df, slots),
        config.get_backtesting_feed_in_settings(runtime_override=scenario_params),
        market_for=market_for_prices(prices_df, None),
    )
    out = frame.copy()
    out["k_act"] = [float(value) for value in buy_cent]
    out["k_push_act"] = [float(value) for value in sell_cent]
    out["import_cost_eur"] = out["import_kwh"] * out["k_act"] / 100.0
    out["export_earn_eur"] = out["export_kwh"] * out["k_push_act"] / 100.0
    out["sim_cost"] = out["import_cost_eur"] - out["export_earn_eur"]
    return out


def fill_rebooked_results(
    results: dict[str, pd.DataFrame],
    plan: SharedReferencePlan,
    params_by_ref_id: dict[str, dict],
    prices_df: pd.DataFrame,
) -> None:
    """Add every rebooked result id to ``results`` from its computed source."""
    for ref_id, source_id in plan.rebooked.items():
        if source_id not in results:
            raise KeyError(f"Referenz '{source_id}' fehlt, '{ref_id}' teilt ihre Energieflüsse.")
        results[ref_id] = rebook_reference_frame(
            results[source_id], prices_df, params_by_ref_id[ref_id]
        )
