"""Zuordnung der Slot-Leistungen auf Rauf/Runter-Segmente (Herkunft/Ziel)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowAllocation:
    """kW-Zuordnung pro Slot (Summen müssen zur Energiebilanz passen)."""

    pv_to_load: float
    grid_to_load: float
    discharge_to_load: float
    charge_from_pv: float
    charge_from_grid: float
    export_from_pv: float
    export_from_battery: float

    @property
    def load_kw(self) -> float:
        return self.pv_to_load + self.grid_to_load + self.discharge_to_load

    @property
    def charge_kw(self) -> float:
        return self.charge_from_pv + self.charge_from_grid

    @property
    def export_kw(self) -> float:
        return self.export_from_pv + self.export_from_battery

    @property
    def discharge_kw(self) -> float:
        return self.discharge_to_load + self.export_from_battery


def allocate_slot_flows(
    *,
    pv: float,
    load_kw: float,
    battery_charge: float,
    battery_discharge: float,
    grid_import: float,
    grid_export: float,
) -> FlowAllocation:
    """
    Priorität: PV → Last → PV-Rest (Laden/Einspeisung) → Netz → Last → Entladen → Last.

    Einspeisung: zuerst PV-Rest, Rest aus Batterie-Entladung.
    Laden: zuerst PV-Rest nach Last, Rest aus Netz.
    """
    load = max(load_kw, 0.0)
    charge = max(battery_charge, 0.0)
    discharge = max(battery_discharge, 0.0)
    export = max(grid_export, 0.0)

    pv_to_load = min(pv, load)
    load_rem = load - pv_to_load
    pv_rem = pv - pv_to_load

    grid_to_load = min(grid_import, load_rem)
    load_rem -= grid_to_load

    discharge_to_load = min(discharge, load_rem)
    discharge_rem = discharge - discharge_to_load

    charge_from_pv = min(charge, pv_rem)
    pv_rem -= charge_from_pv
    charge_from_grid = charge - charge_from_pv

    export_from_pv = min(export, pv_rem)
    export_from_battery = export - export_from_pv

    if export_from_battery > discharge_rem + 1e-6:
        export_from_battery = max(discharge_rem, 0.0)
    discharge_to_load = discharge - export_from_battery

    return FlowAllocation(
        pv_to_load=pv_to_load,
        grid_to_load=grid_to_load,
        discharge_to_load=discharge_to_load,
        charge_from_pv=charge_from_pv,
        charge_from_grid=charge_from_grid,
        export_from_pv=export_from_pv,
        export_from_battery=export_from_battery,
    )
