"""Multi-inverter live PV attribution: PV systems → inverter → plant AC.

Post-read helpers (not per adapter). Island inverters are excluded from plant
derive and plant→inverter split. Incomplete maps fail loud.
"""
from __future__ import annotations

from typing import Any

from ehal.inverter_fields import inv_field
from ehal.pv_fields import pv_field
from optimizer.milp_inverter import inverter_efficiency, is_grid_tied


def _eta_inv(inv: dict) -> float:
    """η_inv for live attribution; fail loud when efficiency is missing."""
    return inverter_efficiency(inv)


def _pv_systems_for_inverter(
    pv_systems: list[dict],
    inverter_id: str,
) -> list[dict]:
    iid = str(inverter_id or "").strip()
    out: list[dict] = []
    for pv in pv_systems:
        if not isinstance(pv, dict):
            continue
        if str(pv.get("inverter_id") or "").strip() == iid:
            out.append(pv)
    return out


def grid_tied_inverters_with_pv(
    inverters: list[dict],
    pv_systems: list[dict],
) -> list[dict]:
    """Grid-tied inverters that own at least one PV system (island excluded)."""
    out: list[dict] = []
    for inv in inverters:
        if not isinstance(inv, dict):
            continue
        iid = str(inv.get("id") or "").strip()
        if not iid or not is_grid_tied(inv):
            continue
        if _pv_systems_for_inverter(pv_systems, iid):
            out.append(inv)
    return out


def binding_mapped(bindings: dict | None, field: str) -> bool:
    """True when the binding key is present (empty string = push-only activation)."""
    if not isinstance(bindings, dict):
        return False
    return field in bindings


def inv_pv_coverage_complete(
    inv: dict,
    pv_systems: list[dict],
    *,
    scoped_live: dict[str, Any] | None = None,
) -> bool:
    """True when this inverter has live/mapped inv PV or every attached PV maps."""
    iid = str(inv.get("id") or "").strip()
    if not iid:
        return False
    inv_key = inv_field(iid, "sens_inv_power_pv")
    live = scoped_live if isinstance(scoped_live, dict) else {}
    if inv_key in live and live[inv_key] is not None:
        return True
    bindings = inv.get("ehal_bindings")
    if binding_mapped(bindings if isinstance(bindings, dict) else None, inv_key):
        return True
    attached = _pv_systems_for_inverter(pv_systems, iid)
    if not attached:
        return False
    for pv in attached:
        pid = str(pv.get("id") or "").strip()
        if not pid:
            return False
        pv_key = pv_field(pid, "sens_pv_production_active")
        if pv_key in live and live[pv_key] is not None:
            continue
        pv_bindings = pv.get("ehal_bindings")
        if not binding_mapped(
            pv_bindings if isinstance(pv_bindings, dict) else None, pv_key
        ):
            return False
    return True


def plant_pv_derive_coverage_complete(
    inverters: list[dict],
    pv_systems: list[dict],
    *,
    scoped_live: dict[str, Any] | None = None,
) -> bool:
    """True when every grid-tied inverter with PV can contribute to plant derive."""
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if not eligible:
        return False
    return all(
        inv_pv_coverage_complete(inv, pv_systems, scoped_live=scoped_live)
        for inv in eligible
    )


def plant_pv_binding_mapped(house: dict | None) -> bool:
    plant = house.get("plant") if isinstance(house, dict) else None
    bindings = (
        plant.get("ehal_bindings") if isinstance(plant, dict) else None
    )
    if not isinstance(bindings, dict):
        return False
    return "sens_pv_production_active" in bindings


def plant_pv_may_be_derived(house: dict | None, components: dict | None) -> bool:
    """True when plant PV binding is absent and inv/pv coverage is complete."""
    if plant_pv_binding_mapped(house):
        return False
    comps = components if isinstance(components, dict) else {}
    inverters = list(comps.get("inverters") or [])
    pv_systems = list(comps.get("pv_systems") or [])
    return plant_pv_derive_coverage_complete(inverters, pv_systems)


def load_house_for_attribution() -> dict:
    try:
        from house_config.ha_ehal_bindings import load_house_profiles_for_ha

        doc = load_house_profiles_for_ha()
        if isinstance(doc, dict):
            return doc
    except Exception:
        pass
    try:
        from ui.house_config_io import load_house_profiles

        doc = load_house_profiles()
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def read_scoped_pv_loxone(field: str) -> float | None:
    """Read one entity-scoped PV/inv power field from Loxone (W)."""
    from ehal.field_registry import apply_loxone_read, loxone_spec
    from ehal.inverter_fields import inv_field_kind
    from ehal.pv_fields import pv_field_kind
    from integrations import loxone_client

    kind = inv_field_kind(field) or pv_field_kind(field)
    if not kind:
        return None
    spec = loxone_spec(kind)
    if spec is None:
        return None
    try:
        raw = loxone_client.fetch_loxone_generic_value(field)
    except Exception:
        return None
    value = apply_loxone_read(raw, spec)
    if value is None:
        return None
    return max(0.0, float(value))


def read_scoped_pv_ha(field: str, *, adapter: Any = None) -> float | None:
    """Read one entity-scoped PV/inv power field from an HA adapter (W)."""
    ha = adapter
    if ha is None:
        try:
            from integrations.ehal_live import get_ha_adapter

            ha = get_ha_adapter()
        except Exception:
            return None
    entities = getattr(getattr(ha, "cfg", None), "entities", None)
    if not isinstance(entities, dict) or field not in entities:
        return None
    try:
        return max(0.0, float(ha._read_mapped_numeric(field)))  # noqa: SLF001
    except Exception:
        return None


def derive_inv_pv_from_pv_systems_w(
    inv: dict,
    pv_systems: list[dict],
    scoped_live: dict[str, Any],
    *,
    fail_partial: bool = True,
) -> float | None:
    """Σ attached ``pv.*.sens_pv_production_active`` when all present; else None.

    When ``fail_partial`` and some but not all attached PV live values are present,
    raise ``ValueError``.
    """
    iid = str(inv.get("id") or "").strip()
    if not iid:
        return None
    attached = _pv_systems_for_inverter(pv_systems, iid)
    if not attached:
        return None
    values: list[float] = []
    missing: list[str] = []
    for pv in attached:
        pid = str(pv.get("id") or "").strip()
        if not pid:
            missing.append("?")
            continue
        key = pv_field(pid, "sens_pv_production_active")
        if key not in scoped_live or scoped_live[key] is None:
            missing.append(pid)
            continue
        values.append(max(0.0, float(scoped_live[key])))
    if missing and values:
        if fail_partial:
            raise ValueError(
                f"Inverter '{iid}': partial PV live maps for derive "
                f"(missing pv systems: {', '.join(missing)}). "
                "Map every attached pv.*.sens_pv_production_active or "
                f"inv.{iid}.sens_inv_power_pv."
            )
        return None
    if missing:
        return None
    return sum(values)


def fill_inv_pv_from_pv_systems(
    scoped_live: dict[str, Any],
    inverters: list[dict],
    pv_systems: list[dict],
    *,
    fail_partial: bool = True,
) -> dict[str, Any]:
    """Copy scoped live and fill missing inv PV from complete per-PV sums."""
    out = dict(scoped_live)
    for inv in inverters:
        if not isinstance(inv, dict):
            continue
        iid = str(inv.get("id") or "").strip()
        if not iid:
            continue
        key = inv_field(iid, "sens_inv_power_pv")
        if key in out and out[key] is not None:
            continue
        derived = derive_inv_pv_from_pv_systems_w(
            inv, pv_systems, out, fail_partial=fail_partial
        )
        if derived is not None:
            out[key] = derived
    return out


def derive_plant_pv_ac_w(
    scoped_live: dict[str, Any],
    inverters: list[dict],
    pv_systems: list[dict],
) -> float:
    """Plant AC PV = Σ grid-tied inv PV · η_inv. Fail loud on incomplete coverage."""
    filled = fill_inv_pv_from_pv_systems(scoped_live, inverters, pv_systems)
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if not eligible:
        raise ValueError(
            "Cannot derive plant sens_pv_production_active: no grid-tied "
            "inverter with PV systems."
        )
    total = 0.0
    missing: list[str] = []
    for inv in eligible:
        iid = str(inv.get("id") or "").strip()
        key = inv_field(iid, "sens_inv_power_pv")
        if key not in filled or filled[key] is None:
            missing.append(iid)
            continue
        total += max(0.0, float(filled[key])) * _eta_inv(inv)
    if missing:
        raise ValueError(
            "Cannot derive plant sens_pv_production_active: incomplete "
            f"grid-tied inverter PV coverage (missing: {', '.join(missing)}). "
            "Map inv.*.sens_inv_power_pv for every grid-tied inverter with PV "
            "(or every attached pv.*.sens_pv_production_active), or map plant PV."
        )
    return total


def with_attributed_plant_pv(
    telemetry: dict[str, Any],
    *,
    scoped_live: dict[str, Any],
    inverters: list[dict],
    pv_systems: list[dict],
    pv_covers_all_inverters: bool = False,
) -> dict[str, Any]:
    """Return telemetry copy with inv←Σpv fills and plant PV derived when missing."""
    from integrations.plant_balance import assert_mapped_plant_pv_coverage

    out = dict(telemetry)
    plant = out.get("sens_pv_production_active")
    # Fail loud on partial PV maps only when plant must be derived.
    fail_partial = plant is None
    filled = fill_inv_pv_from_pv_systems(
        scoped_live, inverters, pv_systems, fail_partial=fail_partial
    )
    # Surface derived inv/pv keys on the working dict for callers/tests (not schema).
    for key, value in filled.items():
        if key.startswith("inv.") and key.endswith(".sens_inv_power_pv"):
            out[key] = value
        elif key.startswith("pv.") and key.endswith(".sens_pv_production_active"):
            out[key] = value
    if plant is None:
        out["sens_pv_production_active"] = derive_plant_pv_ac_w(
            filled, inverters, pv_systems
        )
    else:
        out["sens_pv_production_active"] = max(0.0, float(plant))
        assert_mapped_plant_pv_coverage(
            inverters=inverters,
            pv_systems=pv_systems,
            scoped_live=filled,
            pv_covers_all_inverters=pv_covers_all_inverters,
        )
    return out


def attribute_plant_pv_to_inverters_w(
    plant_w: float,
    *,
    scoped_live: dict[str, Any],
    inverters: list[dict],
    pv_systems: list[dict],
) -> dict[str, float]:
    """Split plant AC W onto grid-tied inverters by live inv PV weights.

    Requires live (or derived) inv PV for every eligible inverter — fail loud.
    Curtailment does not call this yet (forecast weights remain).
    """
    filled = fill_inv_pv_from_pv_systems(scoped_live, inverters, pv_systems)
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if not eligible:
        raise ValueError(
            "attribute_plant_pv_to_inverters_w: no grid-tied inverter with PV."
        )
    weights: dict[str, float] = {}
    missing: list[str] = []
    for inv in eligible:
        iid = str(inv.get("id") or "").strip()
        key = inv_field(iid, "sens_inv_power_pv")
        if key not in filled or filled[key] is None:
            missing.append(iid)
            continue
        # Weight by AC contribution share (η_inv · DC).
        weights[iid] = max(0.0, float(filled[key])) * _eta_inv(inv)
    if missing:
        raise ValueError(
            "attribute_plant_pv_to_inverters_w: incomplete live inv PV "
            f"(missing: {', '.join(missing)})."
        )
    plant = max(0.0, float(plant_w))
    weight_sum = sum(weights.values())
    if weight_sum <= 0.0:
        # Night / zero production: equal split among eligible.
        share = plant / len(weights) if weights else 0.0
        return {iid: share for iid in weights}
    allocated: dict[str, float] = {}
    remaining = plant
    ids = sorted(weights)
    for iid in ids:
        if iid == ids[-1]:
            allocated[iid] = remaining
        else:
            share = plant * (weights[iid] / weight_sum)
            allocated[iid] = share
            remaining = max(0.0, remaining - share)
    return allocated


def collect_scoped_pv_live_from_bindings(
    components: dict,
    *,
    read_value,
) -> dict[str, float]:
    """Read mapped inv/pv PV power fields via ``read_value(field) -> float | None``.

    ``read_value`` is backend-specific (Loxone QID / HA entity). Missing reads
    are omitted (not zero).
    """
    out: dict[str, float] = {}
    inverters = components.get("inverters") if isinstance(components, dict) else []
    pv_systems = components.get("pv_systems") if isinstance(components, dict) else []
    for inv in inverters if isinstance(inverters, list) else []:
        if not isinstance(inv, dict):
            continue
        iid = str(inv.get("id") or "").strip()
        if not iid:
            continue
        field = inv_field(iid, "sens_inv_power_pv")
        bindings = inv.get("ehal_bindings")
        if not binding_mapped(bindings if isinstance(bindings, dict) else None, field):
            continue
        value = read_value(field)
        if value is not None:
            out[field] = max(0.0, float(value))
    for pv in pv_systems if isinstance(pv_systems, list) else []:
        if not isinstance(pv, dict):
            continue
        pid = str(pv.get("id") or "").strip()
        if not pid:
            continue
        field = pv_field(pid, "sens_pv_production_active")
        bindings = pv.get("ehal_bindings")
        if not binding_mapped(bindings if isinstance(bindings, dict) else None, field):
            continue
        value = read_value(field)
        if value is not None:
            out[field] = max(0.0, float(value))
    return out


def load_components_for_attribution() -> dict:
    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return {"inverters": [], "pv_systems": [], "batteries": []}
        doc = load_components_document(path)
        return doc if isinstance(doc, dict) else {
            "inverters": [],
            "pv_systems": [],
            "batteries": [],
        }
    except Exception:
        return {"inverters": [], "pv_systems": [], "batteries": []}
