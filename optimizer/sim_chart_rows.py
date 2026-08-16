"""Chart-row helpers for horizon / baseline simulation."""
from __future__ import annotations

from datetime import datetime

from data.price_forecast_live import is_extrapolated_source
from optimizer import battery as bat
from optimizer.consumer_power import uses_pv_follow
from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.targets import consumer_column_name, consumer_pv_follow_column_name

COL_EINSPEISEVERGUETUNG = "Einspeisevergütung (Cent/kWh)"
COL_PV_PROGNOSE = "PV-Prognose (kW)"
COL_PV_IST = "PV-Ist (kW)"
COL_VERBRAUCH_PROGNOSE = "Verbrauch-Prognose (kW)"
COL_BATTERIE_AKTION = "Geplante Batterie-Aktion (kW)"
COL_NETZBEZUG = "Netzbezug (kW)"


def _chart_price_fields(row: dict) -> dict:
    """Preis-Felder für Simulations-/Chart-Zeilen."""
    fields = {
        "Strompreis (Cent/kWh)": row["k_act"],
        "Preis extrapoliert": is_extrapolated_source(row.get("price_source")),
    }
    if "k_push_act" in row:
        fields[COL_EINSPEISEVERGUETUNG] = row["k_push_act"]
    return fields


def resolve_sell_price_cent(row: dict, default_sell_price_cent: float | None = None) -> float:
    """Stündliche Einspeisevergütung aus Chart-Zeile oder Fallback."""
    if COL_EINSPEISEVERGUETUNG in row:
        return float(row[COL_EINSPEISEVERGUETUNG])
    if default_sell_price_cent is not None:
        return float(default_sell_price_cent)
    raise ValueError(
        "Kein Einspeisepreis in der Zeile und kein Fallback angegeben "
        f"({COL_EINSPEISEVERGUETUNG} oder default_sell_price_cent)."
    )


_RESERVED_KW_COLUMNS = {
    COL_PV_PROGNOSE,
    COL_PV_IST,
    COL_VERBRAUCH_PROGNOSE,
    COL_BATTERIE_AKTION,
    COL_NETZBEZUG,
}


def flexible_consumer_power_kw(row: dict) -> float:
    """Summiert alle flexiblen Verbraucher-Leistungen aus einer Chart-Zeile."""
    return sum(
        float(value or 0.0)
        for key, value in row.items()
        if key.endswith(" (kW)") and key not in _RESERVED_KW_COLUMNS
    )


def _finalize_chart_rows_for_display(
    chart_rows: list[dict],
    charging_contexts: dict[str, dict] | None = None,
    *,
    flex_live_kw: dict[str, float] | None = None,
) -> None:
    """Chart-Darstellung: Sofort-Laden, manuelle Geräte und known-Generics als Flex-Spuren."""
    from optimizer.charge_immediate import apply_immediate_charge_to_chart_rows
    from optimizer.appliance_schedule import apply_appliance_schedules_to_chart_rows
    from house_config.known_chart_display import apply_known_generic_to_chart_rows

    apply_immediate_charge_to_chart_rows(
        chart_rows,
        charging_contexts,
        flex_live_kw=flex_live_kw,
    )
    apply_appliance_schedules_to_chart_rows(chart_rows)
    apply_known_generic_to_chart_rows(chart_rows)


def _format_chart_uhrzeit(row: dict) -> str:
    slot_dt = row.get("slot_datetime")
    if isinstance(slot_dt, datetime):
        return slot_dt.strftime("%d.%m. %H:%M")
    hour = row.get("hour", 0)
    return f"{int(hour):02d}:00"


def _chart_row_slot_field(row: dict) -> dict:
    slot_dt = row.get("slot_datetime")
    if isinstance(slot_dt, datetime):
        return {"slot_datetime": slot_dt}
    return {}


def _chart_row_from_controls(
    row: dict,
    sim_soc: float,
    battery_params: dict,
    consumers_cfg: list,
    mode: int,
    target_power: float,
    consumer_powers: dict[str, float],
    consumer_pv_follow: dict[str, int],
) -> tuple[float, dict, int, float]:
    """Baut Chart-Zeile aus Modus/Flex-Leistungen (gemeinsam für MPC und commit-K)."""
    pv = row["expected_p_pv"]
    con = bat.effective_p_act(row, battery_params)
    total_flex_power = sum(consumer_powers.values())
    max_power = battery_params["max_power_kw"]
    batt_action = bat.battery_plan_kw_from_control(
        mode, target_power, pv, con, total_flex_power, max_power
    )
    action_text = bat.steuerbefehl_for_mode(mode, target_power)
    old_soc = sim_soc
    sim_soc, batt_action = bat.apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
        dt_h=DEFAULT_DT_H,
    )
    p_grid = con + total_flex_power - pv + round(batt_action, 2)
    chart_row = {
        "Uhrzeit": _format_chart_uhrzeit(row),
        **_chart_row_slot_field(row),
        **_chart_price_fields(row),
        COL_PV_PROGNOSE: pv,
        COL_VERBRAUCH_PROGNOSE: con,
        COL_BATTERIE_AKTION: round(batt_action, 2),
        COL_NETZBEZUG: round(p_grid, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": action_text,
    }
    for consumer in consumers_cfg:
        chart_row[consumer_column_name(consumer)] = round(
            consumer_powers.get(consumer["id"], 0.0), 2
        )
        if uses_pv_follow(consumer):
            chart_row[consumer_pv_follow_column_name(consumer)] = int(
                consumer_pv_follow.get(consumer["id"], 0) or 0
            )
    return sim_soc, chart_row, mode, target_power


def _chart_row_from_schedule_slot(
    row: dict,
    sim_soc: float,
    battery_params: dict,
    consumers_cfg: list,
    slot: dict,
) -> tuple[float, dict, int, float]:
    """Wendet einen MILP-Stundenplan-Slot open-loop auf die aktuelle SoC an."""
    consumer_powers = dict(slot.get("consumer_powers") or {})
    consumer_pv_follow = dict(slot.get("consumer_pv_follow") or {})
    total_flex = sum(consumer_powers.values())
    planned_soc = slot.get("planned_soc_percent")
    if planned_soc is None:
        planned_soc = sim_soc
    mode, target_power, _ = bat.derive_control_from_milp_plan(
        slot["milp_plan"],
        row,
        total_flex,
        sim_soc,
        float(planned_soc),
        battery_params,
        dt_h=DEFAULT_DT_H,
    )
    return _chart_row_from_controls(
        row,
        sim_soc,
        battery_params,
        consumers_cfg,
        mode,
        target_power,
        consumer_powers,
        consumer_pv_follow,
    )


def horizon_end_soc_from_chart_rows(chart_rows: list[dict]) -> float | None:
    """End-SOC nach Horizontlauf (gesetzt in simulate_horizon auf der letzten Zeile)."""
    if not chart_rows:
        return None
    raw = chart_rows[-1].get("_horizon_end_soc")
    if raw is None:
        return None
    return float(raw)


def horizon_end_soc_percent(
    chart_rows: list[dict],
    initial_soc: float,
    battery_params: dict,
) -> float:
    """SoC nach der letzten Horizontstunde (Kette über alle chart_rows)."""
    soc = float(initial_soc)
    for row in chart_rows:
        displayed = float(row["Simulierter SoC (%)"])
        soc = displayed
        batt = float(row.get(COL_BATTERIE_AKTION, 0.0) or 0.0)
        soc, _ = bat.apply_soc_change(
            soc,
            batt,
            battery_params["battery_capacity_kwh"],
            battery_params["efficiency"],
            battery_params["min_soc"],
            battery_params["max_soc"],
            dt_h=DEFAULT_DT_H,
        )
    return round(soc, 1)


def finalize_chart_row_energy(
    chart_row: dict,
    mode: int,
    target_power: float,
    old_soc: float,
    battery_params: dict,
) -> float:
    """Leitet Batterieaktion, Netzbezug und End-SoC aus Zeileninhalt ab (Huawei-Logik)."""
    pv = float(chart_row[COL_PV_PROGNOSE])
    con = float(chart_row[COL_VERBRAUCH_PROGNOSE])
    total_flex = flexible_consumer_power_kw(chart_row)
    max_power = battery_params["max_power_kw"]
    batt_action = bat.battery_plan_kw_from_control(
        mode, target_power, pv, con, total_flex, max_power
    )
    new_soc, batt_action = bat.apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
        dt_h=DEFAULT_DT_H,
    )
    chart_row[COL_BATTERIE_AKTION] = round(batt_action, 2)
    chart_row[COL_NETZBEZUG] = round(
        con + total_flex - pv + chart_row[COL_BATTERIE_AKTION],
        2,
    )
    return new_soc


def sync_chart_row_netzbezug(chart_row: dict) -> None:
    """Netzbezug aus PV, Last, Flex und Batterie ableiten (Chart-Energiebilanz)."""
    pv = float(chart_row.get(COL_PV_PROGNOSE, 0.0) or 0.0)
    con = float(chart_row.get(COL_VERBRAUCH_PROGNOSE, 0.0) or 0.0)
    batt = float(chart_row.get(COL_BATTERIE_AKTION, 0.0) or 0.0)
    flex_sum = flexible_consumer_power_kw(chart_row)
    chart_row[COL_NETZBEZUG] = round(con + flex_sum - pv + batt, 2)
