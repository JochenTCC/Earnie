"""Savings ledger v2: heating rod beside a fuel source (plan savings-ledger-v2-plan.md § 4.4)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from house_config.heat_source import heating_rod_fuel_credit_cent_per_kwh
from house_config.planning_flex_converters import planning_heating_rod_to_milp
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_flex as slf

TZ = ZoneInfo("Europe/Vienna")
DAY1 = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
STEP = timedelta(minutes=15)
DT = 0.25
ROD_SLOTS = range(20, 28)  # 12:00–14:00: the rod heats with PV surplus
ROD_KW = 3.0
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 1.0,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}


def _rod(heat_source: dict) -> dict:
    """The planning consumer the MILP plans with, from the real converter."""
    parent = {"id": "wp", "type": "thermal_annual", "nominal_power_kw": 2.0, "heat_source": heat_source}
    part = {"id": "heizstab", "type": "heating_rod", "nominal_power_kw": ROD_KW}
    return planning_heating_rod_to_milp(parent, part)


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _closed(*, pv: float, rod_id: str, rod_kw: float) -> dict:
    house = 0.5 + rod_kw
    return {
        "sample_count": 30,
        "pv_kw": pv,
        "grid_kw": house - pv,
        "battery_kw": 0.0,
        "house_kw": house,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
        "flex_kw": {rod_id: rod_kw},
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _day(rod_id: str) -> list[sl.LedgerInput]:
    inputs = []
    for i in range(96):
        rod_kw = ROD_KW if i in ROD_SLOTS else 0.0
        pv = 4.0 if i in ROD_SLOTS else 0.0
        inputs.append(sl.LedgerInput(DAY1 + i * STEP, _closed(pv=pv, rod_id=rod_id, rod_kw=rod_kw), 30.0, 8.0))
    closing = sl.LedgerInput(DAY1 + timedelta(days=1), _closed(pv=0.0, rod_id=rod_id, rod_kw=0.0), 30.0, 8.0)
    return inputs + [closing]


def _close(rod: dict, battery: dict | None):
    rid = rod["id"]

    def day_flex(state: sl.LedgerState) -> slf.FlexDayInputs:
        return slf.FlexDayInputs(
            consumers=[rod],
            profiles_kw={},
            windows={rid: slf.ConsumerWindows(enable_slots=None, native_slots=None)},
        )

    inputs = _day(rid)
    state = sl.start_chain(
        inputs[0], day_bounds, reason=sl.CHAIN_FIRST_RUN, savings_v=2, with_battery=battery is not None
    )
    closes = []
    for inp in inputs:
        state, closed_day = sl.advance_with_slots(
            state, inp, battery, day_bounds, app_version="test", day_flex=day_flex
        )
        if closed_day is not None:
            closes.append(closed_day)
    (closed,) = closes
    return closed


def test_rod_beside_gas_is_fuel_in_the_shadow_plant():
    gas = {"type": "gas"}
    rod = _rod(gas)
    closed = _close(rod, None)
    row = closed.row
    rod_kwh = ROD_KW * len(ROD_SLOTS) * DT  # 6 kWh
    credit = heating_rod_fuel_credit_cent_per_kwh(gas)  # 0.1043 €/kWh / 0.95 → ct per rod kWh

    assert row["flex_timing"] == {rod["id"]: slf.TIMING_FUEL}
    assert row["fuel_saved_kwh"] == pytest.approx(round(rod_kwh / 0.95, 3))
    assert row["fuel_saved_eur"] == pytest.approx(round(rod_kwh * credit / 100.0, 4))
    # with Earnie: the rod used 3 of the 4 kW PV; without: the 3 kW are exported at 8 ct
    # and the heat is bought as gas. Without battery the electricity part is exact:
    export_eur = ROD_KW * len(ROD_SLOTS) * DT * 0.08
    assert row["saving_eur"] == pytest.approx(rod_kwh * credit / 100.0 - export_eur, abs=1e-4)
    # rod electricity only on the "with" side; nothing re-timed in the shadow plant
    assert row["flex_delivered_kwh"] == {rod["id"]: rod_kwh}
    assert row["flex_retimed_kwh"] == {}
    # the fuel sits in the slots the rod ran in, so the slots add up to the row
    record = sl.day_slots_record(closed.closing)
    sl.check_day_slots(row, record)
    # slot 20 without Earnie: load 0.5 kW, PV 4 kW → 3.5 kW export at 8 ct, plus the rod's gas
    fuel_slot = closed.closing.slots[20]["cost_without_eur"]
    assert fuel_slot == pytest.approx(ROD_KW * DT * credit / 100.0 - 3.5 * DT * 0.08)


def test_rod_fuel_price_is_the_milp_credit():
    oil = {"type": "oil", "fuel_price": 120.0, "efficiency": 0.8}
    rod = _rod(oil)
    assert rod["fuel_credit_cent_per_kwh"] == pytest.approx(0.12 / 0.8 * 100.0)
    closed = _close(rod, BATTERY)
    rod_kwh = ROD_KW * len(ROD_SLOTS) * DT
    assert closed.row["fuel_saved_eur"] == pytest.approx(round(rod_kwh * 0.15, 4))
    assert closed.row["fuel_saved_kwh"] == pytest.approx(round(rod_kwh / 0.8, 3))
    sl.check_day_slots(closed.row, sl.day_slots_record(closed.closing))


def test_rod_beside_an_electric_source_is_an_ordinary_consumer():
    hp = {"type": "heat_pump", "heat_pump_type": "luft"}
    rod = _rod(hp)
    assert rod["parent_heat_electric"] is True and "fuel_credit_cent_per_kwh" not in rod
    closed = _close(rod, BATTERY)
    row = closed.row
    # no shape and no window: logged timing, no fuel
    assert row["flex_timing"] == {rod["id"]: slf.TIMING_LOGGED}
    assert row["flex_logged_reasons"] == {rod["id"]: slf.REASON_NO_SHAPE_NO_WINDOW}
    assert row["fuel_saved_kwh"] == 0.0 and row["fuel_saved_eur"] == 0.0
    assert row["saving_eur"] == row["saving_logged_timing_eur"]


def test_rod_beside_fuel_without_price_keeps_its_logged_timing():
    rod = _rod({"type": "gas"})
    rod.pop("fuel_credit_cent_per_kwh")
    closed = _close(rod, None)
    assert closed.row["flex_timing"] == {rod["id"]: slf.TIMING_LOGGED}
    assert closed.row["flex_logged_reasons"] == {rod["id"]: slf.REASON_NO_FUEL_PRICE}
    assert closed.row["fuel_saved_eur"] == 0.0
    assert closed.row["saving_eur"] == 0.0


def test_rod_without_meter_is_logged_no_meter():
    rod = _rod({"type": "gas"})
    rows = [{"counted": True, "flex_delivered_kwh": {}} for _ in range(4)]
    result = slf.retime_flex_day(
        rows, [rod], {}, {rod["id"]: slf.ConsumerWindows(None, None)}, dt_h=DT
    )
    assert result.timing == {rod["id"]: slf.TIMING_LOGGED_NO_METER}
    assert result.fuel_kwh == 0.0 and result.fuel_eur_per_slot == [0.0] * 4
