"""dm6.consumer_bare_bindings merges qualified heat / pool read keys into the bare key."""
from __future__ import annotations

from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY
from runtime_store.migration.steps.consumer_bare_bindings import STEP

_QT = "heatpump.waermepumpe.sens_temperature_heat_storage"


def _docs(bindings: dict, *, ctype: str = "thermal_annual", cid: str = "waermepumpe") -> dict:
    house = {
        DATA_MODEL_KEY: CURRENT_DATA_MODEL,
        "profiles": [
            {"id": "p", "consumers": [{"id": cid, "type": ctype, "ehal_bindings": bindings}]}
        ],
    }
    return {"house_profiles.json": house}


def _bindings(result) -> dict:
    return result.docs["house_profiles.json"]["profiles"][0]["consumers"][0]["ehal_bindings"]


def test_empty_pair_merges_into_bare_key():
    docs = _docs(
        {
            "heatpump.waermepumpe.set_enable": "",
            "sens_temperature_heat_storage": "",
            _QT: "",
            "heatpump.waermepumpe.get_temperature_heat_storage_setpoint": "",
        }
    )
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    assert result.changed_files == ("house_profiles.json",)
    # set_enable stays qualified (the mapping stores it so); heat kinds become bare.
    assert _bindings(result) == {
        "heatpump.waermepumpe.set_enable": "",
        "sens_temperature_heat_storage": "",
        "get_temperature_heat_storage_setpoint": "",
    }
    assert not STEP.detect(result.docs)
    assert _QT in docs["house_profiles.json"]["profiles"][0]["consumers"][0]["ehal_bindings"]


def test_merker_of_either_key_is_kept():
    result = STEP.apply(_docs({"sens_temperature_heat_storage": "", _QT: "TempEq"}), {})
    assert _bindings(result) == {"sens_temperature_heat_storage": "TempEq"}
    result = STEP.apply(_docs({"sens_temperature_heat_storage": "TempEq", _QT: ""}), {})
    assert _bindings(result) == {"sens_temperature_heat_storage": "TempEq"}


def test_two_different_merkers_block():
    docs = _docs({"sens_temperature_heat_storage": "A", _QT: "B"})
    result = STEP.apply(docs, {})
    assert result.changed_files == ()
    assert len(result.blockers) == 1
    assert "'A'" in result.blockers[0].message_de and "'B'" in result.blockers[0].message_de


def test_pool_water_temperature():
    docs = _docs(
        {"pool.pool_swimspa.sens_temperature_water": "", "pool.pool_swimspa.set_enable": ""},
        ctype="thermal_rc",
        cid="pool_swimspa",
    )
    assert STEP.detect(docs)
    assert _bindings(STEP.apply(docs, {})) == {
        "pool.pool_swimspa.set_enable": "",
        "sens_temperature_water": "",
    }


def test_bare_only_is_no_op():
    docs = _docs({"sens_temperature_heat_storage": "", "heatpump.waermepumpe.set_enable": ""})
    assert not STEP.detect(docs)
    assert STEP.apply(docs, {}).changed_files == ()
