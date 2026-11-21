"""dm6.wallbox_charger_keys: one key per charger kind, spelled ``evcs.<Wallbox>.<kind>``."""
from __future__ import annotations

from house_config.required_signal_activation import (
    activate_wallbox_required,
    pack_missing_required,
)
from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY
from runtime_store.migration.steps.wallbox_charger_keys import STEP

_Q = "evcs.wb_a.set_evcs_max_current"


def _docs(bindings: dict, *, wallbox_id: str = "wb_a") -> dict:
    components = {
        DATA_MODEL_KEY: CURRENT_DATA_MODEL,
        "wallboxes": [{"id": wallbox_id, "ehal_bindings": bindings}],
    }
    return {"components.json": components}


def _bindings(result) -> dict:
    return result.docs["components.json"]["wallboxes"][0]["ehal_bindings"]


def test_a_migrated_wallbox_ends_with_one_qualified_key_per_kind():
    # The state dm6.wallboxes + dm4.required_signal_activation left behind.
    docs = _docs(
        {
            "set_evcs_max_current": "Lox_Strom",
            "sens_evcs_connected": "",
            "evcs.e_auto.set_evcs_mode": "Lox_Modus",
            _Q: "",
        }
    )
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    assert result.changed_files == ("components.json",)
    assert _bindings(result) == {
        _Q: "Lox_Strom",
        "evcs.wb_a.sens_evcs_connected": "",
        "evcs.wb_a.set_evcs_mode": "Lox_Modus",
    }
    assert not STEP.detect(result.docs)
    assert "set_evcs_max_current" in docs["components.json"]["wallboxes"][0]["ehal_bindings"]


def test_the_bound_value_of_either_key_is_kept():
    result = STEP.apply(_docs({"set_evcs_max_current": "", _Q: "Lox_Strom"}), {})
    assert _bindings(result) == {_Q: "Lox_Strom"}
    result = STEP.apply(_docs({"set_evcs_max_current": "Lox_Strom", _Q: ""}), {})
    assert _bindings(result) == {_Q: "Lox_Strom"}
    result = STEP.apply(_docs({"set_evcs_max_current": "Lox_Strom", _Q: "Lox_Strom"}), {})
    assert _bindings(result) == {_Q: "Lox_Strom"}


def test_two_different_merkers_block_without_a_change():
    docs = _docs({"set_evcs_max_current": "A", _Q: "B"})
    result = STEP.apply(docs, {})
    assert result.changed_files == ()
    assert result.docs is docs
    assert len(result.blockers) == 1
    message = result.blockers[0].message_de
    assert "'A'" in message and "'B'" in message and "wb_a" in message


def test_a_new_wallbox_is_not_detected():
    assert not STEP.detect(_docs({_Q: "", "evcs.wb_a.sens_evcs_connected": ""}))


def test_activation_adds_no_second_key_for_a_kind_the_wallbox_holds():
    held = activate_wallbox_required(
        {"id": "wb_a", "ehal_bindings": {"set_evcs_max_current": "Lox_Strom"}}
    )
    assert held["ehal_bindings"] == {"set_evcs_max_current": "Lox_Strom"}
    new = activate_wallbox_required({"id": "wb_a", "ehal_bindings": {}})
    assert new["ehal_bindings"] == {_Q: ""}
    components = {"wallboxes": [{"id": "wb_a", "ehal_bindings": {"set_evcs_max_current": ""}}]}
    assert not pack_missing_required(None, components)
