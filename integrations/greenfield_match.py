"""Control matching for Loxone greenfield house-profile import."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from house_config.id_slug import slug_id

# Mirrored from loxone_greenfield_import for match helpers (keep in sync).
_HK_TYPE_BY_KIND = {
    "heatpump": "thermal_annual",
    "ev": "ev",
    "generic": "generic",
    "pool": "thermal_rc",
    "pool_filter": "generic",
}

_GROUP_ALIASES = {
    "Earnie_WP_": "Earnie_Waermepumpe_",
}


def _control_names(doc: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for ctrl in (doc.get("controls") or {}).values():
        if not isinstance(ctrl, dict):
            continue
        name = str(ctrl.get("name") or "").strip()
        if name:
            names.add(name)
    return names


@dataclass(frozen=True)
class EntityMatch:
    """One plant or consumer proposed from device-map Merker hits."""

    entity_kind: str
    hk_type: str
    group_key: str
    label: str
    bindings: dict[str, str] = field(default_factory=dict)

def _prefix_meta(device_map: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in device_map.get("prefix_groups") or []:
        if not isinstance(row, dict):
            continue
        prefix = str(row.get("prefix") or "").strip()
        if not prefix:
            continue
        out[prefix] = {
            "entity_kind": str(row.get("entity_kind") or "").strip(),
            "hk_type": str(row.get("hk_type") or "").strip(),
            "default_label": str(row.get("default_label") or prefix).strip(),
        }
    return out


def _resolve_hk_type(entity_kind: str, marker_hk: str, prefix_meta: dict) -> str:
    if marker_hk == "thermal":
        return "thermal_rc"
    if marker_hk in {"generic", "ev", "thermal_annual", "thermal_rc"}:
        return marker_hk
    return _HK_TYPE_BY_KIND.get(entity_kind, "generic")


def _present_index(names: set[str]) -> dict[str, str]:
    """casefold → first-seen original Miniserver spelling."""
    index: dict[str, str] = {}
    for name in names:
        key = name.casefold()
        if key not in index:
            index[key] = name
    return index


def _signal_tails_by_prefix(
    device_map: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """prefix → {tail.casefold(): ehal_field} from exact group markers."""
    prefixes = _prefix_meta(device_map)
    tails: dict[str, dict[str, str]] = {p: {} for p in prefixes}
    for marker in device_map.get("markers") or []:
        if not isinstance(marker, dict):
            continue
        name = str(marker.get("name") or "").strip()
        field = marker.get("ehal_field")
        if not name or field is None:
            continue
        ehal = str(field).strip()
        if not ehal:
            continue
        group = str(marker.get("group") or "").strip()
        if not group or group not in tails:
            continue
        if not name.casefold().startswith(group.casefold()):
            continue
        tail = name[len(group) :]
        if tail:
            tails[group][tail.casefold()] = ehal
    return tails


def _sorted_prefixes(prefixes: dict[str, dict[str, str]]) -> list[str]:
    return sorted(prefixes.keys(), key=len, reverse=True)


def earnie_names_from_doc(doc: dict[str, Any], device_map: dict[str, Any]) -> list[str]:
    """LoxAPP3 control names matching Earnie_ or any greenfield prefix."""
    prefixes = _sorted_prefixes(_prefix_meta(device_map))
    prefix_folds = [p.casefold() for p in prefixes]
    out: list[str] = []
    seen: set[str] = set()
    for name in _control_names(doc):
        low = name.casefold()
        if low in seen:
            continue
        if low.startswith("earnie_") or any(low.startswith(p) for p in prefix_folds):
            seen.add(low)
            out.append(name)
    return out


def probe_candidate_names(doc: dict[str, Any], device_map: dict[str, Any]) -> list[str]:
    """Exact device-map markers plus Earnie_* names from LoxAPP3."""
    names: list[str] = []
    seen: set[str] = set()
    for name in device_map_marker_names(device_map) + earnie_names_from_doc(doc, device_map):
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _ensure_group_bucket(
    groups: dict[str, dict[str, Any]],
    *,
    group_key: str,
    entity_kind: str,
    hk_type: str,
    label: str,
) -> dict[str, Any]:
    return groups.setdefault(
        group_key,
        {
            "entity_kind": entity_kind,
            "hk_type": hk_type,
            "label": label,
            "bindings": {},
        },
    )


def _bind_field(bucket: dict[str, Any], field: str, io_name: str) -> None:
    bindings = bucket["bindings"]
    if field not in bindings:
        bindings[field] = io_name
    if field == "sens_evcs_active_power":
        bindings.setdefault("flex.sens_power_act", io_name)


def _collapse_alias_groups(groups: dict[str, dict[str, Any]]) -> None:
    """Merge legacy heatpump groups into the canonical Earnie_Waermepumpe_ bucket."""
    for alias_key, canonical_key in _GROUP_ALIASES.items():
        if alias_key not in groups:
            continue
        alias_bucket = groups.pop(alias_key)
        alias_bindings = dict(alias_bucket.get("bindings") or {})
        if canonical_key in groups:
            target = groups[canonical_key]
            for field, io_name in alias_bindings.items():
                target["bindings"].setdefault(field, io_name)
            continue
        groups[canonical_key] = {
            "entity_kind": alias_bucket.get("entity_kind") or "heatpump",
            "hk_type": alias_bucket.get("hk_type") or "thermal_annual",
            "label": alias_bucket.get("label") or "Wärmepumpe",
            "bindings": alias_bindings,
        }


def _match_exact_markers(
    device_map: dict[str, Any],
    *,
    present_by_fold: dict[str, str],
    prefixes: dict[str, dict[str, str]],
    plant_bindings: dict[str, str],
    groups: dict[str, dict[str, Any]],
    report: ImportReport,
    claimed: set[str],
) -> None:
    for marker in device_map.get("markers") or []:
        if not isinstance(marker, dict):
            continue
        map_name = str(marker.get("name") or "").strip()
        if not map_name:
            continue
        io_name = present_by_fold.get(map_name.casefold())
        if not io_name:
            continue
        ehal_field = marker.get("ehal_field")
        if ehal_field is None:
            report.skipped_markers.append(io_name)
            claimed.add(io_name.casefold())
            continue
        field = str(ehal_field).strip()
        if not field:
            report.skipped_markers.append(io_name)
            claimed.add(io_name.casefold())
            continue
        report.matched_markers.append(io_name)
        claimed.add(io_name.casefold())
        kind = str(marker.get("entity_kind") or "").strip()
        if kind == "plant":
            plant_bindings.setdefault(field, io_name)
            continue
        group_key = str(marker.get("group") or "").strip() or kind
        meta = prefixes.get(group_key) or {}
        hk_type = _resolve_hk_type(
            kind,
            str(marker.get("hk_type") or meta.get("hk_type") or ""),
            prefixes,
        )
        bucket = _ensure_group_bucket(
            groups,
            group_key=group_key,
            entity_kind=kind or meta.get("entity_kind") or "generic",
            hk_type=hk_type,
            label=str(meta.get("default_label") or group_key.rstrip("_")),
        )
        _bind_field(bucket, field, io_name)


def _parse_prefix_remainder(
    name: str,
    prefixes: dict[str, dict[str, str]],
    tails_by_prefix: dict[str, dict[str, str]],
) -> tuple[str, str, str, str] | None:
    """Return (prefix, slug_token, ehal_field, group_key) or None."""
    low = name.casefold()
    for prefix in _sorted_prefixes(prefixes):
        pfold = prefix.casefold()
        if not low.startswith(pfold):
            continue
        remainder = name[len(prefix) :]
        rem_fold = remainder.casefold()
        tails = tails_by_prefix.get(prefix) or {}
        for tail_fold in sorted(tails.keys(), key=len, reverse=True):
            field = tails[tail_fold]
            if rem_fold == tail_fold:
                return prefix, "", field, prefix
            if rem_fold.endswith("_" + tail_fold) and len(rem_fold) > len(tail_fold) + 1:
                slug = remainder[: -(len(tail_fold) + 1)]
                if not slug or "_" in slug:
                    continue
                group_key = f"{prefix}{slug.casefold()}"
                return prefix, slug, field, group_key
    return None


def _match_slug_names(
    present_by_fold: dict[str, str],
    *,
    prefixes: dict[str, dict[str, str]],
    tails_by_prefix: dict[str, dict[str, str]],
    groups: dict[str, dict[str, Any]],
    report: ImportReport,
    claimed: set[str],
) -> None:
    for fold, io_name in present_by_fold.items():
        if fold in claimed:
            continue
        parsed = _parse_prefix_remainder(io_name, prefixes, tails_by_prefix)
        if parsed is None:
            continue
        prefix, slug, field, group_key = parsed
        meta = prefixes.get(prefix) or {}
        kind = str(meta.get("entity_kind") or "generic")
        hk_type = _resolve_hk_type(kind, str(meta.get("hk_type") or ""), prefixes)
        label = slug if slug else str(meta.get("default_label") or prefix.rstrip("_"))
        bucket = _ensure_group_bucket(
            groups,
            group_key=group_key,
            entity_kind=kind,
            hk_type=hk_type,
            label=label,
        )
        _bind_field(bucket, field, io_name)
        report.matched_markers.append(io_name)
        claimed.add(fold)


def match_controls(
    doc: dict[str, Any],
    device_map: dict[str, Any],
    *,
    extra_names: set[str] | frozenset[str] | None = None,
) -> tuple[list[EntityMatch], ImportReport]:
    """Match controls: case-insensitive exact map names + Prefix+Slug groups."""
    from integrations.loxone_greenfield_import import ImportReport

    present = _control_names(doc)
    if extra_names:
        present |= {str(n).strip() for n in extra_names if str(n).strip()}
    present_by_fold = _present_index(present)
    prefixes = _prefix_meta(device_map)
    tails_by_prefix = _signal_tails_by_prefix(device_map)
    report = ImportReport()
    plant_bindings: dict[str, str] = {}
    groups: dict[str, dict[str, Any]] = {}
    claimed: set[str] = set()
    _match_exact_markers(
        device_map,
        present_by_fold=present_by_fold,
        prefixes=prefixes,
        plant_bindings=plant_bindings,
        groups=groups,
        report=report,
        claimed=claimed,
    )
    _match_slug_names(
        present_by_fold,
        prefixes=prefixes,
        tails_by_prefix=tails_by_prefix,
        groups=groups,
        report=report,
        claimed=claimed,
    )
    _collapse_alias_groups(groups)
    matches: list[EntityMatch] = []
    if plant_bindings:
        matches.append(
            EntityMatch(
                entity_kind="plant",
                hk_type="",
                group_key="plant",
                label="Plant",
                bindings=dict(plant_bindings),
            )
        )
    for group_key, bucket in groups.items():
        from ehal.flex_fields import expand_flex_bindings

        label = str(bucket["label"])
        # Expand role stubs using the same slug apply_typed_matches will use.
        proposed_id = slug_id(label)
        matches.append(
            EntityMatch(
                entity_kind=str(bucket["entity_kind"]),
                hk_type=str(bucket["hk_type"]),
                group_key=group_key,
                label=label,
                bindings=expand_flex_bindings(dict(bucket["bindings"]), proposed_id),
            )
        )
    return matches, report


