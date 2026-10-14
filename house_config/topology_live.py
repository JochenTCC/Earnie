"""Topology P1 live-path validation (daemon + EHAL-Com; not SE/backtesting)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from house_config.inverter import AC_GRID_TIED
from house_config.powerstation import BATTERY_TYPE_HOUSE
from house_config.topology_regulates import REGULATES_ON_GRID

_THREE_QUESTIONS = (
    "Sitzt der Zähler direkt am Hausanschluss? "
    "Gibt es nur einen Tarif? "
    "Regelt ein anderes Gerät selbst auf diesen Zähler?"
)

_P3_P4_HINT = (
    "Mehrere Regler am Wurzelknoten werden erst mit Topology P3 "
    "(per-ESS-Schreiben) und P4 (reaktiver Regler im MILP) unterstützt."
)


def _as_list(entities: Mapping[str, dict] | Sequence[dict] | None) -> list[dict]:
    if entities is None:
        return []
    if isinstance(entities, Mapping):
        return [dict(v) for v in entities.values() if isinstance(v, dict)]
    return [dict(e) for e in entities if isinstance(e, dict)]


def _is_grid_tied_house(bat: dict) -> bool:
    bat_type = str(bat.get("type") or BATTERY_TYPE_HOUSE).strip().lower()
    if bat_type != BATTERY_TYPE_HOUSE:
        return False
    ac = str(bat.get("ac_connection") or AC_GRID_TIED).strip().lower()
    return ac == AC_GRID_TIED


def validate_live_topology(
    *,
    plant: Mapping[str, object] | None,
    batteries: Mapping[str, dict] | Sequence[dict] | None,
    inverters: Mapping[str, dict] | Sequence[dict] | None,
    live_battery_ids: Sequence[str] | None = None,
) -> None:
    """Refuse live planning when root assertions or loop/multi-ESS rules fail.

    - plant.grid_meter both true (M1 user assertion)
    - (i) grid-tied house batteries with regulates_on=grid plus inverters with
      regulates_on=grid ≤ 1 (island packs excluded from the count)
    - (ii) at most one grid-tied house battery in the live plan until P3+P4
    """
    _assert_grid_meter(plant)
    bats = _as_list(batteries)
    invs = _as_list(inverters)
    _assert_root_loops(bats, invs)
    _assert_one_grid_tied_house_in_live(bats, live_battery_ids)


def _assert_grid_meter(plant: Mapping[str, object] | None) -> None:
    plant_map = plant if isinstance(plant, Mapping) else {}
    raw = plant_map.get("grid_meter")
    if not isinstance(raw, Mapping):
        raise ValueError(
            "Live-Pfad: plant.grid_meter fehlt. Beide Assertions müssen true "
            "sein (Zähler am Hausanschluss, ein Tarif). "
            f"{_THREE_QUESTIONS} "
            "Migration: python -m scripts.migrate_topology_once "
            "--config-dir <config-dir>"
        )
    at_house = raw.get("at_house_connection")
    single = raw.get("single_tariff")
    if at_house is not True or single is not True:
        raise ValueError(
            "Live-Pfad: plant.grid_meter.at_house_connection und "
            "single_tariff müssen beide true sein "
            f"(got at_house_connection={at_house!r}, single_tariff={single!r}). "
            f"{_THREE_QUESTIONS}"
        )


def _assert_root_loops(batteries: list[dict], inverters: list[dict]) -> None:
    loop_ids: list[str] = []
    for bat in batteries:
        if not _is_grid_tied_house(bat):
            continue
        if str(bat.get("regulates_on") or "").strip().lower() != REGULATES_ON_GRID:
            continue
        loop_ids.append(f"battery:{bat.get('id') or '?'}")
    for inv in inverters:
        if str(inv.get("regulates_on") or "").strip().lower() != REGULATES_ON_GRID:
            continue
        loop_ids.append(f"inverter:{inv.get('id') or '?'}")
    if len(loop_ids) <= 1:
        return
    raise ValueError(
        "Live-Pfad: mehr als ein geschlossener Regler am Wurzelknoten "
        f"({', '.join(loop_ids)}). {_P3_P4_HINT}"
    )


def _assert_one_grid_tied_house_in_live(
    batteries: list[dict],
    live_battery_ids: Sequence[str] | None,
) -> None:
    if live_battery_ids is None:
        selected = {
            str(b.get("id") or "").strip()
            for b in batteries
            if str(b.get("id") or "").strip()
        }
    else:
        selected = {str(x or "").strip() for x in live_battery_ids if str(x or "").strip()}
    grid_tied = [
        str(b.get("id") or "").strip()
        for b in batteries
        if _is_grid_tied_house(b) and str(b.get("id") or "").strip() in selected
    ]
    if len(grid_tied) <= 1:
        return
    raise ValueError(
        "Live-Pfad: höchstens eine netzgekoppelte Hausbatterie im Live-Plan "
        f"bis Topology P3+P4 (gefunden: {', '.join(grid_tied)}). "
        "Zweite Hausbatterie ablehnen — kein Warn-and-Exclude."
    )


def validate_live_topology_from_config_dir() -> None:
    """Load sidecars + live scenario and validate (daemon / EHAL-Com)."""
    from house_config.components_store import load_components_document
    from house_config.entity_resolution import (
        attach_ac_connection_from_inverters,
        batteries_by_id,
    )
    from house_config.inverter import (
        inverters_by_id,
        reject_if_needs_conversion_efficiency_migration,
        reject_if_needs_inverter_migration,
    )
    from house_config.migrate_topology import reject_if_needs_topology_migration
    from house_config.profiles_store import load_house_profiles_document
    from house_config.scenario_resolution import (
        find_scenario_settings,
        get_live_scenario_id,
    )
    from runtime_store.config_load import load_config_or_exit
    from runtime_store.persist_paths import (
        resolve_backtesting_scenarios_json_path,
        resolve_components_json_path,
        resolve_house_profiles_json_path,
    )

    config = load_config_or_exit()
    # Raw JSON lives on Config instance (config.CONFIG), not the module.
    cfg = getattr(config, "CONFIG", None)
    raw = getattr(cfg, "_raw_config", None) if cfg is not None else None
    if not isinstance(raw, dict):
        raise ValueError("Live-Pfad: config.json roh nicht lesbar für Topology-Check.")

    components = load_components_document(resolve_components_json_path())
    reject_if_needs_inverter_migration(components)
    reject_if_needs_conversion_efficiency_migration(components)
    reject_if_needs_topology_migration(components)

    inverters = inverters_by_id(components)
    batteries = batteries_by_id(components)
    attach_ac_connection_from_inverters(batteries, inverters)

    house = load_house_profiles_document(resolve_house_profiles_json_path())
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}

    scenario_id = get_live_scenario_id(raw)
    settings = find_scenario_settings(
        resolve_backtesting_scenarios_json_path(),
        scenario_id,
    )
    bat_ids = settings.get("battery_ids")
    live_ids: list[str] = []
    if isinstance(bat_ids, list):
        live_ids = [str(x).strip() for x in bat_ids if str(x or "").strip()]
    elif str(settings.get("battery_id", "") or "").strip():
        live_ids = [str(settings.get("battery_id")).strip()]

    validate_live_topology(
        plant=plant,
        batteries=batteries,
        inverters=inverters,
        live_battery_ids=live_ids,
    )
