"""House catalogue of the "when does Earnie pay off" study (houses only).

All values come from ``haeuser.json`` (see ``params.py`` and ``anleitung-parameter.md``).
This module turns them into ``Archetype`` objects, adds the household axis and computes the
annual consumption. Earnie-Points, Abo tiers and prices are business data and are handled
outside this repository. ``python -m studies.viability.archetypes [--params FILE]`` prints the
houses as a Markdown table.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from studies.viability import params

params.set_path_from_argv()  # honour --params before reading the file
_P = params.load()

# --- assumptions -----------------------------------------------------------------------
_A = _P["assumptions"]
EV_KWH_PER_100KM = _A["ev_kwh_per_100km"]
EV_BATTERY_KWH = _A["ev_battery_kwh"]
WALLBOX_KW = _A["wallbox_kw"]  # three-phase
HEATING_ROD_KW = _A["heating_rod_kw"]
HEATING_ROD_KWH = _A["heating_rod_kwh"]
PV_TILT_DEG = _A["pv_tilt_deg"]
PV_AZIMUTH_SOUTH = _A["pv_azimuth_south"]
LOCATION = _A["location"]

# Household axis (electricity without heat pump, EV, heating rod). Applied to archetypes
# WITHOUT an EV; archetypes with an EV keep the default household only.
HOUSEHOLDS = _A["households"]
DEFAULT_HOUSEHOLD = _A["default_household"]

SOURCES = {
    "storage": "S: Technologiereport Speicher 2023 (13,89 kWh), IEA PVPS 2024 (ca. 14 kWh)",
    "pv_size": "A: keine oesterreichische Durchschnittsgroesse gefunden",
    "wp_kwh": "A: nur deutsche Quellen (3.000 bis 6.000 kWh/a)",
    "ev_km": "A: Haushalts-Durchschnitt 12.560 km/a (VCOe), E-Auto-spezifisch fehlt",
    "base_kwh": "S: klimaaktiv Richtwerte, Statistik Austria 2016 (4 Personen 4.027 kWh)",
    "rod": "A: kein Wert gefunden",
}


@dataclass(frozen=True)
class Archetype:
    id: str
    name: str
    base_kwh: int = HOUSEHOLDS[DEFAULT_HOUSEHOLD]  # household electricity without heat pump, EV, heating rod
    household: str = DEFAULT_HOUSEHOLD
    pv_kwp: float = 0.0
    pv_layout: str = "south"  # "south" or "east_west" (two equal halves)
    battery_kwh: float = 0.0
    evs: tuple[int, ...] = ()  # annual km per EV, one wallbox each
    heat_pump_kwh: int = 0
    heating_rod: bool = False

    # --- derived -------------------------------------------------------------------
    @property
    def ev_kwh(self) -> float:
        return sum(km / 100.0 * EV_KWH_PER_100KM for km in self.evs)

    @property
    def total_kwh(self) -> float:
        rod = HEATING_ROD_KWH if self.heating_rod else 0.0
        return self.base_kwh + self.heat_pump_kwh + self.ev_kwh + rod


# Templates (base load is the household axis, see variants()); defined in parameters.json "haeuser".
ARCHETYPES: tuple[Archetype, ...] = tuple(
    Archetype(
        h["id"], h["name"], pv_kwp=h["pv_kwp"], pv_layout=h["pv_layout"], battery_kwh=h["battery_kwh"],
        evs=h["evs"], heat_pump_kwh=h["heat_pump_kwh"], heating_rod=h["heating_rod"],
    )
    for h in _P["houses"]
)


def variants() -> tuple[Archetype, ...]:
    """Expand the household axis: three households without EV, middle household with EV."""
    out: list[Archetype] = []
    for tpl in ARCHETYPES:
        keys = (DEFAULT_HOUSEHOLD,) if tpl.evs else tuple(HOUSEHOLDS)
        for key in keys:
            out.append(replace(tpl, id=f"{tpl.id}-{key}", base_kwh=HOUSEHOLDS[key], household=key))
    return tuple(out)


def markdown_table() -> str:
    """House templates without business columns."""
    head = ("| ID | Beschreibung | PV kWp | Speicher kWh | E-Auto km | WP kWh | Heizstab | Haushalte | "
            "Gesamt kWh/a (mittlerer Haushalt) |")
    rows = [head, "|" + "---|" * 9]
    for a in ARCHETYPES:
        pv = (f"{a.pv_kwp:g}" + (" O/W" if a.pv_layout == "east_west" else "")) if a.pv_kwp else "-"
        rows.append(
            f"| {a.id} | {a.name} | {pv} | {a.battery_kwh:g} | "
            f"{' + '.join(f'{k:,}' for k in a.evs) or '-'} | {a.heat_pump_kwh or '-'} | "
            f"{'3 kW' if a.heating_rod else '-'} | {'nur mittel' if a.evs else 'klein/mittel/gross'} | "
            f"{a.total_kwh:,.0f} |"
        )
    return "\n".join(rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", help="Parameter file (default: parameters.json)")
    parser.parse_args()
    print(markdown_table())
