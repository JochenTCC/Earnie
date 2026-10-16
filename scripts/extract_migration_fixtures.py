"""Extract + scrub Earnie-env-home pack snapshots for ConfigMigration P0.

Usage:
  python -m scripts.extract_migration_fixtures --env-home PATH
  python -m scripts.extract_migration_fixtures --env-home PATH --out tests/fixtures/migration

Never commit raw private content. This script scrubs labels, geo, Merker/entity
values, and path refs before writing public fixtures.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PACK_FILES = (
    "config.json",
    "house_profiles.json",
    "components.json",
    "deviation_rules.json",
    "backtesting_scenarios.json",
    "grid_fees.json",
)

# (fixture_folder, git_sha) — chronological “before” snapshots
SNAPSHOTS: tuple[tuple[str, str], ...] = (
    ("v3_last", "7269b26"),
    ("v4_pre_quellenwahl", "760ab99"),
    ("v4_pre_inverter_gridfee", "515ea9a"),
    ("v4_pre_conversion", "49fc6a2"),
    ("v4_pre_topology", "c0cd597"),
)

V1_NEST_SHA = "26c9daf"
PLACEHOLDER_LAT = 47.0
PLACEHOLDER_LON = 10.0
PLACEHOLDER_PROFILE_LABEL = "House A"
PLACEHOLDER_PROFILE_ID = "profile_a"

_BINDING_VALUE_KEYS = frozenset(
    {
        "ehal_bindings",
        "loxone_blocks",
        "loxone_inputs",
        "loxone_outputs",
        "swimspa_filter_bindings",
    }
)
_PATHISH_KEYS = frozenset(
    {
        "historical_csv_source",
        "pv_profile_csv",
        "total_profile_csv",
        "grid_profile_csv",
        "battery_profile_csv",
        "log_filename",
        "pv_tuning_log_file",
    }
)
_LABEL_REWRITES = (
    (re.compile(r"Schützenstraße\s*7c", re.I), PLACEHOLDER_PROFILE_LABEL),
    (re.compile(r"Schuetzenstrasse\s*7c", re.I), PLACEHOLDER_PROFILE_LABEL),
)


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _git_show(env_home: Path, sha: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(env_home), "show", f"{sha}:config/{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _load_pack(env_home: Path, sha: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in PACK_FILES:
        raw = _git_show(env_home, sha, name)
        if raw is None:
            continue
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            raise SystemExit(f"{sha}:config/{name}: expected JSON object")
        out[name] = doc
    if "house_profiles.json" not in out and "components.json" not in out:
        raise SystemExit(f"{sha}: no pack JSON found under config/")
    return out


def _scrub_string(value: str, counter: list[int]) -> str:
    text = value
    for pattern, repl in _LABEL_REWRITES:
        text = pattern.sub(repl, text)
    if text != value:
        return text
    # Non-empty binding / path-like values become stable aliases.
    if not text.strip():
        return text
    counter[0] += 1
    return f"alias_{counter[0]}"


def _scrub_node(node: Any, counter: list[int], *, parent_key: str | None = None) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, val in node.items():
            if key in ("latitude", "lat") and isinstance(val, (int, float)):
                out[key] = PLACEHOLDER_LAT
            elif key in ("longitude", "lon", "lng") and isinstance(val, (int, float)):
                out[key] = PLACEHOLDER_LON
            elif key == "label" and isinstance(val, str):
                scrubbed = val
                for pattern, repl in _LABEL_REWRITES:
                    scrubbed = pattern.sub(repl, scrubbed)
                out[key] = scrubbed
            elif key in _BINDING_VALUE_KEYS and isinstance(val, dict):
                out[key] = {
                    k: (
                        _scrub_string(v, counter)
                        if isinstance(v, str) and v.strip()
                        else v
                    )
                    for k, v in val.items()
                }
            elif key in _PATHISH_KEYS and isinstance(val, str) and val.strip():
                out[key] = f"fixture/{Path(val).name or 'data.csv'}"
            else:
                out[key] = _scrub_node(val, counter, parent_key=key)
        return out
    if isinstance(node, list):
        return [_scrub_node(item, counter, parent_key=parent_key) for item in node]
    if isinstance(node, str) and parent_key in _PATHISH_KEYS:
        return f"fixture/{Path(node).name or 'data.csv'}"
    return node


def scrub_pack(pack: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counter = [0]
    scrubbed = {
        name: _scrub_node(copy.deepcopy(doc), counter) for name, doc in pack.items()
    }
    house = scrubbed.get("house_profiles.json")
    if isinstance(house, dict):
        profiles = house.get("profiles")
        if isinstance(profiles, list):
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                profile["id"] = PLACEHOLDER_PROFILE_ID
                profile["label"] = PLACEHOLDER_PROFILE_LABEL
                if "latitude" in profile:
                    profile["latitude"] = PLACEHOLDER_LAT
                if "longitude" in profile:
                    profile["longitude"] = PLACEHOLDER_LON
    return scrubbed


def _write_pack(out_dir: Path, pack: dict[str, dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, doc in pack.items():
        path = out_dir / name
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def slice_single_battery(pack: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep exactly one battery so plant-flat ESS migrate can auto-pick."""
    out = copy.deepcopy(pack)
    components = out.get("components.json")
    if not isinstance(components, dict):
        raise SystemExit("v3_single_battery: components.json missing")
    batteries = components.get("batteries")
    if not isinstance(batteries, list):
        raise SystemExit("v3_single_battery: batteries[] missing")
    with_id = [
        b for b in batteries if isinstance(b, dict) and str(b.get("id") or "").strip()
    ]
    if not with_id:
        raise SystemExit("v3_single_battery: no batteries with id")
    # Prefer the largest-looking house storage label/id, else first.
    preferred = None
    for bat in with_id:
        bid = str(bat.get("id") or "")
        label = str(bat.get("label") or "")
        if "15" in bid or "15" in label or "10_kwh" in bid:
            preferred = bat
            break
    keep = preferred or with_id[0]
    components["batteries"] = [keep]
    keep_id = str(keep["id"]).strip()
    # Drop scenario battery refs that no longer exist.
    scenarios = out.get("backtesting_scenarios.json")
    if isinstance(scenarios, dict):
        _prune_scenario_battery_refs(scenarios, {keep_id})
    if len(components["batteries"]) != 1:
        raise SystemExit(
            f"v3_single_battery: expected 1 battery, got {len(components['batteries'])}"
        )
    return out


def _prune_scenario_battery_refs(doc: dict[str, Any], keep_ids: set[str]) -> None:
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list):
        return
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        settings = sc.get("settings")
        if not isinstance(settings, dict):
            continue
        ids = settings.get("battery_ids")
        if isinstance(ids, list):
            settings["battery_ids"] = [
                x for x in ids if str(x) in keep_ids
            ] or [next(iter(keep_ids))]
        if "battery_id" in settings and str(settings.get("battery_id")) not in keep_ids:
            settings["battery_id"] = next(iter(keep_ids))


def reconstruct_pre_ehal(
    dm3_pack: dict[str, dict[str, Any]],
    v1_pack: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Graft scrubbed v1 loxone nests onto a dm3 skeleton (decision 1C)."""
    out = copy.deepcopy(dm3_pack)
    v1_config = v1_pack.get("config.json") or {}
    v1_house = v1_pack.get("house_profiles.json") or {}
    config = out.setdefault("config.json", {"earnie_data_model": 3})
    if not isinstance(config, dict):
        raise SystemExit("v3_pre_ehal: config.json invalid")
    config["earnie_data_model"] = 3
    blocks = v1_config.get("loxone_blocks")
    if not isinstance(blocks, dict) or not blocks:
        raise SystemExit("v3_pre_ehal: v1 config.loxone_blocks missing or empty")
    # Drop block keys that map onto plant-flat ESS fields so this fixture stays
    # ehal-only (ESS migrate is covered by v3_last / v3_single_battery).
    from ehal.ess_fields import plant_flat_ess_keys
    from house_config.ehal_bindings import BLOCKS_TO_EHAL

    filtered_blocks: dict[str, Any] = {}
    for key, val in blocks.items():
        field = BLOCKS_TO_EHAL.get(str(key))
        if field and field in plant_flat_ess_keys({field: "x"}):
            continue
        filtered_blocks[str(key)] = val
    if not filtered_blocks:
        raise SystemExit("v3_pre_ehal: no non-ESS loxone_blocks left after filter")
    config["loxone_blocks"] = copy.deepcopy(filtered_blocks)

    house = out.get("house_profiles.json")
    if not isinstance(house, dict):
        raise SystemExit("v3_pre_ehal: house_profiles.json missing")
    house["earnie_data_model"] = 3
    v1_profiles = v1_house.get("profiles")
    dm3_profiles = house.get("profiles")
    if not isinstance(v1_profiles, list) or not isinstance(dm3_profiles, list):
        raise SystemExit("v3_pre_ehal: profiles[] missing")
    v1_by_type: dict[str, dict] = {}
    for consumer in v1_profiles[0].get("consumers") or []:
        if isinstance(consumer, dict) and consumer.get("type"):
            v1_by_type.setdefault(str(consumer["type"]), consumer)
    grafted = 0
    for consumer in dm3_profiles[0].get("consumers") or []:
        if not isinstance(consumer, dict):
            continue
        ctype = str(consumer.get("type") or "")
        src = v1_by_type.get(ctype)
        if not isinstance(src, dict):
            continue
        for nest_key in (
            "loxone_inputs",
            "loxone_outputs",
            "swimspa_filter_bindings",
        ):
            nest = src.get(nest_key)
            if isinstance(nest, dict) and nest:
                consumer[nest_key] = copy.deepcopy(nest)
                grafted += 1
        thermal = src.get("thermal_control")
        if isinstance(thermal, dict) and isinstance(thermal.get("loxone"), dict):
            tc = consumer.setdefault("thermal_control", {})
            if isinstance(tc, dict):
                tc["loxone"] = copy.deepcopy(thermal["loxone"])
                grafted += 1
    if grafted == 0 and not config.get("loxone_blocks"):
        raise SystemExit("v3_pre_ehal: nothing grafted from v1 nests")
    # EHAL-only fixture: drop plant-flat ESS so ensure_migrated does not stop
    # on the ESS one-shot (covered by v3_last / v3_single_battery).
    from ehal.ess_fields import plant_flat_ess_keys

    plant = house.get("plant")
    if isinstance(plant, dict):
        bindings = plant.get("ehal_bindings")
        if isinstance(bindings, dict):
            flat = plant_flat_ess_keys(bindings)
            if flat:
                plant["ehal_bindings"] = {
                    k: v for k, v in bindings.items() if k not in flat
                }
    # Scrub again so grafted Merker values are aliased.
    return scrub_pack(out)


def extract_all(env_home: Path, out_root: Path) -> None:
    if not (env_home / ".git").exists():
        raise SystemExit(f"Not a git repo: {env_home}")
    out_root.mkdir(parents=True, exist_ok=True)

    scrubbed_by_folder: dict[str, dict[str, dict[str, Any]]] = {}
    for folder, sha in SNAPSHOTS:
        pack = scrub_pack(_load_pack(env_home, sha))
        _write_pack(out_root / folder, pack)
        scrubbed_by_folder[folder] = pack
        print(f"wrote {folder}/ from {sha} ({len(pack)} files)")

    v3 = scrubbed_by_folder["v3_last"]
    single = slice_single_battery(v3)
    _write_pack(out_root / "v3_single_battery", single)
    print("wrote v3_single_battery/ (1 battery slice)")

    v1 = scrub_pack(_load_pack(env_home, V1_NEST_SHA))
    pre_ehal = reconstruct_pre_ehal(v3, v1)
    _write_pack(out_root / "v3_pre_ehal", pre_ehal)
    n_blocks = len((pre_ehal.get("config.json") or {}).get("loxone_blocks") or {})
    print(f"wrote v3_pre_ehal/ (loxone_blocks={n_blocks})")


def main(argv: list[str] | None = None) -> None:
    _configure_console_utf8()
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Extract scrubbed migration fixtures from Earnie-env-home."
    )
    parser.add_argument(
        "--env-home",
        type=Path,
        required=True,
        help="Path to private Earnie-env-home git clone",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=repo_root / "tests" / "fixtures" / "migration",
        help="Output directory (default: tests/fixtures/migration)",
    )
    args = parser.parse_args(argv)
    extract_all(args.env_home.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
