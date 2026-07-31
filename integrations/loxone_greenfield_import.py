"""Greenfield Loxone import: Earnie_* Merker + EFM → house_profiles (2.4.n P2)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from house_config.id_slug import slug_id
from integrations.loxone_efm_meters import (
    apply_consumer_imports,
    apply_plant_power_suggestions,
    extract_efm_meters,
    propose_consumer_imports,
)

logger = logging.getLogger(__name__)

# Loxone jdev: 200 = readable, 403 = name known but not readable for this user,
# 404 = unknown. Virtual HTTP In Cmd titles often return 403 without App visualization.
_PRESENT_CODES = frozenset({"200", "403"})

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MAP = _REPO_ROOT / "share" / "loxone" / "greenfield_device_map.json"

_HK_TYPE_BY_KIND = {
    "heatpump": "thermal_annual",
    "ev": "ev",
    "generic": "generic",
    "pool": "thermal_rc",
    "pool_filter": "generic",
}

_DEFAULT_EV_SCHEDULE = {
    "target_soc_percent": 100.0,
    "charging_efficiency": 0.95,
    "forecast_when_absent": True,
    "weekday": {
        "car_available_from_hour": 18,
        "ready_by_hour": 7,
        "daily_rest_soc": 40.0,
    },
    "weekend": {
        "car_available_from_hour": 20,
        "ready_by_hour": 9,
        "daily_rest_soc": 30.0,
    },
}

_DEFAULT_THERMAL_RC = {
    "water_volume_liters": 1000.0,
    "setpoint_c": 28.0,
    "tolerance_c": 1.0,
    "heat_loss_kw_per_k": 0.02,
    "heating_efficiency": 0.99,
}


@dataclass(frozen=True)
class EntityMatch:
    """One plant or consumer proposed from device-map Merker hits."""

    entity_kind: str
    hk_type: str
    group_key: str
    label: str
    bindings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkerProbeResult:
    """Outcome of probing known Merker names via /jdev/sps/io/{name}."""

    present: frozenset[str]
    missing: frozenset[str]
    errors: frozenset[str] = frozenset()
    codes: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": sorted(self.present),
            "missing": sorted(self.missing),
            "errors": sorted(self.errors),
            "codes": dict(self.codes),
        }


@dataclass
class ImportReport:
    matched_markers: list[str] = field(default_factory=list)
    skipped_markers: list[str] = field(default_factory=list)
    created_consumers: list[str] = field(default_factory=list)
    plant_fields: list[str] = field(default_factory=list)
    efm_created: list[str] = field(default_factory=list)
    efm_skipped_typed: list[str] = field(default_factory=list)
    efm_plant_filled: list[str] = field(default_factory=list)
    probed_present: list[str] = field(default_factory=list)
    probed_missing: list[str] = field(default_factory=list)
    profile_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched_markers": list(self.matched_markers),
            "skipped_markers": list(self.skipped_markers),
            "created_consumers": list(self.created_consumers),
            "plant_fields": list(self.plant_fields),
            "efm_created": list(self.efm_created),
            "efm_skipped_typed": list(self.efm_skipped_typed),
            "efm_plant_filled": list(self.efm_plant_filled),
            "probed_present": list(self.probed_present),
            "probed_missing": list(self.probed_missing),
            "profile_id": self.profile_id,
        }


def default_device_map_path() -> Path:
    return _DEFAULT_MAP


def load_device_map(path: str | Path | None = None) -> dict[str, Any]:
    """Load greenfield_device_map.json; raise if markers missing."""
    map_path = Path(path) if path else _DEFAULT_MAP
    if not map_path.is_file():
        raise FileNotFoundError(f"greenfield device map not found: {map_path}")
    raw = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("markers"), list):
        raise ValueError(f"device map '{map_path}' must contain a markers list")
    return raw


def _control_names(doc: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for ctrl in (doc.get("controls") or {}).values():
        if not isinstance(ctrl, dict):
            continue
        name = str(ctrl.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def device_map_marker_names(device_map: dict[str, Any]) -> list[str]:
    """Stable list of exact Merker names from the greenfield device map."""
    names: list[str] = []
    seen: set[str] = set()
    for marker in device_map.get("markers") or []:
        if not isinstance(marker, dict):
            continue
        name = str(marker.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def probe_marker_names(
    names: list[str] | tuple[str, ...] | set[str],
    *,
    host: str,
    username: str,
    password: str,
    timeout_sec: float = 5.0,
) -> MarkerProbeResult:
    """Probe /jdev/sps/io/{name}; treat LL.Code 200 or 403 as present, 404 as missing."""
    ip = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    ip = ip.split("/")[0]
    if not ip:
        raise ValueError("LOXONE_IP is empty")
    auth = HTTPBasicAuth(username, password)
    present: set[str] = set()
    missing: set[str] = set()
    errors: set[str] = set()
    codes: dict[str, str] = {}
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        url = f"http://{ip}/jdev/sps/io/{quote(name, safe='')}"
        try:
            response = requests.get(url, auth=auth, timeout=timeout_sec)
            payload = response.json() if response.content else {}
            ll = payload.get("LL") if isinstance(payload, dict) else {}
            code = str((ll or {}).get("Code") or response.status_code)
        except (requests.RequestException, OSError, ValueError, TypeError) as exc:
            logger.warning("marker probe failed for %s: %s", name, exc)
            errors.add(name)
            codes[name] = "error"
            continue
        codes[name] = code
        if code in _PRESENT_CODES:
            present.add(name)
        elif code == "404":
            missing.add(name)
        else:
            errors.add(name)
    return MarkerProbeResult(
        present=frozenset(present),
        missing=frozenset(missing),
        errors=frozenset(errors),
        codes=codes,
    )


def probe_device_map_markers(
    device_map: dict[str, Any] | None = None,
    *,
    host: str,
    username: str,
    password: str,
    timeout_sec: float = 5.0,
) -> MarkerProbeResult:
    """Probe every exact name in greenfield_device_map.json."""
    dmap = device_map if device_map is not None else load_device_map()
    return probe_marker_names(
        device_map_marker_names(dmap),
        host=host,
        username=username,
        password=password,
        timeout_sec=timeout_sec,
    )


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
        bindings.setdefault("flex.power_name", io_name)


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
        matches.append(
            EntityMatch(
                entity_kind=str(bucket["entity_kind"]),
                hk_type=str(bucket["hk_type"]),
                group_key=group_key,
                label=str(bucket["label"]),
                bindings=dict(bucket["bindings"]),
            )
        )
    return matches, report


def _profiles_as_dict(house_doc: dict) -> dict[str, dict]:
    raw = house_doc.get("profiles")
    if isinstance(raw, dict):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        out: dict[str, dict] = {}
        for item in raw:
            if isinstance(item, dict) and str(item.get("id") or "").strip():
                pid = str(item["id"]).strip()
                out[pid] = dict(item)
        return out
    return {}


def ensure_live_profile(house_doc: dict) -> tuple[dict, str]:
    """Ensure a usable profile exists; return (house, profile_id)."""
    house = dict(house_doc)
    profiles = _profiles_as_dict(house)
    if not profiles:
        profiles = {
            "live": {
                "id": "live",
                "label": "Live",
                "annual_kwh": 0.0,
                "latitude": 48.0,
                "longitude": 16.0,
                "land": "AT",
                "consumers": [],
            }
        }
        house["profiles"] = profiles
        return house, "live"
    house["profiles"] = profiles
    if "live" in profiles:
        return house, "live"
    return house, next(iter(profiles))


def _stub_consumer(*, consumer_id: str, label: str, hk_type: str, bindings: dict[str, str]) -> dict:
    consumer: dict[str, Any] = {
        "id": consumer_id,
        "label": label,
        "type": hk_type,
        "nominal_power_kw": 1.0,
        "ehal_bindings": dict(bindings),
    }
    if hk_type == "generic":
        consumer["earnie_role"] = "known"
        consumer["use_profile_csv"] = False
    elif hk_type == "ev":
        consumer["battery_capacity_kwh"] = 50.0
        consumer["min_power_kw"] = 1.4
        consumer["charging_schedule"] = dict(_DEFAULT_EV_SCHEDULE)
    elif hk_type == "thermal_annual":
        consumer["living_area_m2"] = 0.0
        consumer["building_class"] = 3
        consumer["heat_pump_type"] = "luft"
        consumer["persons"] = 2
    elif hk_type == "thermal_rc":
        consumer["thermal_rc"] = dict(_DEFAULT_THERMAL_RC)
    return consumer


def apply_typed_matches(
    house_doc: dict,
    matches: list[EntityMatch],
    *,
    profile_id: str,
    report: ImportReport | None = None,
) -> dict:
    """Write plant bindings and create typed consumers from Merker matches."""
    house = dict(house_doc)
    profiles = _profiles_as_dict(house)
    if profile_id not in profiles:
        raise ValueError(f"profile_id '{profile_id}' missing from house profiles")
    profile = dict(profiles[profile_id])
    consumers = [dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)]
    taken = {str(c.get("id") or "").strip() for c in consumers if str(c.get("id") or "").strip()}
    by_id = {str(c.get("id") or ""): c for c in consumers if str(c.get("id") or "")}
    rep = report or ImportReport()

    plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
    plant_bindings = (
        dict(plant["ehal_bindings"]) if isinstance(plant.get("ehal_bindings"), dict) else {}
    )

    needs_geo = False
    for match in matches:
        if match.entity_kind == "plant":
            plant_bindings.update(match.bindings)
            rep.plant_fields = sorted(match.bindings)
            continue
        cid = slug_id(match.label, existing=taken)
        taken.add(cid)
        hk_type = match.hk_type or "generic"
        if hk_type in {"thermal_annual", "thermal_rc"}:
            needs_geo = True
        consumer = _stub_consumer(
            consumer_id=cid,
            label=match.label,
            hk_type=hk_type,
            bindings=match.bindings,
        )
        by_id[cid] = consumer
        rep.created_consumers.append(cid)
    if needs_geo:
        if profile.get("latitude") is None:
            profile["latitude"] = 48.0
        if profile.get("longitude") is None:
            profile["longitude"] = 16.0
        if not str(profile.get("land") or "").strip():
            profile["land"] = "AT"

    if plant_bindings:
        plant["ehal_bindings"] = plant_bindings
        house["plant"] = plant
    profile["consumers"] = list(by_id.values())
    house["profiles"] = {**profiles, profile_id: profile}
    return house


def _bound_power_addresses(consumers: list[dict]) -> set[str]:
    bound: set[str] = set()
    for consumer in consumers:
        bindings = consumer.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        for key in ("flex.power_name", "sens_evcs_active_power"):
            value = str(bindings.get(key) or "").strip()
            if value:
                bound.add(value.casefold())
    return bound


def merge_efm(
    house_doc: dict,
    doc: dict[str, Any],
    *,
    profile_id: str,
    report: ImportReport | None = None,
) -> dict:
    """Apply EFM meters; skip loads whose power name is already typed-bound."""
    house = dict(house_doc)
    profiles = _profiles_as_dict(house)
    profile = dict(profiles.get(profile_id) or {})
    consumers = [dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)]
    house["profiles"] = {**profiles, profile_id: profile}
    rep = report or ImportReport()

    candidates = extract_efm_meters(doc)
    proposals = propose_consumer_imports(candidates, consumers)
    bound_power = _bound_power_addresses(consumers)
    selected_consumers: list[dict[str, Any]] = []
    selected_plant: list[dict[str, Any]] = []

    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    plant_bindings = (
        dict(plant.get("ehal_bindings"))
        if isinstance(plant.get("ehal_bindings"), dict)
        else {}
    )

    for prop in proposals:
        row = prop.as_dict()
        if prop.action in {"create", "match"}:
            power = str(prop.power_address or prop.name or "").strip()
            if power.casefold() in bound_power:
                rep.efm_skipped_typed.append(power)
                continue
            row["bind_power"] = True
            selected_consumers.append(row)
            if prop.action == "create":
                rep.efm_created.append(str(prop.consumer_id or prop.name))
        elif prop.action == "skip_plant":
            field = str(prop.plant_field or "").strip()
            if not field:
                continue
            if str(plant_bindings.get(field) or "").strip():
                continue
            row["bind_plant"] = True
            selected_plant.append(row)
            rep.efm_plant_filled.append(field)

    if selected_consumers:
        house = apply_consumer_imports(
            house, profile_id=profile_id, selected=selected_consumers
        )
    if selected_plant:
        house = apply_plant_power_suggestions(house, selected=selected_plant)
    return house


def run_greenfield_import(
    doc: dict[str, Any],
    house_doc: dict | None = None,
    *,
    profile_id: str | None = None,
    device_map: dict[str, Any] | None = None,
    probe_host: str | None = None,
    probe_username: str | None = None,
    probe_password: str | None = None,
    probe_timeout_sec: float = 5.0,
) -> dict[str, Any]:
    """Orchestrate Merker match + EFM merge; return house_doc + report.

    When ``probe_host`` / credentials are set, device-map markers and LoxAPP3
    Earnie_* names are probed via ``/jdev/sps/io/{name}`` and unioned.
    """
    dmap = device_map if device_map is not None else load_device_map()
    house, resolved_id = ensure_live_profile(house_doc or {"profiles": []})
    if profile_id:
        profiles = _profiles_as_dict(house)
        if profile_id not in profiles:
            raise ValueError(f"profile_id '{profile_id}' missing from house profiles")
        resolved_id = profile_id
    extra: set[str] | None = None
    probe_result: MarkerProbeResult | None = None
    if probe_host and probe_username is not None and probe_password is not None:
        candidates = probe_candidate_names(doc, dmap)
        probe_result = probe_marker_names(
            candidates,
            host=probe_host,
            username=probe_username,
            password=probe_password,
            timeout_sec=probe_timeout_sec,
        )
        extra = set(probe_result.present)
    matches, report = match_controls(doc, dmap, extra_names=extra)
    report.profile_id = resolved_id
    if probe_result is not None:
        report.probed_present = sorted(probe_result.present)
        report.probed_missing = sorted(probe_result.missing)
    house = apply_typed_matches(house, matches, profile_id=resolved_id, report=report)
    house = merge_efm(house, doc, profile_id=resolved_id, report=report)
    out: dict[str, Any] = {"house_doc": house, "report": report.as_dict(), "matches": matches}
    if probe_result is not None:
        out["probe"] = probe_result.as_dict()
    return out


def apply_and_save(
    doc: dict[str, Any],
    house_doc: dict | None = None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Run import and persist via ui.house_config_io.save_house_profiles."""
    from ui.house_config_io import save_house_profiles

    result = run_greenfield_import(doc, house_doc, profile_id=profile_id)
    save_house_profiles(result["house_doc"])
    return result
