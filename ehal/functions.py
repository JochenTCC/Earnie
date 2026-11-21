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
        # SoC / inv PV kinds are satisfied by entity-scoped ess.|inv.{id}.* via _mapped_fields.
        ("sens_grid_power_active", "sens_inv_power_pv", "sens_ess_soc"),
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
    EhalFunction(
        "grid_export_limit",
        "Einspeiseleistung begrenzen",
        ("set_grid_export_power_limit",),
        "Ohne outbound Limit kann Earnie die Einspeisegrenze nicht an den Hub schreiben.",
    ),
    EhalFunction(
        "inverter_limit",
        "Wechselrichter AC-Leistung begrenzen",
        ("set_inv_ac_power_limit",),
        "Ohne outbound WR-Limit kann Earnie die AC-Leistung pro Wechselrichter nicht begrenzen.",
    ),
    EhalFunction(
        "ess_source_select",
        "Quellenwahl Netz/Batterie (Standby-Backup)",
        ("set_ess_source_select",),
        "Ohne Quellenwahl kann Earnie angeschlossene Dauerläufer nicht zwischen Netz und Powerstation umschalten.",
    ),
    EhalFunction(
        "heat_storage_band",
        "Speicherband der Regelung (Live plant mit Soll und Toleranz des Backends)",
        (
            "get_temperature_heat_storage_setpoint",
            "get_temperature_heat_storage_tolerance",
        ),
        "Mit nur einem der beiden Werte plant Live weiter mit dem konfigurierten Speicherband.",
    ),
)

FUNCTIONS_BY_ID = {f.id: f for f in EHAL_FUNCTIONS}


@dataclass(frozen=True)
class FunctionStatus:
    function: EhalFunction
    state: FunctionState
    missing: tuple[str, ...]


def _mapped_fields(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    require_nonempty_value: bool = True,
) -> set[str]:
    """Flat keys plus entity-scoped kinds (``ess|inv|pv|evcs.{slug}.*`` → kind).

    ``require_nonempty_value``: HA needs a real ``entity_id``. Loxone Q8 uses empty
    strings as activation flags — pass ``False`` so key presence counts.
    """
    from ehal.ess_fields import ess_field_kind
    from ehal.inverter_fields import inv_field_kind
    from ehal.pv_fields import pv_field_kind
    from ehal.qualified_ids import evcs_field_kind

    if isinstance(mapped, Mapping):
        if require_nonempty_value:
            keys = {str(k) for k, v in mapped.items() if str(v or "").strip()}
        else:
            keys = {str(k) for k, v in mapped.items() if str(k or "").strip()}
    else:
        keys = {str(k) for k in mapped}
    out = set(keys)
    for key in keys:
        kind = (
            ess_field_kind(key)
            or inv_field_kind(key)
            or pv_field_kind(key)
            or evcs_field_kind(key)
        )
        if kind:
            out.add(kind)
    return out


def function_statuses(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    fields: Iterable[str] | None = None,
    vendor_ess_active: bool = False,
    require_nonempty_value: bool = True,
) -> list[FunctionStatus]:
    """Status of every function; ``fields`` restricts to functions whose required
    fields all belong to one mapping entity (e.g. plant vs. EV consumer).

    ``vendor_ess_active``: treat ``set_ess_active_power`` as mapped when a HA
    vendor force driver (e.g. huawei_solar) is configured.
    """
    present = _mapped_fields(mapped, require_nonempty_value=require_nonempty_value)
    if vendor_ess_active:
        present.add("set_ess_active_power")
    # entity-scoped ess.{slug}.* expands to flat kinds so battery entity scope matches.
    scope = (
        _mapped_fields(fields, require_nonempty_value=require_nonempty_value)
        if fields is not None
        else None
    )
    flat, entities = _entity_kinds(mapped, require_nonempty_value=require_nonempty_value)
    if vendor_ess_active:
        flat.add("set_ess_active_power")
    out: list[FunctionStatus] = []
    for function in EHAL_FUNCTIONS:
        if scope is not None and not set(function.required) <= scope:
            continue
        missing = _missing_fields(function, present, flat, entities)
        if not missing:
            state: FunctionState = "available"
        elif _not_started(function, present) or len(missing) == len(function.required):
            state = "not_configured"
        else:
            state = "incomplete"
        out.append(FunctionStatus(function, state, missing))
    return out


def _active_keys(
    mapped: Mapping[str, object] | Iterable[str], *, require_nonempty_value: bool
) -> set[str]:
    if isinstance(mapped, Mapping):
        if require_nonempty_value:
            return {str(k) for k, v in mapped.items() if str(v or "").strip()}
        return {str(k) for k in mapped if str(k or "").strip()}
    return {str(k) for k in mapped}


def _kind_namespace(kind: str) -> str | None:
    """Device type whose fields must come from one entity (battery, inverter, …)."""
    from ehal.ess_fields import ESS_FIELD_KINDS
    from ehal.inverter_fields import INVERTER_FIELD_KINDS
    from ehal.pv_fields import PV_FIELD_KINDS
    from ehal.qualified_ids import EVCS_KINDS

    if kind in ESS_FIELD_KINDS:
        return "ess"
    if kind in INVERTER_FIELD_KINDS:
        return "inv"
    if kind in PV_FIELD_KINDS:
        return "pv"
    if kind in EVCS_KINDS:
        return "evcs"
    return None


def _entity_kinds(
    mapped: Mapping[str, object] | Iterable[str], *, require_nonempty_value: bool
) -> tuple[set[str], dict[str, dict[str, set[str]]]]:
    """(flat keys, namespace → Kennung → kinds) of the active keys."""
    from ehal.ess_fields import parse_ess_entity_scoped
    from ehal.inverter_fields import parse_inv_entity_scoped
    from ehal.pv_fields import parse_pv_entity_scoped
    from ehal.qualified_ids import evcs_field_kind

    flat: set[str] = set()
    entities: dict[str, dict[str, set[str]]] = {}
    for key in _active_keys(mapped, require_nonempty_value=require_nonempty_value):
        scoped = None
        for namespace, parse in (
            ("ess", parse_ess_entity_scoped),
            ("inv", parse_inv_entity_scoped),
            ("pv", parse_pv_entity_scoped),
        ):
            parsed = parse(key)
            if parsed:
                scoped = (namespace, parsed[0], parsed[1])
                break
        if scoped is None and evcs_field_kind(key):
            scoped = ("evcs", key.split(".")[1], evcs_field_kind(key))
        if scoped is None:
            flat.add(key)
        else:
            entities.setdefault(scoped[0], {}).setdefault(scoped[1], set()).add(scoped[2])
    return flat, entities


def _missing_fields(
    function: EhalFunction,
    present: set[str],
    flat: set[str],
    entities: dict[str, dict[str, set[str]]],
) -> tuple[str, ...]:
    """Required fields that are not mapped, in the order of ``function.required``.

    Fields of one device type must sit on one entity: the charge limit of one battery
    and the discharge limit of another do not make a function. Of several entities the
    one with the fewest missing fields counts (a second, read-only battery is no gap).
    """
    missing: set[str] = set()
    by_namespace: dict[str, list[str]] = {}
    for field in function.required:
        namespace = _kind_namespace(field)
        if namespace is None:
            if field not in present:
                missing.add(field)
        else:
            by_namespace.setdefault(namespace, []).append(field)
    for namespace, fields in by_namespace.items():
        candidates = [flat] + [flat | kinds for kinds in entities.get(namespace, {}).values()]
        gaps = [[f for f in fields if f not in candidate] for candidate in candidates]
        missing.update(min(gaps, key=len))
    return tuple(f for f in function.required if f in missing)


def _not_started(function: EhalFunction, present: set[str]) -> bool:
    """True when ``started_by`` is set and none of those fields are mapped."""
    if not function.started_by:
        return False
    return not any(field in present for field in function.started_by)


def incomplete_function_fields(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    vendor_ess_active: bool = False,
    require_nonempty_value: bool = True,
) -> set[str]:
    """Required fields of functions that are only partly mapped.

    Adapters report these in the live write trace. A function that was never
    started (``not_configured``) is omitted — an unmapped mode is not a
    half-finished function.
    """
    fields: set[str] = set()
    for status in function_statuses(
        mapped,
        vendor_ess_active=vendor_ess_active,
        require_nonempty_value=require_nonempty_value,
    ):
        if status.state == "incomplete":
            fields.update(status.function.required)
    return fields


def available_functions(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    vendor_ess_active: bool = False,
    require_nonempty_value: bool = True,
) -> set[str]:
    return {
        s.function.id
        for s in function_statuses(
            mapped,
            vendor_ess_active=vendor_ess_active,
            require_nonempty_value=require_nonempty_value,
        )
        if s.state == "available"
    }


def incomplete_function_messages(
    mapped: Mapping[str, object] | Iterable[str],
    *,
    fields: Iterable[str] | None = None,
    labels: Mapping[str, str] | None = None,
    vendor_ess_active: bool = False,
    require_nonempty_value: bool = True,
) -> list[str]:
    """German warnings for partly mapped functions (UI / log)."""
    names = labels or {}
    messages: list[str] = []
    for status in function_statuses(
        mapped,
        fields=fields,
        vendor_ess_active=vendor_ess_active,
        require_nonempty_value=require_nonempty_value,
    ):
        if status.state != "incomplete":
            continue
        missing = ", ".join(names.get(f, f) for f in status.missing)
        text = f"„{status.function.label}“ ist nicht verfügbar – es fehlt: {missing}."
        if status.function.reason:
            text += f" {status.function.reason}"
        messages.append(text)
    return messages
