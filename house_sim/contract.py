"""HouseSim contract mode — entities from Earnie activated keys (Binding P5d).

Derives deterministic HA ``entity_id``s from activated ``ehal_bindings`` keys
(empty values). Earnie never stores those entity ids; they exist only in the
simulator / YAML fill helper for tests and the push harness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ehal.push_signals import Signal, read_signals_from_docs, write_signals_from_docs
from ehal.qualified_ids import field_kind
from house_sim.state_store import StateStore
from integrations.ha_carrier_yaml import entity_placeholder
from integrations.ha_units import QUANTITY_BASE_UNIT, field_quantity

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def ehal_slug(ehal_id: str) -> str:
    """Stable slug for ``sensor.earnie_<slug>`` / ``number.earnie_<slug>``."""
    text = _SLUG_RE.sub("_", str(ehal_id or "").strip()).strip("_")
    return text.lower() if text else "unknown"


def contract_entity_id(ehal_id: str, *, write: bool) -> str:
    """Deterministic HouseSim entity id for a qualified EHAL ID."""
    slug = ehal_slug(ehal_id)
    domain = "number" if write else "sensor"
    return f"{domain}.earnie_{slug}"


def _unit_for(ehal_id: str) -> str | None:
    qty = field_quantity(field_kind(ehal_id))
    return QUANTITY_BASE_UNIT.get(qty) if qty else None


def _device_class_for(ehal_id: str) -> str | None:
    qty = field_quantity(field_kind(ehal_id))
    if qty == "power":
        return "power"
    if qty == "energy":
        return "energy"
    if qty == "percent":
        return "battery"
    if qty == "current":
        return "current"
    return None


def _default_state(ehal_id: str, *, write: bool) -> str:
    kind = field_kind(ehal_id)
    if kind == "sens_ess_soc":
        return "55.0"
    if kind.startswith("sens_") and "energy" in kind:
        return "100.0"
    if write and kind.startswith("set_"):
        return "0.0"
    if kind in ("sens_pv_production_active",):
        return "800.0"
    if kind in ("sens_grid_power_active",):
        return "500.0"
    return "0.0"


def _ha_state_object(ehal_id: str, *, write: bool) -> dict[str, Any]:
    entity_id = contract_entity_id(ehal_id, write=write)
    unit = _unit_for(ehal_id)
    attrs: dict[str, Any] = {
        "friendly_name": f"Earnie contract {ehal_id}",
    }
    if unit:
        attrs["unit_of_measurement"] = unit
    dc = _device_class_for(ehal_id)
    if dc:
        attrs["device_class"] = dc
    if not write:
        attrs["state_class"] = (
            "total_increasing" if (unit == "kWh") else "measurement"
        )
    else:
        attrs["min"] = -100000.0
        attrs["max"] = 100000.0
        attrs["step"] = 1.0
        attrs["mode"] = "box"
    return {
        "entity_id": entity_id,
        "state": _default_state(ehal_id, write=write),
        "attributes": attrs,
    }


def minimal_contract_docs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Small activated pack (empty binding values) for tests / CLI default."""
    house: dict[str, Any] = {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
                "sens_pv_production_active": "",
            }
        },
        "profiles": {},
    }
    components: dict[str, Any] = {
        "batteries": [
            {
                "id": "house",
                "type": "house",
                "control": "full",
                "ehal_bindings": {
                    "ess.house.sens_ess_soc": "",
                    "ess.house.set_ess_charge_power_limit": "",
                    "ess.house.set_ess_discharge_power_limit": "",
                    "ess.house.set_ess_active_power": "",
                },
            }
        ],
        "inverters": [],
        "pv_systems": [],
    }
    return house, components


def assert_bindings_have_no_entity_ids(
    house: dict[str, Any],
    components: dict[str, Any],
) -> None:
    """Fail loud when any activated binding stores a non-empty SB name."""
    from integrations.ha_push_read import binding_entries

    for kind, eid, _ctype, field_key, name in binding_entries(house, components):
        if str(name or "").strip():
            raise ValueError(
                f"contract pack must not store entity_id in ehal_bindings "
                f"({kind}:{eid} {field_key}={name!r})"
            )


@dataclass
class ContractBundle:
    """Activated pack + deterministic entity map + StateStore."""

    house: dict[str, Any]
    components: dict[str, Any]
    read_signals: list[Signal]
    write_signals: list[Signal]
    entity_by_ehal: dict[str, str] = field(default_factory=dict)
    store: StateStore = field(default_factory=StateStore)

    @property
    def read_entity_by_ehal(self) -> dict[str, str]:
        return {
            s.ehal_id: self.entity_by_ehal[s.ehal_id]
            for s in self.read_signals
            if s.ehal_id in self.entity_by_ehal
        }

    @property
    def write_entity_by_ehal(self) -> dict[str, str]:
        return {
            s.ehal_id: self.entity_by_ehal[s.ehal_id]
            for s in self.write_signals
            if s.ehal_id in self.entity_by_ehal
        }


def build_contract(
    house: dict[str, Any] | None = None,
    components: dict[str, Any] | None = None,
    *,
    allow_stored_entity_ids: bool = False,
) -> ContractBundle:
    """Build contract entities from activated keys (empty values by default)."""
    if house is None or components is None:
        house, components = minimal_contract_docs()
    if not allow_stored_entity_ids:
        assert_bindings_have_no_entity_ids(house, components)
    reads = read_signals_from_docs(house, components)
    writes = write_signals_from_docs(house, components)
    entity_by_ehal: dict[str, str] = {}
    entities: list[dict[str, Any]] = []
    for sig in reads:
        eid = contract_entity_id(sig.ehal_id, write=False)
        entity_by_ehal[sig.ehal_id] = eid
        entities.append(_ha_state_object(sig.ehal_id, write=False))
    for sig in writes:
        eid = contract_entity_id(sig.ehal_id, write=True)
        entity_by_ehal[sig.ehal_id] = eid
        entities.append(_ha_state_object(sig.ehal_id, write=True))
    return ContractBundle(
        house=house,
        components=components,
        read_signals=reads,
        write_signals=writes,
        entity_by_ehal=entity_by_ehal,
        store=StateStore(entities),
    )


def placeholder_fill_map(entity_by_ehal: dict[str, str]) -> dict[str, str]:
    """``ENTITY_*`` → deterministic ``entity_id`` for YAML tests."""
    return {
        entity_placeholder(ehal_id): entity_id
        for ehal_id, entity_id in entity_by_ehal.items()
    }


def fill_yaml_placeholders(yaml_text: str, entity_by_ehal: dict[str, str]) -> str:
    """Replace every ``ENTITY_*`` placeholder with the contract entity id."""
    text = str(yaml_text)
    # Longer placeholders first so prefixes do not collide.
    mapping = sorted(
        placeholder_fill_map(entity_by_ehal).items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for placeholder, entity_id in mapping:
        text = text.replace(placeholder, entity_id)
    return text


def fill_carrier_yaml_for_contract(
    bundle: ContractBundle,
    *,
    earnie_host: str,
    earnie_port: int,
    token: str,
    repeat_s: float = 10.0,
) -> str:
    """Build HA carrier YAML and fill contract entity ids (tests only)."""
    from integrations.ha_carrier_yaml import build_carrier_yaml

    raw = build_carrier_yaml(
        bundle.house,
        bundle.components,
        earnie_host=earnie_host,
        earnie_port=earnie_port,
        token=token,
        repeat_s=repeat_s,
    )
    return fill_yaml_placeholders(raw, bundle.entity_by_ehal)
