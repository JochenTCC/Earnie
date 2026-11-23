"""Scenario references the form cannot offer (deleted entry, or not selectable here).

Split from ``ui.scenario_form_helpers``, which re-exports every name here.
"""
from __future__ import annotations

# Reference fields of a scenario: single selects and lists.
_REF_SELECT_FIELDS = ("house_profile_id", "import_tariff_id", "export_tariff_id")
_REF_LIST_FIELDS = ("battery_ids", "pv_system_ids")
REF_FIELD_LABELS_DE = {
    "house_profile_id": "Hausprofil",
    "import_tariff_id": "Bezugstarif",
    "export_tariff_id": "Einspeisetarif",
    "battery_ids": "Batterie",
    "pv_system_ids": "PV-Feld",
}


def _stored_ref_ids(stored_settings: dict, field: str) -> list[str]:
    settings = stored_settings or {}
    if field == "battery_ids" and "battery_ids" not in settings and "battery_id" in settings:
        raw = [settings.get("battery_id")]
    else:
        raw = settings.get(field)
    if field in _REF_LIST_FIELDS:
        items = raw if isinstance(raw, list) else []
    else:
        items = [raw]
    out: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def missing_scenario_refs(
    stored_settings: dict,
    *,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> dict[str, list[str]]:
    """Referenced ids the form cannot offer (deleted entry, or not selectable here)."""
    from house_config.tariffs_store import ensure_user_fixed_option

    known = {
        "house_profile_id": {str(pid) for pid in profiles},
        "import_tariff_id": {
            str(t.get("id")) for t in ensure_user_fixed_option(list(import_tariffs))
        },
        "export_tariff_id": {
            str(t.get("id")) for t in ensure_user_fixed_option(list(export_tariffs))
        },
        "battery_ids": {str(b.get("id")) for b in batteries},
        "pv_system_ids": {str(p.get("id")) for p in pv_systems},
    }
    missing: dict[str, list[str]] = {}
    for field, ids in known.items():
        absent = [ref for ref in _stored_ref_ids(stored_settings, field) if ref not in ids]
        if absent:
            missing[field] = absent
    return missing


def carry_missing_refs(settings: dict, missing: dict[str, list[str]]) -> dict:
    """Keep references the form cannot show, so opening or saving does not drop them.

    A select keeps its missing id while it shows no choice; picking another entry replaces it.
    List fields keep their missing ids; ``drop_missing_refs`` removes them on request.
    """
    out = dict(settings)
    for field, ids in missing.items():
        if field in _REF_SELECT_FIELDS:
            if not str(out.get(field) or "").strip():
                out[field] = ids[0]
            continue
        current = list(out.get(field) or [])
        out[field] = current + [ref for ref in ids if ref not in current]
    return out


def drop_missing_refs(stored_settings: dict, missing: dict[str, list[str]]) -> dict:
    """Stored settings without the missing references (explicit user action)."""
    out = dict(stored_settings or {})
    if "battery_id" in out and "battery_ids" not in out:
        bid = str(out.pop("battery_id") or "").strip()
        out["battery_ids"] = [bid] if bid else []
    for field, ids in missing.items():
        if field in _REF_SELECT_FIELDS:
            if str(out.get(field) or "").strip() in ids:
                out.pop(field, None)
            continue
        kept = [ref for ref in (out.get(field) or []) if str(ref or "").strip() not in ids]
        if kept:
            out[field] = kept
        else:
            out.pop(field, None)
    return out
