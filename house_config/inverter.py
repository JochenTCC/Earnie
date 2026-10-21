"""Inverter entity helpers (2.7.l): topology via ac_connection, not batteries[].kind."""
from __future__ import annotations

from typing import Literal

InverterType = Literal["hybrid", "pv_string", "battery"]
AcConnection = Literal["grid_tied", "island"]
InverterControl = Literal["full", "limits_only", "read_only"]

INVERTER_TYPE_HYBRID: InverterType = "hybrid"
INVERTER_TYPE_PV_STRING: InverterType = "pv_string"
INVERTER_TYPE_BATTERY: InverterType = "battery"
DEFAULT_INVERTER_TYPE: InverterType = INVERTER_TYPE_HYBRID

AC_GRID_TIED: AcConnection = "grid_tied"
AC_ISLAND: AcConnection = "island"
DEFAULT_AC_CONNECTION: AcConnection = AC_GRID_TIED

DEFAULT_INVERTER_CONTROL: InverterControl = "full"
DEFAULT_INVERTER_EFFICIENCY = 0.97

_TYPES = frozenset(
    {INVERTER_TYPE_HYBRID, INVERTER_TYPE_PV_STRING, INVERTER_TYPE_BATTERY}
)
_AC = frozenset({AC_GRID_TIED, AC_ISLAND})
_CONTROL = frozenset({"full", "limits_only", "read_only"})

MIGRATE_HINT = (
    "components.json needs inverters[] (2.7.l). Run: "
    "python -m scripts.migrate_inverters_once --config-dir <config-dir>"
)
CONVERSION_EFFICIENCY_MIGRATE_HINT = (
    "components.json needs inverters[].efficiency (η_inv). Run: "
    "python -m scripts.migrate_conversion_efficiency_once --config-dir <config-dir>"
)


def needs_inverter_migration(doc: dict) -> bool:
    """True when the document still uses pre-inverter topology."""
    if not isinstance(doc, dict):
        return False
    batteries = doc.get("batteries")
    pv_systems = doc.get("pv_systems")
    if isinstance(batteries, list):
        for bat in batteries:
            if isinstance(bat, dict) and "kind" in bat:
                return True
    has_assets = (
        (isinstance(batteries, list) and len(batteries) > 0)
        or (isinstance(pv_systems, list) and len(pv_systems) > 0)
    )
    if not has_assets:
        return False
    if "inverters" not in doc:
        return True
    # Assets present but still missing inverter_id (pre-migrate hand edits).
    for bat in batteries or []:
        if not isinstance(bat, dict):
            continue
        bat_type = str(bat.get("type") or "house").strip().lower()
        backing = str(bat.get("backing") or "").strip().lower()
        if bat_type == "powerstation" and backing == "virtual":
            continue
        if not str(bat.get("inverter_id") or "").strip():
            return True
    for pv in pv_systems or []:
        if isinstance(pv, dict) and not str(pv.get("inverter_id") or "").strip():
            return True
    return False


def reject_if_needs_inverter_migration(doc: dict, *, path: str = "") -> None:
    """Fail fast when components still use batteries[].kind / missing inverters."""
    if not needs_inverter_migration(doc):
        return
    where = f" ({path})" if path else ""
    raise ValueError(
        f"components.json{where}: pre-inverter topology detected "
        f"(missing inverters[] or residual batteries[].kind). {MIGRATE_HINT}"
    )


def needs_conversion_efficiency_migration(doc: dict) -> bool:
    """True when any inverter lacks required one-way efficiency (η_inv)."""
    if not isinstance(doc, dict):
        return False
    inverters = doc.get("inverters")
    if not isinstance(inverters, list) or not inverters:
        return False
    for inv in inverters:
        if not isinstance(inv, dict):
            return True
        if "efficiency" not in inv:
            return True
    return False


def reject_if_needs_conversion_efficiency_migration(
    doc: dict, *, path: str = ""
) -> None:
    """Fail fast when inverters[] exist but η_inv is missing."""
    if not needs_conversion_efficiency_migration(doc):
        return
    where = f" ({path})" if path else ""
    raise ValueError(
        f"components.json{where}: inverters[].efficiency (η_inv) fehlt. "
        f"{CONVERSION_EFFICIENCY_MIGRATE_HINT}"
    )


def allows_automatik(ac_connection: str) -> bool:
    """True when Design C1 Automatik is allowed (not island)."""
    return str(ac_connection or "").strip().lower() != AC_ISLAND


def _optional_positive_kw(raw: object, *, field: str, inv_id: str, index: int) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): {field} ungültig."
        ) from exc
    if value <= 0.0:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): {field} muss > 0 sein."
        )
    return value


def _normalize_inverter_choices(
    raw: dict, inv_id: str, index: int
) -> tuple[str, str, str]:
    """Validated ``(type, ac_connection, control)`` of a raw inverter entry."""
    inv_type = str(raw.get("type") or DEFAULT_INVERTER_TYPE).strip().lower()
    if inv_type not in _TYPES:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): type muss "
            f"'hybrid', 'pv_string' oder 'battery' sein (got {raw.get('type')!r})."
        )
    ac = str(raw.get("ac_connection") or DEFAULT_AC_CONNECTION).strip().lower()
    if ac not in _AC:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): ac_connection muss "
            f"'grid_tied' oder 'island' sein (got {raw.get('ac_connection')!r})."
        )
    control = str(raw.get("control") or DEFAULT_INVERTER_CONTROL).strip().lower()
    if control not in _CONTROL:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): control ungültig ({raw.get('control')!r})."
        )
    return inv_type, ac, control


def _parse_inverter_efficiency(raw: dict, inv_id: str, index: int) -> float:
    """η_inv in (0, 1]; raises when missing, unparsable or out of range."""
    if "efficiency" not in raw:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): efficiency (η_inv) fehlt. "
            f"{CONVERSION_EFFICIENCY_MIGRATE_HINT}"
        )
    try:
        efficiency = float(raw["efficiency"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): efficiency ungültig."
        ) from exc
    if not (0.0 < efficiency <= 1.0):
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): efficiency muss in (0, 1] liegen "
            f"(got {efficiency!r})."
        )
    return efficiency


def normalize_inverter(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"inverters[{index}] muss ein Objekt sein.")
    inv_id = str(raw.get("id", "")).strip()
    if not inv_id:
        raise ValueError(f"inverters[{index}]: id fehlt.")
    label = str(raw.get("label", inv_id)).strip() or inv_id
    inv_type, ac, control = _normalize_inverter_choices(raw, inv_id, index)
    ehal_bindings = raw.get("ehal_bindings")
    if ehal_bindings is None:
        ehal_bindings = {}
    if not isinstance(ehal_bindings, dict):
        raise ValueError(
            f"inverters[{index}] ('{inv_id}'): ehal_bindings muss ein Objekt sein."
        )
    efficiency = _parse_inverter_efficiency(raw, inv_id, index)
    out: dict = {
        "id": inv_id,
        "label": label,
        "type": inv_type,
        "ac_connection": ac,
        "control": control,
        "efficiency": efficiency,
        "ehal_bindings": {
            str(k): str(v).strip()
            for k, v in ehal_bindings.items()
            if str(k or "").strip()
        },
    }
    for field in ("max_ac_power_kw", "max_pv_input_kw", "max_ac_charge_kw"):
        value = _optional_positive_kw(
            raw.get(field), field=field, inv_id=inv_id, index=index
        )
        if value is not None:
            out[field] = value
    owned_by = str(raw.get("owned_by") or "").strip()
    if owned_by:
        out["owned_by"] = owned_by
    from house_config.topology_regulates import normalize_regulates_on

    regulates_on = normalize_regulates_on(
        raw.get("regulates_on") if "regulates_on" in raw else None,
        entity_kind="inverters",
        entity_id=inv_id,
        index=index,
        required=False,
    )
    if regulates_on is not None:
        out["regulates_on"] = regulates_on
    if "id_locked" in raw:
        out["id_locked"] = bool(raw.get("id_locked"))
    provisional = str(raw.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    return out


def inverters_by_id(raw_config: dict) -> dict[str, dict]:
    raw_list = raw_config.get("inverters")
    if raw_list is None:
        return {}
    if not isinstance(raw_list, list):
        raise ValueError("inverters muss ein Array sein.")
    result: dict[str, dict] = {}
    for index, item in enumerate(raw_list):
        spec = normalize_inverter(item, index)
        if spec["id"] in result:
            raise ValueError(f"inverters: doppelte id '{spec['id']}'.")
        result[spec["id"]] = spec
    return result


def planning_inverter_entry(inv: dict) -> dict:
    entry = {
        "id": inv["id"],
        "label": inv["label"],
        "type": inv["type"],
        "ac_connection": inv["ac_connection"],
        "control": inv.get("control", DEFAULT_INVERTER_CONTROL),
        "efficiency": float(inv["efficiency"]),
        "ehal_bindings": dict(inv.get("ehal_bindings") or {}),
    }
    for field in (
        "max_ac_power_kw",
        "max_pv_input_kw",
        "max_ac_charge_kw",
        "owned_by",
        "regulates_on",
    ):
        if field in inv and inv[field] is not None:
            entry[field] = inv[field]
    return entry


def validate_inverter_topology(
    *,
    inverters: dict[str, dict],
    batteries: dict[str, dict],
    pv_systems: dict[str, dict],
) -> None:
    """Cross-entity checks after normalize (unknown id, owned_by, island PV)."""
    _validate_battery_inverters(inverters, batteries)
    _validate_pv_inverters(inverters, pv_systems)
    _validate_inverter_ownership(inverters, batteries)


def _validate_battery_inverters(
    inverters: dict[str, dict], batteries: dict[str, dict]
) -> None:
    from house_config.powerstation import is_virtual_powerstation

    for bat_id, bat in batteries.items():
        if is_virtual_powerstation(bat):
            if bat.get("inverter_id"):
                raise ValueError(
                    f"Batterie '{bat_id}': virtuelle Powerstation darf keinen "
                    "inverter_id haben."
                )
            continue
        inv_id = str(bat.get("inverter_id") or "").strip()
        if not inv_id:
            raise ValueError(
                f"Batterie '{bat_id}': inverter_id fehlt "
                "(virtuelle Powerstations ausgenommen)."
            )
        if inv_id not in inverters:
            raise ValueError(
                f"Batterie '{bat_id}': unbekannte inverter_id '{inv_id}'."
            )
        inv = inverters[inv_id]
        if inv["type"] == INVERTER_TYPE_PV_STRING:
            raise ValueError(
                f"Batterie '{bat_id}': inverter '{inv_id}' ist type=pv_string "
                "(nur PV, keine Batterie)."
            )


def _validate_pv_inverters(
    inverters: dict[str, dict], pv_systems: dict[str, dict]
) -> None:
    for pv_id, pv in pv_systems.items():
        inv_id = str(pv.get("inverter_id") or "").strip()
        if not inv_id:
            raise ValueError(f"PV-Feld '{pv_id}': inverter_id fehlt.")
        if inv_id not in inverters:
            raise ValueError(
                f"PV-Feld '{pv_id}': unbekannte inverter_id '{inv_id}'."
            )
        inv = inverters[inv_id]
        if inv["type"] == INVERTER_TYPE_BATTERY:
            raise ValueError(
                f"PV-Feld '{pv_id}': inverter '{inv_id}' ist type=battery "
                "(keine PV-Seite)."
            )


def _validate_inverter_ownership(
    inverters: dict[str, dict], batteries: dict[str, dict]
) -> None:
    from house_config.powerstation import (
        BATTERY_TYPE_POWERSTATION,
        BACKING_VIRTUAL,
    )

    for inv_id, inv in inverters.items():
        owned = str(inv.get("owned_by") or "").strip()
        if not owned:
            continue
        if owned not in batteries:
            raise ValueError(
                f"Inverter '{inv_id}': owned_by '{owned}' unbekannt."
            )
        bat = batteries[owned]
        if str(bat.get("inverter_id") or "").strip() != inv_id:
            raise ValueError(
                f"Inverter '{inv_id}': owned_by '{owned}' zeigt nicht zurück "
                f"(battery.inverter_id={bat.get('inverter_id')!r})."
            )
        bat_type = str(bat.get("type") or "house").strip().lower()
        backing = str(bat.get("backing") or "").strip().lower()
        if bat_type == BATTERY_TYPE_POWERSTATION and backing == BACKING_VIRTUAL:
            raise ValueError(
                f"Inverter '{inv_id}': owned_by darf keine virtuelle Powerstation sein."
            )
