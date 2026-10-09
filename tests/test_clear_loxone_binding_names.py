"""Q8: clear Merker names from Loxone bindings (keep activation keys)."""
from __future__ import annotations

from ehal.functions import available_functions, function_statuses
from house_config.clear_loxone_binding_names import (
    clear_binding_values,
    clear_loxone_binding_names_in_components,
    clear_loxone_binding_names_in_house,
)


def test_clear_binding_values() -> None:
    assert clear_binding_values({"sens_pv_production_active": "PV", "x": ""}) == {
        "sens_pv_production_active": "",
        "x": "",
    }


def test_clear_house_and_components() -> None:
    house = {
        "plant": {"ehal_bindings": {"sens_pv_production_active": "PV"}},
        "profiles": {
            "live": {
                "consumers": [
                    {
                        "id": "wm",
                        "ehal_bindings": {"flex.wm.set_enable": "En"},
                    }
                ]
            }
        },
    }
    cleared = clear_loxone_binding_names_in_house(house)
    assert cleared["plant"]["ehal_bindings"]["sens_pv_production_active"] == ""
    assert cleared["profiles"]["live"]["consumers"][0]["ehal_bindings"][
        "flex.wm.set_enable"
    ] == ""
    # original untouched
    assert house["plant"]["ehal_bindings"]["sens_pv_production_active"] == "PV"

    components = {
        "batteries": [
            {
                "id": "b1",
                "ehal_bindings": {"ess.b1.sens_ess_soc": "SoC"},
            }
        ]
    }
    cleared_c = clear_loxone_binding_names_in_components(components)
    assert cleared_c["batteries"][0]["ehal_bindings"]["ess.b1.sens_ess_soc"] == ""


def test_mapped_fields_empty_loxone_activation() -> None:
    mapped = {
        "sens_grid_power_active": "",
        "sens_pv_production_active": "",
        "sens_ess_soc": "",
    }
    assert available_functions(mapped, require_nonempty_value=False) >= {"telemetry"}
    assert available_functions(mapped, require_nonempty_value=True) == set()
    statuses = function_statuses(mapped, require_nonempty_value=False)
    tele = next(s for s in statuses if s.function.id == "telemetry")
    assert tele.state == "available"
