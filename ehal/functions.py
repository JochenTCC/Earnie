"""EHAL functions and the fields each one needs (backend-agnostic).

A function (e.g. "limit the battery") is available only when *all* of its
required EHAL fields are mapped. A partly mapped function is reported as
``incomplete`` (UI warning) and treated as unavailable by the adapters — it
becomes available again as soon as the mapping is completed. Nothing mapped
means ``not_configured`` (no warning).

``started_by`` marks the fields that mean the user actually began that
function. Shared fields that already belong to another function (ESS limits)
do not count: a limits-only plant is ``not_configured`` for force
charge/discharge, not a half-finished ``ess_active``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

FunctionState = Literal["available", "incomplete", "not_configured"]


@dataclass(frozen=True)
class EhalFunction:
    id: str
    label: str
    required: tuple[str, ...]
    reason: str = ""
    # Fields that mean this function was started. Empty: any required field counts.
    started_by: tuple[str, ...] = ()


# Order = display order in the mapping UI.
EHAL_FUNCTIONS: tuple[EhalFunction, ...] = (
    EhalFunction(
        "telemetry",
        "Grundtelemetrie (Netz, PV, SoC)",
        ("sens_grid_power_active", "sens_pv_production_active", "sens_ess_soc"),
    ),
    EhalFunction(
        "ess_limits",
        "Speicher begrenzen (Automatik, Entladesperre)",
        ("set_ess_charge_power_limit", "set_ess_discharge_power_limit"),
        "Earnie setzt immer beide Grenzen; mit nur einer bleibt die andere auf dem letzten Wert stehen.",
    ),
    EhalFunction(
        "ess_active",
        "Speicher zwingen (Zwangsladen, Zwangsentladen)",
        (
            "set_ess_active_power",
            "set_ess_charge_power_limit",
            "set_ess_discharge_power_limit",
        ),
        "Ohne Lade-/Entladegrenzen kann Earnie nach einem Zwangsmodus nicht sicher zu Automatik zurückkehren.",
        ("set_ess_active_power",),
    ),
    EhalFunction(
        "evcs_current",
        "Wallbox-Ladestrom vorgeben",
        ("set_evcs_max_current",),
    ),
    EhalFunction(
        "slot_energy",
        "Slot-Ist aus Energiezählern",
        ("sens_pv_energy", "sens_grid_energy_import", "sens_grid_energy_export"),
        "Teilweise gemappte Zähler würden PV- und Netzbilanz aus verschiedenen Quellen mischen.",
    ),
)

FUNCTIONS_BY_ID = {f.id: f for f in EHAL_FUNCTIONS}


@dataclass(frozen=True)
class FunctionStatus:
    function: EhalFunction
    state: FunctionState
    missing: tuple[str, ...]


def _mapped_fields(mapped: Mapping[str, object] | Iterable[str]) -> set[str]:
    if isinstance(mapped, Mapping):
        return {str(k) for k, v in mapped.items() if str(v or "").strip()}
    return {str(k) for k in mapped}


def function_statuses(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    fields: Iterable[str] | None = None,
    vendor_ess_active: bool = False,
) -> list[FunctionStatus]:
    """Status of every function; ``fields`` restricts to functions whose required
    fields all belong to one mapping entity (e.g. plant vs. EV consumer).

    ``vendor_ess_active``: treat ``set_ess_active_power`` as mapped when a HA
    vendor force driver (e.g. huawei_solar) is configured.
    """
    present = _mapped_fields(mapped)
    if vendor_ess_active:
        present.add("set_ess_active_power")
    scope = set(fields) if fields is not None else None
    out: list[FunctionStatus] = []
    for function in EHAL_FUNCTIONS:
        if scope is not None and not set(function.required) <= scope:
            continue
        missing = tuple(f for f in function.required if f not in present)
        if not missing:
            state: FunctionState = "available"
        elif _not_started(function, present) or len(missing) == len(function.required):
            state = "not_configured"
        else:
            state = "incomplete"
        out.append(FunctionStatus(function, state, missing))
    return out


def _not_started(function: EhalFunction, present: set[str]) -> bool:
    """True when ``started_by`` is set and none of those fields are mapped."""
    if not function.started_by:
        return False
    return not any(field in present for field in function.started_by)


def incomplete_function_fields(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    vendor_ess_active: bool = False,
) -> set[str]:
    """Required fields of functions that are only partly mapped.

    Adapters report these in the live write trace. A function that was never
    started (``not_configured``) is omitted — an unmapped mode is not a
    half-finished function.
    """
    fields: set[str] = set()
    for status in function_statuses(mapped, vendor_ess_active=vendor_ess_active):
        if status.state == "incomplete":
            fields.update(status.function.required)
    return fields


def available_functions(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    vendor_ess_active: bool = False,
) -> set[str]:
    return {
        s.function.id
        for s in function_statuses(mapped, vendor_ess_active=vendor_ess_active)
        if s.state == "available"
    }


def incomplete_function_messages(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    fields: Iterable[str] | None = None,
    labels: Mapping[str, str] | None = None,
    vendor_ess_active: bool = False,
) -> list[str]:
    """German warnings for partly mapped functions (UI / log)."""
    names = labels or {}
    messages: list[str] = []
    for status in function_statuses(
        mapped, fields=fields, vendor_ess_active=vendor_ess_active
    ):
        if status.state != "incomplete":
            continue
        missing = ", ".join(names.get(f, f) for f in status.missing)
        text = f"„{status.function.label}“ ist nicht verfügbar – es fehlt: {missing}."
        if status.function.reason:
            text += f" {status.function.reason}"
        messages.append(text)
    return messages
