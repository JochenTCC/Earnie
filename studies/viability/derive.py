"""Derive a house from its free axes (study parameter plan v3, § 4.2). Pure, no Earnie imports.

``derive_house`` turns persons, envelope, heating system, PV sizing, layout, battery ratio and EV
pattern into the values the pack generator writes. Each rule's values come from ``haeuser.json``.
``all_houses`` enumerates the valid combinations and ``stratified_sample`` draws from them.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass

from studies.viability.params import validate_heating_system


@dataclass(frozen=True)
class DerivedHouse:
    id: str
    axes: dict
    scenarios: tuple[str, ...]
    living_area_m2: float
    gross_floor_area_m2: float
    household_kwh: float
    hot_water_kwh: float
    space_heat_kwh: float
    heat_pump_kwh: float
    ev_kwh: float
    demand_kwh: float
    heating_power_kw: float
    jaz: float
    building_class: int
    collector_m2: float
    storage_liters: float
    storage_loss_kw_per_k: float
    storage_setpoint_c: float
    storage_tolerance_c: float
    roof_cap_kwp: float
    pv_wanted_kwp: float
    pv_kwp: float
    pv_limit: str
    battery_kwh: float
    ev_patterns: tuple[str, ...]

    @property
    def heat_source(self) -> str:
        return self.axes["_quelle"]


def roof_cap_kwp(gross_floor_area_m2: float, layout: str, collector_m2: float, rules: dict) -> float:
    """Usable roof per side, one side for south and two for east/west, less the collector."""
    footprint = gross_floor_area_m2 / rules["dach_geschosse"]
    side = footprint / 2.0 / math.cos(math.radians(rules["dach_neigung_grad"]))
    sides = 1 if layout == "sued" else 2
    usable = side * rules["dach_nutzbar"] * sides - collector_m2
    return usable / rules["dach_m2_je_kwp"]


def storage_liters(heating_power_kw: float, collector_m2: float, rules: dict) -> float:
    """Volume from the heating power within its limits; a collector asks for at least its own rule."""
    by_power = rules["speicher_l_je_kw"] * heating_power_kw
    limited = min(rules["speicher_max_l"], max(rules["speicher_min_l"], by_power))
    return float(round(max(limited, rules["speicher_l_je_m2_kollektor"] * collector_m2)))


def storage_loss_kw_per_k(liters: float, rules: dict) -> float:
    """Upper limit of ErP class C, in W at the reference difference, as kW per K."""
    loss = rules["speicher_verlust_w"]
    return (loss["basis"] + loss["faktor"] * liters ** loss["exponent"]) / loss["bezug_k"] / 1000.0


def derive_house(house: dict, params: dict) -> DerivedHouse:
    rules, assumptions = params["regeln"], params["annahmen"]
    persons = int(house["personen"])
    envelope = rules["huellen"][house["huelle"]]
    system = params["heizsysteme"][house["heizsystem"]]
    validate_heating_system(system, f"{house['id']}.{house['heizsystem']}")

    area = rules["wohnflaeche_basis_m2"] + rules["wohnflaeche_je_person_m2"] * (persons - 2)
    gross = area * rules["bgf_faktor"]
    household = float(rules["haushaltsstrom_kwh"][str(persons)])
    hot_water = rules["warmwasser_kwh_je_person_tag"] * persons * 365.0
    space_heat = gross * envelope["hwb_kwh_m2"]
    heat_pump = (space_heat + hot_water) / envelope["jaz"] if system["quelle"] == "heat_pump" else 0.0
    patterns = tuple(params["eauto_muster"]["fahrzeuge"][house["eauto"]])
    ev = len(patterns) * assumptions["ev_km_pro_jahr"] * assumptions["ev_kwh_pro_100km"] / 100.0
    demand = household + heat_pump + ev

    heating_power = round(
        space_heat * rules["heizlast_delta_t_k"] / (rules["heizgradtage_kd"] * 24.0)
        + rules["heizlast_kw_je_person"] * persons,
        2,
    )
    collector = rules["kollektor_m2_je_person"] * persons if system["kollektor"] else 0.0
    storage = storage_liters(heating_power, collector, rules) if system["speicher"] else 0.0
    band = rules["speicher_band_c"][system["quelle"]]
    cap = roof_cap_kwp(gross, house["pv_belegung"], collector, rules)
    wanted = house["pv_kwp_je_mwh"] * demand / 1000.0
    pv, limit = wanted, "verbrauch"
    if pv < rules["pv_min_kwp"]:
        pv, limit = rules["pv_min_kwp"], "mindest_kwp"
    if pv > cap:
        pv, limit = cap, "dach"
    return DerivedHouse(
        id=house["id"],
        axes={**{k: house[k] for k in params["achsen"]}, "_quelle": system["quelle"],
              "_heizstab": system["heizstab"]},
        scenarios=tuple(house["szenarien"]),
        living_area_m2=float(area),
        gross_floor_area_m2=gross,
        household_kwh=household,
        hot_water_kwh=hot_water,
        space_heat_kwh=space_heat,
        heat_pump_kwh=heat_pump,
        ev_kwh=ev,
        demand_kwh=demand,
        heating_power_kw=heating_power,
        jaz=float(envelope["jaz"]),
        building_class=int(envelope["gebaeudeklasse"]),
        collector_m2=collector,
        storage_liters=storage,
        storage_loss_kw_per_k=storage_loss_kw_per_k(storage, rules) if storage else 0.0,
        storage_setpoint_c=float(band["bis"]),
        storage_tolerance_c=float(band["bis"] - band["von"]),
        roof_cap_kwp=cap,
        pv_wanted_kwp=wanted,
        pv_kwp=round(pv, 2),
        pv_limit=limit,
        battery_kwh=round(pv * house["speicher_kwh_je_kwp"], 1),
        ev_patterns=patterns,
    )


def all_houses(params: dict) -> list[dict]:
    """Every valid combination of the axes, with a stable id."""
    axes = params["achsen"]
    for system in axes["heizsystem"]:
        validate_heating_system(params["heizsysteme"][system], system)
    houses: list[dict] = []
    for persons, envelope, system, pv, layout, battery, ev in itertools.product(
        axes["personen"], axes["huelle"], axes["heizsystem"], axes["pv_kwp_je_mwh"],
        axes["pv_belegung"], axes["speicher_kwh_je_kwp"], axes["eauto"],
    ):
        if envelope not in params["heizsysteme"][system]["huellen"]:
            continue
        houses.append({
            "id": f"G{len(houses):04d}",
            "personen": persons, "huelle": envelope, "heizsystem": system, "pv_kwp_je_mwh": pv,
            "pv_belegung": layout, "speicher_kwh_je_kwp": battery, "eauto": ev,
            "szenarien": list(params["standard_szenarien"]),
        })
    return houses


def stratified_sample(params: dict, count: int, seed: int, *, min_per_level: int = 10) -> list[dict]:
    """Random sample in which every axis level occurs at least ``min_per_level`` times if possible.

    Each pick prefers the house whose levels are furthest below the minimum, ties broken by the
    seeded shuffle, so the same seed gives the same sample.
    """
    pool = all_houses(params)
    random.Random(seed).shuffle(pool)
    axes = list(params["achsen"])
    counts = {(axis, level): 0 for axis in axes for level in params["achsen"][axis]}
    picked: list[dict] = []
    for _ in range(min(count, len(pool))):
        best = max(
            range(len(pool)),
            key=lambda i: sum(max(0, min_per_level - counts[(axis, pool[i][axis])]) for axis in axes),
        )
        house = pool.pop(best)
        picked.append(house)
        for axis in axes:
            counts[(axis, house[axis])] += 1
    return picked
