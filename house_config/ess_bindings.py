"""Primary house-battery entity-scoped ESS binding lookup (no plant-flat aliases)."""
from __future__ import annotations

from ehal.ess_fields import ESS_FIELD_KINDS, binding_address, ess_field
from house_config.powerstation import ehal_mappable_batteries, primary_house_battery


def mappable_batteries(
    batteries: list[dict] | None = None,
) -> list[dict]:
    """EHAL-mappable batteries from arg or components.json."""
    if batteries is not None:
        return ehal_mappable_batteries(
            [b for b in batteries if isinstance(b, dict)]
        )
    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return []
        doc = load_components_document(path)
        raw = doc.get("batteries") if isinstance(doc, dict) else []
        return ehal_mappable_batteries(raw if isinstance(raw, list) else [])
    except Exception:  # noqa: BLE001 — resolve path must stay usable
        return []


def primary_battery(
    batteries: list[dict] | None = None,
) -> dict | None:
    """Primary house battery dict, or None."""
    return primary_house_battery(mappable_batteries(batteries))


def resolve_primary_ess_binding(
    kind: str,
    *,
    batteries: list[dict] | None = None,
) -> str:
    """Merker or Q8 entity-scoped exchange id for the primary house battery.

    Empty Merker with key present → ``ess.{id}.{kind}`` for ``set_*`` / pushable
    reads. Never invents plant-flat ``sens_ess_*`` / ``set_ess_*`` aliases.
    """
    kind_s = str(kind or "").strip()
    if kind_s not in ESS_FIELD_KINDS:
        raise ValueError(f"Unknown ESS EHAL kind '{kind_s}'.")
    bat = primary_battery(batteries)
    if not bat:
        return ""
    bid = str(bat.get("id") or "").strip()
    if not bid:
        return ""
    bindings = bat.get("ehal_bindings")
    bind_map = bindings if isinstance(bindings, dict) else {}
    merker = binding_address(bind_map, bid, kind_s)
    if merker:
        return merker
    field = ess_field(bid, kind_s)
    if field not in bind_map:
        return ""
    from ehal.loxone_push_source import is_pushable_kind

    if kind_s.startswith("set_") or is_pushable_kind(kind_s):
        return field
    return ""


def entity_scoped_battery_bindings(
    batteries: list[dict] | None = None,
) -> dict[str, str]:
    """All non-empty entity-scoped ``ess.{id}.*`` addresses from mappable batteries."""
    out: dict[str, str] = {}
    for bat in mappable_batteries(batteries):
        bid = str(bat.get("id") or "").strip()
        if not bid:
            continue
        bindings = bat.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        for key, value in bindings.items():
            field = str(key or "").strip()
            addr = str(value or "").strip()
            if field and addr and field not in out:
                out[field] = addr
    return out
