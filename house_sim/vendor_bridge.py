"""Bridge between contract entities and a vendor archetype (HouseSim W3).

In a real Home Assistant the carrier automations copy Earnie's setpoints onto
vendor entities and vendor telemetry onto the entities Earnie reads. In tests the
contract store (``sensor.earnie_*`` / ``number.earnie_*``) and a vendor store
(e.g. ``evcc_en``) are separate, so this bridge plays that role: setpoints go
contract → vendor, telemetry goes vendor → contract.

Earnie-facing like :mod:`house_sim.push_harness`; ``house_sim/core`` stays free
of Earnie imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from house_sim.contract import ContractBundle
from house_sim.state_store import StateStore

PLUG_TO_NUMBER = {"on": 1.0, "off": 0.0}


@dataclass(frozen=True)
class Link:
    """One copied value between a qualified EHAL ID and a vendor entity.

    ``convert`` maps the source state string to the target state string; the
    default copies numbers unchanged.
    """

    ehal_id: str
    vendor_entity_id: str
    convert: Callable[[str], str] | None = None


def plug_state_to_number(state: str) -> str:
    """Vendor ``on`` / ``off`` → ``1`` / ``0`` as Earnie's digital field expects."""
    key = str(state).strip().lower()
    if key not in PLUG_TO_NUMBER:
        raise ValueError(f"Plug state {state!r} is neither 'on' nor 'off'")
    return str(PLUG_TO_NUMBER[key])


def _number(state: str) -> str:
    return str(float(state))


class VendorBridge:
    """Copies setpoints and telemetry between a contract bundle and a vendor store."""

    def __init__(
        self,
        bundle: ContractBundle,
        vendor_store: StateStore,
        *,
        setpoints: list[Link],
        telemetry: list[Link],
    ) -> None:
        self.bundle = bundle
        self.vendor_store = vendor_store
        self.setpoints = list(setpoints)
        self.telemetry = list(telemetry)
        writes = bundle.write_entity_by_ehal
        reads = bundle.read_entity_by_ehal
        for link in self.setpoints:
            if link.ehal_id not in writes:
                raise ValueError(f"{link.ehal_id} is no activated write signal")
        for link in self.telemetry:
            if link.ehal_id not in reads:
                raise ValueError(f"{link.ehal_id} is no activated read signal")

    def to_vendor(self) -> list[str]:
        """Contract setpoints → vendor entities; returns the copied EHAL IDs."""
        copied: list[str] = []
        writes = self.bundle.write_entity_by_ehal
        for link in self.setpoints:
            payload = self.bundle.store.get(writes[link.ehal_id])
            if payload is None:
                raise KeyError(writes[link.ehal_id])
            convert = link.convert or _number
            self.vendor_store.set_state(link.vendor_entity_id, convert(payload["state"]))
            copied.append(link.ehal_id)
        return copied

    def from_vendor(self) -> list[str]:
        """Vendor telemetry → contract sensors; returns the copied EHAL IDs."""
        copied: list[str] = []
        reads = self.bundle.read_entity_by_ehal
        for link in self.telemetry:
            payload = self.vendor_store.get(link.vendor_entity_id)
            if payload is None:
                raise KeyError(link.vendor_entity_id)
            convert = link.convert or _number
            self.bundle.store.set_state(reads[link.ehal_id], convert(payload["state"]))
            copied.append(link.ehal_id)
        return copied
