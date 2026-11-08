"""Print what Earnie derives from the pack in ``EARNIE_ENV_PATH`` as one JSON line.

Runs in a process of its own, since ``config`` binds to one pack at import. Points use the
nominal kWp: the pack's ``kwp`` is the effective one, nominal × performance ratio.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import config
from house_config.baseload import consumer_annual_kwh, profile_baseload_kwh
from house_config.earnie_points import compute_earnie_points
from studies.viability import params as params_mod


def main() -> None:
    scenarios = config.get_backtesting_scenarios()
    live = scenarios[config.get_live_scenario_id()]
    profile = live["_house_profile"]
    consumers = {
        str(c["id"]): round(float(consumer_annual_kwh(c)), 1) for c in profile.get("consumers", [])
    }
    components_path = Path(os.environ["EARNIE_ENV_PATH"]) / "config" / "components.json"
    components = json.loads(components_path.read_text(encoding="utf-8"))
    ratio = float(params_mod.load()["annahmen"]["pv_performance_ratio"])
    nominal = {
        **components,
        "pv_systems": [{**s, "kwp": float(s["kwp"]) / ratio} for s in components["pv_systems"]],
    }
    print(
        json.dumps(
            {
                "scenarios": sorted(scenarios),
                "annual_kwh": float(profile["annual_kwh"]),
                "baseload_kwh": round(float(profile_baseload_kwh(profile)), 1),
                "consumers": consumers,
                "consumers_kwh": round(sum(consumers.values()), 1),
                "points": compute_earnie_points(nominal, profile),
            }
        )
    )


if __name__ == "__main__":
    main()
