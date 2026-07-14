"""Migrate NAS prod flexible_consumers / appliances into house_profiles.json (1.95c)."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROFILE_ID = "example_efh"

SWIMSPA_THERMAL_BINDINGS = {
    "loxone_outputs": {"enable_name": "Ernie_SwimSpa_Freigabe"},
    "loxone_inputs": {
        "power_name": "Ernie_Swim-Spa-P_act",
        "subtract_consumer_ids": ["swimspa_filter"],
    },
    "thermal_control": {
        "loxone": {"heating_active_name": "homie_bwa_spa_heating"},
        "history_logs": {
            "heating_active_csv": "",
            "filter_active_csv": "",
        },
    },
}


def _load_json(path: Path) -> dict:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot read {path}")


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _flex_by_id(config: dict) -> dict[str, dict]:
    return {
        str(entry["id"]): entry
        for entry in config.get("flexible_consumers", [])
        if isinstance(entry, dict) and entry.get("id")
    }


def _build_ev_consumer(eauto: dict, eauto_milp: dict | None) -> dict:
    sched = deepcopy(eauto.get("charging_schedule") or {})
    if eauto_milp:
        sched["milp"] = dict(eauto_milp)
    return {
        "id": "ev",
        "legacy_id": "eauto",
        "label": str(eauto.get("name", "E-Auto")),
        "type": "ev",
        "nominal_power_kw": float(eauto.get("nominal_power_kw", 3.5)),
        "min_power_kw": float(eauto.get("min_power_kw", 0.0) or 0.0),
        "min_on_quarterhours": int(eauto.get("min_on_quarterhours", 4) or 4),
        "battery_capacity_kwh": 17.0,
        "charging_schedule": sched,
    }


def _build_swimspa_consumer(swimspa: dict) -> dict:
    thermal = swimspa.get("thermal_control") or {}
    return {
        "id": "swimspa",
        "legacy_id": "swimspa",
        "label": str(swimspa.get("name", "SwimSpa")),
        "type": "thermal_rc",
        "nominal_power_kw": float(swimspa.get("nominal_power_kw", 2.8)),
        "min_on_quarterhours": int(swimspa.get("min_on_quarterhours", 8) or 8),
        "water_volume_liters": float(thermal.get("water_volume_liters", 6000)),
        "setpoint_c": float(thermal.get("setpoint_c", 36.5)),
        "tolerance_c": float(thermal.get("tolerance_c", 1.0)),
        "heat_loss_kw_per_k": float(thermal.get("heat_loss_kw_per_k", 0.1)),
        "heating_efficiency": float(thermal.get("heating_efficiency", 0.95)),
    }


def _build_wp_consumer(waermepumpe: dict, wp_profile: dict | None) -> dict:
    base = wp_profile or {}
    return {
        "id": "wp_heating",
        "legacy_id": "waermepumpe",
        "label": str(waermepumpe.get("name", "Wärmepumpe")),
        "type": "thermal_annual",
        "nominal_power_kw": float(waermepumpe.get("nominal_power_kw", 1.6)),
        **{
            key: base[key]
            for key in (
                "living_area_m2",
                "building_class",
                "heat_pump_type",
                "persons",
                "target_temp_c",
                "heating_limit_c",
                "solar_thermal_area_m2",
                "solar_thermal_tilt_deg",
                "solar_thermal_azimuth_deg",
                "hwb_kwh_m2",
            )
            if key in base
        },
    }


def _generic_from_appliance(appliance: dict) -> dict:
    default_power = float(appliance.get("default_power_kw", 1.0))
    default_runtime = float(appliance.get("default_runtime_h", 1.0))
    return {
        "id": str(appliance["id"]),
        "label": str(appliance.get("name", appliance["id"])),
        "type": "generic",
        "nominal_power_kw": default_power,
        "annual_kwh": round(default_power * default_runtime * 52, 1),
        "schedule": {
            "runs_per_week": 2,
            "duration_h": default_runtime,
            "start_hour": 12,
            "start_shift_h": 4.0,
        },
        "appliance_recommendation": {
            "power_source": str(appliance.get("power_source", "manual")),
            "loxone_power_name": str(appliance.get("loxone_power_name", "")),
            "default_power_kw": default_power,
            "default_runtime_h": default_runtime,
        },
    }


def _order_migrated_consumers(consumers: list[dict]) -> list[dict]:
    """thermal_annual muss Verbraucher 1 sein (profiles_store-Regel)."""
    thermal = [consumer for consumer in consumers if consumer.get("type") == "thermal_annual"]
    others = [consumer for consumer in consumers if consumer.get("type") != "thermal_annual"]
    return thermal + others


def migrate_prod_consumers(
    config: dict,
    house_profiles: dict,
    *,
    profile_id: str = PROFILE_ID,
    strip_flex_ids: tuple[str, ...] = ("eauto", "swimspa", "swimspa_filter", "waermepumpe"),
) -> tuple[dict, dict, list[dict]]:
    """Return updated (config, house_profiles, migration_status_rows)."""
    config_out = deepcopy(config)
    profiles_out = deepcopy(house_profiles)
    profiles = profiles_out.setdefault("profiles", [])
    if isinstance(profiles, dict):
        profile = profiles.setdefault(profile_id, {"id": profile_id, "consumers": []})
        consumers: list[dict] = profile.setdefault("consumers", [])
    else:
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        if profile is None:
            profile = {"id": profile_id, "label": profile_id, "annual_kwh": 0.0, "consumers": []}
            profiles.append(profile)
        consumers = profile.setdefault("consumers", [])

    flex = _flex_by_id(config)
    status: list[dict] = []
    existing_ids = {str(c["id"]) for c in consumers if c.get("id")}
    consumers = [c for c in consumers if str(c.get("id")) != "herd_kochen"]
    existing_ids.discard("herd_kochen")

    wp_existing = next((c for c in consumers if c.get("id") == "wp_heating"), None)

    if "eauto" in flex:
        ev = _build_ev_consumer(flex["eauto"], config.get("eauto_milp"))
        consumers = [c for c in consumers if c.get("id") != "ev"]
        consumers.append(ev)
        status.append({"id": "ev", "legacy_id": "eauto", "phase": "1.95c", "status": "migrated"})
    if "swimspa" in flex:
        consumers = [c for c in consumers if c.get("id") != "swimspa"]
        consumers.append(_build_swimspa_consumer(flex["swimspa"]))
        status.append({"id": "swimspa", "legacy_id": "swimspa", "phase": "1.95b", "status": "migrated"})
    if "swimspa_filter" in flex:
        status.append(
            {
                "id": "swimspa_filter",
                "phase": "1.95b",
                "status": "bridge-only",
                "note": "planning_filter_to_milp defaults",
            }
        )
    if "waermepumpe" in flex:
        consumers = [c for c in consumers if c.get("id") != "wp_heating"]
        consumers.append(_build_wp_consumer(flex["waermepumpe"], wp_existing))
        status.append(
            {
                "id": "wp_heating",
                "legacy_id": "waermepumpe",
                "phase": "1.97",
                "status": "migrated",
            }
        )

    for appliance in config.get("appliances", []):
        if not isinstance(appliance, dict) or not appliance.get("id"):
            continue
        aid = str(appliance["id"])
        consumers = [c for c in consumers if c.get("id") != aid]
        consumers.append(_generic_from_appliance(appliance))
        status.append({"id": aid, "phase": "1.96d", "status": "migrated"})

    if config_out.get("appliances"):
        config_out.pop("appliances", None)
        status.append(
            {
                "id": "appliances[]",
                "phase": "1.96d",
                "status": "retired-config-block",
            }
        )

    profile["consumers"] = _order_migrated_consumers(consumers)
    if isinstance(profiles, dict):
        profiles[profile_id] = profile

    flex_list = config_out.get("flexible_consumers", [])
    config_out["flexible_consumers"] = [
        entry
        for entry in flex_list
        if str(entry.get("id", "")) not in set(strip_flex_ids)
    ]
    return config_out, profiles_out, status


def _render_migration_review(status_rows: list[dict]) -> str:
    lines = [
        "## Flex consumer migration (1.95c script)",
        "",
        "| Canonical | legacy_id | Phase | Status | Notes |",
        "|-----------|-----------|-------|--------|-------|",
    ]
    for row in status_rows:
        lines.append(
            f"| `{row.get('id', '')}` | `{row.get('legacy_id', '')}` | "
            f"{row.get('phase', '')} | {row.get('status', '')} | "
            f"{row.get('blocker') or row.get('note') or ''} |"
        )
    lines.append("")
    lines.append("Filter bridge defaults: `SWIMSPA_FILTER_BRIDGE_DEFAULTS` in planning_flex_bridge.py")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate NAS flex consumers to house profile.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--house-profiles", type=Path, required=True)
    parser.add_argument("--profile-id", default=PROFILE_ID)
    parser.add_argument("--migration-review", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = _load_json(args.config)
    profiles_doc = _load_json(args.house_profiles)
    config_out, profiles_out, status = migrate_prod_consumers(
        config,
        profiles_doc,
        profile_id=args.profile_id,
    )
    if args.dry_run:
        print(json.dumps({"status": status}, indent=2))
        return
    _write_json(args.config, config_out)
    _write_json(args.house_profiles, profiles_out)
    if args.migration_review:
        review_path = args.migration_review
        existing = review_path.read_text(encoding="utf-8") if review_path.is_file() else ""
        marker = "## Flex consumer migration"
        if marker in existing:
            head = existing.split(marker, 1)[0].rstrip()
            review_path.write_text(head + "\n\n" + _render_migration_review(status), encoding="utf-8")
        else:
            review_path.write_text(existing.rstrip() + "\n\n" + _render_migration_review(status), encoding="utf-8")
    print(f"Migrated {len(status)} consumer rows -> profile '{args.profile_id}'")


if __name__ == "__main__":
    main()
