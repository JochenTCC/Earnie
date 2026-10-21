"""HouseSim archetype generator — Earnie pack → S4 archetype directory (HA Testbed P1).

From the activated ``ehal_bindings`` keys of ``house_profiles.json`` +
``components.json`` it writes an archetype in the layout ``load_archetype`` reads
(``entities.json``, ``ehal.ha.entities.json``, ``house_params.json``,
``pv_series.json``) plus ``placeholders.json`` (``ehal_id`` → ``entity_id``, the
single source for filling the carrier YAML) and ``meta.json``.

Design (docs/dev/ha-contract-testbed.md §3b):

* Physics looks up *flat* field names; the generator emits flat keys for the
  physical subset, so ``house_sim/core`` stays untouched and ``ehal``-free.
* Only grid, PV (one inverter), one house battery and a wallbox are physical.
  Every other signal gets an explicit static value, listed in ``meta.json``.
  S4 serves static values only from numbers, so static *reads* are ``number``
  entities seeded from the fixture state.
* The pack must be canonical (PV per inverter, ``ess.<id>.sens_ess_power`` for
  grid-tied house batteries). Missing required inputs abort; nothing is
  defaulted silently.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ehal.qualified_ids import field_kind, parse_qualified_id
from ehal.required_signals import grid_tied_house_batteries, inverter_has_attached_pv
from house_sim.contract import (
    ContractBundle,
    _ha_state_object,
    build_contract,
)
from house_sim.core.archetype import TELEMETRY_PROJECTION
from integrations.ha_carrier_yaml import entity_placeholder
from integrations.ha_units import QUANTITY_BASE_UNIT, field_quantity

GENERATOR_VERSION = 1
HOURS_PER_YEAR = 8760.0
# Synthetic PV day: sin² bell, peak = fraction × installed kWp.
PV_PEAK_FRACTION = 0.8
DEFAULT_PV_POINTS = 48
DEFAULT_INITIAL_SOC_PCT = 50.0
STATIC_WRITE_INITIAL = "0.0"
BATTERY_TYPE_HOUSE = "house"

ARCHETYPE_FILES = (
    "entities.json",
    "ehal.ha.entities.json",
    "house_params.json",
    "pv_series.json",
    "placeholders.json",
    "meta.json",
)

# Physics flat key ← plant/grid kinds (same name on both sides).
_GRID_PHYSICAL = frozenset(
    {"sens_grid_power_active", "sens_grid_energy_import", "sens_grid_energy_export"}
)
_ESS_PHYSICAL = frozenset(
    {
        "sens_ess_soc",
        "sens_ess_power",
        "set_ess_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
    }
)
_PV_FLAT = "sens_pv_production_active"
_BATTERY_ENERGY = {
    "sens_ess_energy_charge": "charge",
    "sens_ess_energy_discharge": "discharge",
}


@dataclass(frozen=True)
class StaticSpec:
    value: str
    unit: str | None = None  # only for kinds without an EHAL quantity


# Explicit static values for non-physical reads, by field kind. Unknown kinds
# abort unless ``static_overrides`` supplies a value.
STATIC_READ_VALUES: dict[str, StaticSpec] = {
    "sens_inv_power_ac": StaticSpec("0.0"),
    "sens_power_consumers": StaticSpec("0.0"),
    "sens_power_act": StaticSpec("0.0"),
    "sens_pv_production_active": StaticSpec("0.0"),
    "sens_evcs_active_power": StaticSpec("0.0"),
    "sens_evcs_connected": StaticSpec("0"),
    "sens_evcs_soc_act": StaticSpec("50.0"),
    "sens_evcs_bat_capacity": StaticSpec("60.0"),
    "get_evcs_limit_soc": StaticSpec("80.0"),
    "get_evcs_soc_min_immediate": StaticSpec("20.0"),
    "get_evcs_nominal_current": StaticSpec("16.0"),
    "get_grid_export_power_limit": StaticSpec("10000.0"),
    "get_inv_max_ac_power": StaticSpec("10000.0"),
    "get_inv_max_pv_power": StaticSpec("10000.0"),
    "sens_temperature_outside": StaticSpec("10.0", "°C"),
    "sens_temperature_water": StaticSpec("45.0", "°C"),
    "get_temperature_water_setpoint": StaticSpec("50.0", "°C"),
    "get_temperature_tolerance_c": StaticSpec("2.0", "K"),
    "sens_temperature_heat_storage": StaticSpec("45.0", "°C"),
    "sens_temperature_heat_storage_low": StaticSpec("35.0", "°C"),
    "sens_heating_active": StaticSpec("0"),
    "sens_filter_active": StaticSpec("0"),
    "sens_consumer_active": StaticSpec("0"),
    "sens_absent_mode": StaticSpec("0"),
    "sens_energy_total": StaticSpec("0.0", "kWh"),
}

# Battery limits come from the pack (kind → (components key, factor to EHAL unit)).
_BATTERY_DERIVED_STATIC: dict[str, tuple[str, float]] = {
    "get_ess_soc_min": ("battery_min_soc", 1.0),
    "get_ess_soc_max": ("battery_max_soc", 1.0),
    "get_ess_max_charge_power": ("battery_max_charge_power_kw", 1000.0),
    "get_ess_max_discharge_power": ("battery_max_discharge_power_kw", 1000.0),
}


@dataclass
class GeneratedArchetype:
    """In-memory result; ``write_archetype`` puts it on disk."""

    entities: dict[str, Any]
    ehal_entities: dict[str, Any]
    house_params: dict[str, Any]
    pv_series: dict[str, Any]
    placeholders: dict[str, str]
    meta: dict[str, Any]
    bundle: ContractBundle = field(repr=False, default=None)  # type: ignore[assignment]

    def files(self) -> dict[str, Any]:
        return {
            "entities.json": self.entities,
            "ehal.ha.entities.json": self.ehal_entities,
            "house_params.json": self.house_params,
            "pv_series.json": self.pv_series,
            "placeholders.json": self.placeholders,
            "meta.json": self.meta,
        }


def load_pack(config_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read ``house_profiles.json`` + ``components.json`` (as ``ha_carrier_yaml_gen``)."""
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    return house, components


def pack_sha256(house: dict[str, Any], components: dict[str, Any]) -> str:
    blob = json.dumps(
        {"house_profiles": house, "components": components},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- canonical pack checks ---------------------------------------------------


def _check_canonical(bundle: ContractBundle) -> None:
    house, components = bundle.house, bundle.components
    read_ids = {s.ehal_id for s in bundle.read_signals}
    plant_bindings = (house.get("plant") or {}).get("ehal_bindings") or {}
    if any(field_kind(k) == _PV_FLAT for k in plant_bindings):
        raise ValueError(
            "pack is not canonical: plant sens_pv_production_active is retired "
            "(PV is bound per inverter as inv.<id>.sens_inv_power_pv). "
            "Run python -m scripts.migrate_config first."
        )
    pv_systems = components.get("pv_systems") or []
    for inv in components.get("inverters") or []:
        iid = str(inv.get("id") or "").strip()
        if inverter_has_attached_pv(iid, pv_systems) and f"inv.{iid}.sens_inv_power_pv" not in read_ids:
            raise ValueError(
                f"pack is not canonical: inverter {iid!r} has attached PV but "
                f"inv.{iid}.sens_inv_power_pv is not activated "
                "(python -m scripts.migrate_config)."
            )
    for bat in grid_tied_house_batteries(
        components.get("batteries") or [], components.get("inverters") or []
    ):
        bid = str(bat.get("id") or "").strip()
        for kind in ("sens_ess_soc", "sens_ess_power"):
            if f"ess.{bid}.{kind}" not in read_ids:
                raise ValueError(
                    f"pack is not canonical: grid-tied house battery {bid!r} "
                    f"needs ess.{bid}.{kind} activated (python -m scripts.migrate_config)."
                )


# --- physical selection ------------------------------------------------------


def _house_batteries(components: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        b
        for b in components.get("batteries") or []
        if str(b.get("type") or BATTERY_TYPE_HOUSE).strip().lower() == BATTERY_TYPE_HOUSE
    ]


def _physical_battery(components: dict[str, Any]) -> dict[str, Any] | None:
    batteries = _house_batteries(components)
    if len(batteries) > 1:
        ids = ", ".join(str(b.get("id")) for b in batteries)
        raise ValueError(
            f"archetype physics models exactly one house battery, pack has {len(batteries)} ({ids})"
        )
    return batteries[0] if batteries else None


def _positive(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a number: {value!r}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be > 0, got {value!r}")
    return number


def _battery_capacity_kwh(battery: dict[str, Any] | None, override: float | None) -> tuple[float, str]:
    if override is not None:
        return _positive(override, "--battery-kwh"), "argument"
    if battery is None:
        raise ValueError(
            "no house battery in the pack and no --battery-kwh: the simulator physics needs a battery capacity"
        )
    if battery.get("battery_capacity_kwh") in (None, ""):
        raise ValueError(
            f"battery {battery.get('id')!r} has no battery_capacity_kwh; pass --battery-kwh"
        )
    return _positive(battery["battery_capacity_kwh"], f"battery {battery.get('id')!r} battery_capacity_kwh"), "components.json"


def _load_kw(house: dict[str, Any], override: float | None) -> tuple[float, str]:
    if override is not None:
        number = float(override)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"--load-kw must be >= 0, got {override!r}")
        return number, "argument"
    profiles = house.get("profiles") or {}
    items = list(profiles.values()) if isinstance(profiles, dict) else list(profiles)
    annual = [p for p in items if isinstance(p, dict) and p.get("annual_kwh") not in (None, "")]
    if len(annual) != 1:
        raise ValueError(
            f"cannot derive the base load: {len(annual)} profiles with annual_kwh "
            "(need exactly one); pass --load-kw"
        )
    kwh = _positive(annual[0]["annual_kwh"], f"profile {annual[0].get('id')!r} annual_kwh")
    return round(kwh / HOURS_PER_YEAR, 4), f"profile {annual[0].get('id')!r} annual_kwh / {HOURS_PER_YEAR:g}"


def _pv_series(components: dict[str, Any], points: int) -> tuple[list[float], float]:
    if points < 2:
        raise ValueError("--pv-points must be >= 2")
    systems = components.get("pv_systems") or []
    if not systems:
        return [0.0], 0.0
    kwp = 0.0
    for pv in systems:
        kwp += _positive(pv.get("kwp"), f"pv_system {pv.get('id')!r} kwp")
    peak = kwp * PV_PEAK_FRACTION
    series = [round(peak * math.sin(math.pi * (i + 0.5) / points) ** 2, 4) for i in range(points)]
    return series, kwp


# --- entity construction -----------------------------------------------------


def _state(num: float, ndigits: int = 4) -> str:
    return f"{round(float(num), ndigits):g}"


def _device_key(ehal_id: str) -> str:
    parsed = parse_qualified_id(ehal_id)
    if parsed is None or parsed.namespace is None:
        return "plant"
    return f"{parsed.namespace}_{parsed.kennung}"


def _battery_by_id(components: dict[str, Any], bid: str) -> dict[str, Any]:
    for bat in components.get("batteries") or []:
        if str(bat.get("id")) == bid:
            return bat
    raise ValueError(f"battery {bid!r} not found in components.json")


def _static_read(
    ehal_id: str,
    components: dict[str, Any],
    overrides: dict[str, str],
) -> tuple[str, str | None, str]:
    """(state, unit or None, source) for a non-physical read."""
    kind = field_kind(ehal_id)
    parsed = parse_qualified_id(ehal_id)
    if ehal_id in overrides:
        return str(overrides[ehal_id]), STATIC_READ_VALUES.get(kind, StaticSpec("")).unit, "override"
    if kind in overrides:
        return str(overrides[kind]), STATIC_READ_VALUES.get(kind, StaticSpec("")).unit, "override"
    if kind in _BATTERY_DERIVED_STATIC and parsed is not None and parsed.namespace == "ess":
        key, factor = _BATTERY_DERIVED_STATIC[kind]
        bat = _battery_by_id(components, str(parsed.kennung))
        if bat.get(key) in (None, ""):
            raise ValueError(
                f"{ehal_id}: battery {parsed.kennung!r} has no {key} to derive a static value; "
                "pass --static"
            )
        return _state(float(bat[key]) * factor), None, f"components.json {key}"
    spec = STATIC_READ_VALUES.get(kind)
    if spec is None:
        raise ValueError(
            f"{ehal_id}: no static value for kind {kind!r}; pass --static {ehal_id}=<value>"
        )
    return spec.value, spec.unit, "table"


def _unit_check(ehal_id: str, unit: str | None) -> None:
    qty = field_quantity(field_kind(ehal_id))
    if qty is None:
        return
    base = QUANTITY_BASE_UNIT[qty]
    if unit is not None and unit != base:
        raise ValueError(f"{ehal_id}: unit {unit!r} does not match its quantity {qty} ({base})")


def _limit_w(battery: dict[str, Any], key: str, ehal_id: str) -> float:
    if battery.get(key) in (None, ""):
        raise ValueError(f"{ehal_id}: battery {battery.get('id')!r} has no {key}")
    return _positive(battery[key], f"battery {battery.get('id')!r} {key}") * 1000.0


def generate_archetype(
    house: dict[str, Any],
    components: dict[str, Any],
    *,
    battery_kwh: float | None = None,
    load_kw: float | None = None,
    initial_soc_pct: float = DEFAULT_INITIAL_SOC_PCT,
    static_overrides: dict[str, str] | None = None,
    pv_points: int = DEFAULT_PV_POINTS,
) -> GeneratedArchetype:
    """Build the archetype for a pack; raises ``ValueError`` on anything missing."""
    overrides = dict(static_overrides or {})
    bundle = build_contract(house, components)
    _check_canonical(bundle)
    reads, writes = bundle.read_signals, bundle.write_signals
    if not reads and not writes:
        raise ValueError("pack has no activated signals")
    if not 0.0 <= float(initial_soc_pct) <= 100.0:
        raise ValueError(f"initial SoC must be within 0..100 %, got {initial_soc_pct!r}")

    battery = _physical_battery(components)
    phys_bid = str(battery.get("id")) if battery else None
    capacity, capacity_src = _battery_capacity_kwh(battery, battery_kwh)
    base_load, load_src = _load_kw(house, load_kw)
    series, kwp = _pv_series(components, pv_points)

    pv_ids = [s.ehal_id for s in reads if field_kind(s.ehal_id) == "sens_inv_power_pv"]
    if len(pv_ids) > 1:
        raise ValueError(
            "archetype physics models one PV source, pack activates "
            f"{len(pv_ids)} inverter PV signals ({', '.join(pv_ids)})"
        )
    if kwp > 0 and not pv_ids:
        raise ValueError("pack has PV systems but no inv.<id>.sens_inv_power_pv activated")
    evcs_ids = sorted(s.ehal_id for s in reads if field_kind(s.ehal_id) == "sens_evcs_active_power")

    physical: dict[str, str] = {}  # flat key → ehal_id
    battery_energy: dict[str, str] = {}  # charge/discharge → ehal_id
    for sig in reads + writes:
        ehal_id, kind = sig.ehal_id, field_kind(sig.ehal_id)
        parsed = parse_qualified_id(ehal_id)
        ns = parsed.namespace if parsed else None
        if ns == "grid" and kind in _GRID_PHYSICAL:
            physical[kind] = ehal_id
        elif ns is None and kind == "sens_pv_energy":
            physical[kind] = ehal_id
        elif ehal_id in pv_ids:
            physical[_PV_FLAT] = ehal_id
        elif ns == "ess" and parsed.kennung == phys_bid and kind in _ESS_PHYSICAL:
            physical[kind] = ehal_id
        elif ns == "ess" and parsed.kennung == phys_bid and kind in _BATTERY_ENERGY:
            battery_energy[_BATTERY_ENERGY[kind]] = ehal_id
        elif evcs_ids and ehal_id == evcs_ids[0]:
            physical[kind] = ehal_id
    for flat, ehal_id in physical.items():
        proj_qty = TELEMETRY_PROJECTION.get(flat, (None, None, None))[1]
        if flat in TELEMETRY_PROJECTION and field_quantity(field_kind(ehal_id)) != proj_qty:
            raise ValueError(f"{ehal_id}: quantity does not match physics field {flat}")

    entities: list[dict[str, Any]] = []
    entity_by_ehal: dict[str, str] = {}
    static_signals: list[dict[str, str]] = []
    device_members: dict[str, list[str]] = {}
    physical_ids = set(physical.values()) | set(battery_energy.values())

    def _register(ehal_id: str, obj: dict[str, Any]) -> None:
        entity_by_ehal[ehal_id] = obj["entity_id"]
        entities.append(obj)
        device_members.setdefault(_device_key(ehal_id), []).append(obj["entity_id"])

    for sig in reads:
        ehal_id = sig.ehal_id
        if ehal_id in physical_ids:
            obj = _ha_state_object(ehal_id, write=False)
            obj["state"] = _state(initial_soc_pct) if field_kind(ehal_id) == "sens_ess_soc" else "0.0"
            _register(ehal_id, obj)
            continue
        state, unit, source = _static_read(ehal_id, components, overrides)
        _unit_check(ehal_id, unit)
        # S4 serves static values only from number entities (seeded from the fixture state).
        obj = _ha_state_object(ehal_id, write=True)
        obj["state"] = state
        if unit:
            obj["attributes"]["unit_of_measurement"] = unit
        _register(ehal_id, obj)
        static_signals.append(
            {"ehal_id": ehal_id, "entity_id": obj["entity_id"], "value": state, "unit": unit or "", "source": source}
        )

    for sig in writes:
        ehal_id, kind = sig.ehal_id, field_kind(sig.ehal_id)
        obj = _ha_state_object(ehal_id, write=True)
        if ehal_id in physical_ids and kind == "set_ess_active_power":
            obj["state"] = "0.0"
        elif ehal_id in physical_ids:
            key = "battery_max_charge_power_kw" if "charge_power_limit" in kind and "discharge" not in kind else "battery_max_discharge_power_kw"
            obj["state"] = _state(_limit_w(battery, key, ehal_id))
        else:
            obj["state"] = STATIC_WRITE_INITIAL
            static_signals.append(
                {"ehal_id": ehal_id, "entity_id": obj["entity_id"], "value": STATIC_WRITE_INITIAL, "unit": "", "source": "write initial"}
            )
        _register(ehal_id, obj)

    ids = [e["entity_id"] for e in entities]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"entity ids collide (slug clash): {', '.join(dup)}")
    placeholders = [entity_placeholder(i) for i in entity_by_ehal]
    if len(set(placeholders)) != len(placeholders):
        raise ValueError("ENTITY_* placeholders collide for distinct EHAL ids")

    devices = [
        {
            "key": key,
            "name": f"Earnie sim {key}",
            "manufacturer": "earnie_house_sim",
            "model": "generated",
            "entity_ids": members,
        }
        for key, members in sorted(device_members.items())
    ]

    ehal_map = {flat: entity_by_ehal[eid] for flat, eid in physical.items()}
    sign = {k: "ehal" for k in ehal_map if k != "sens_ess_soc"}
    house_params: dict[str, Any] = {
        "battery_capacity_kwh": capacity,
        "initial_soc_pct": float(initial_soc_pct),
        "load_kw": base_load,
        "initial_evcs_power_w": 0.0,
    }
    if battery_energy:
        house_params["battery_energy_entities"] = {
            direction: entity_by_ehal[eid] for direction, eid in battery_energy.items()
        }
    self_consumption = battery is not None and "set_ess_active_power" not in physical
    if self_consumption:
        house_params["ess_fallback"] = "self_consumption"
        if "set_ess_charge_power_limit" not in physical:
            house_params["ess_max_charge_w"] = _limit_w(battery, "battery_max_charge_power_kw", "self_consumption")
        if "set_ess_discharge_power_limit" not in physical:
            house_params["ess_max_discharge_w"] = _limit_w(battery, "battery_max_discharge_power_kw", "self_consumption")

    meta = {
        "title": "Generated from an Earnie configuration pack (HA Testbed P1)",
        "generator": "house_sim.archetype_gen",
        "generator_version": GENERATOR_VERSION,
        "source_pack_sha256": pack_sha256(house, components),
        "physical": {flat: {"ehal_id": eid, "entity_id": entity_by_ehal[eid]} for flat, eid in sorted(physical.items())},
        "physical_battery_energy": {d: entity_by_ehal[e] for d, e in sorted(battery_energy.items())},
        "static_signals": sorted(static_signals, key=lambda s: s["ehal_id"]),
        "params": {
            "battery_capacity_kwh": {"value": capacity, "source": capacity_src},
            "load_kw": {"value": base_load, "source": load_src},
            "initial_soc_pct": {"value": float(initial_soc_pct), "source": "argument"},
            "pv": {
                "kwp": kwp,
                "peak_fraction": PV_PEAK_FRACTION,
                "points": len(series),
                "inverter_signal": pv_ids[0] if pv_ids else None,
            },
            "ess_fallback": "self_consumption" if self_consumption else None,
        },
        "notes": [
            "Static reads are number entities: S4 serves static values from numbers only.",
            "Setpoints are numbers (carrier writes via number.set_value); switch/select setpoints are not modelled.",
            "Wallboxes beyond the first and all non-physical signals are static; consumer loads are not simulated.",
        ],
    }

    return GeneratedArchetype(
        entities={"devices": devices, "entities": entities},
        ehal_entities={"entities": ehal_map, "sign": sign},
        house_params=house_params,
        pv_series={"kw": series},
        placeholders=dict(sorted(entity_by_ehal.items())),
        meta=meta,
        bundle=bundle,
    )


def write_archetype(archetype: GeneratedArchetype, out_dir: Path) -> list[Path]:
    """Write the archetype files into ``out_dir`` (created if missing)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, doc in archetype.files().items():
        path = out_dir / name
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written
