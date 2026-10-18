"""dm4.consumer_flex_bindings — rekey flex.* to typed storage."""
from __future__ import annotations

from house_config.migrate_consumer_flex_bindings import (
    house_has_legacy_flex_bindings,
    migrate_house_consumer_flex_bindings,
    rekey_consumer_flex_bindings,
)
from runtime_store.migration.steps.consumer_flex_bindings import STEP, detect


def test_rekey_heatpump_and_generic():
    consumer = {
        "id": "waermepumpe",
        "type": "thermal_annual",
        "ehal_bindings": {
            "flex.waermepumpe.sens_power_act": "P",
            "flex.waermepumpe.set_enable": "En",
        },
    }
    out, conflicts = rekey_consumer_flex_bindings(consumer)
    assert conflicts == []
    assert out == {
        "heatpump.waermepumpe.sens_power_act": "P",
        "heatpump.waermepumpe.set_enable": "En",
    }


def test_rekey_conflict_different_merker():
    consumer = {
        "id": "wm",
        "label": "Waschmaschine",
        "type": "generic",
        "ehal_bindings": {
            "flex.wm.set_enable": "A",
            "consumer.wm.set_enable": "B",
        },
    }
    out, conflicts = rekey_consumer_flex_bindings(consumer)
    assert len(conflicts) == 1
    assert "Konflikt" in conflicts[0]
    assert out["flex.wm.set_enable"] == "A"
    assert out["consumer.wm.set_enable"] == "B"


def test_rekey_fills_empty_typed_from_flex():
    consumer = {
        "id": "wm",
        "type": "generic",
        "ehal_bindings": {
            "flex.wm.set_enable": "En",
            "consumer.wm.set_enable": "",
        },
    }
    out, conflicts = rekey_consumer_flex_bindings(consumer)
    assert conflicts == []
    assert out == {"consumer.wm.set_enable": "En"}


def test_migrate_house_and_detect():
    house = {
        "profiles": {
            "p": {
                "consumers": [
                    {
                        "id": "kochen",
                        "type": "generic",
                        "ehal_bindings": {"flex.kochen.sens_power_act": ""},
                    }
                ]
            }
        }
    }
    assert house_has_legacy_flex_bindings(house)
    assert detect({"house_profiles.json": house})
    out, changed, conflicts = migrate_house_consumer_flex_bindings(house)
    assert changed
    assert conflicts == ()
    cons = out["profiles"]["p"]["consumers"][0]
    assert cons["ehal_bindings"] == {"consumer.kochen.sens_power_act": ""}
    assert not house_has_legacy_flex_bindings(out)
    assert not detect({"house_profiles.json": out})


def test_step_apply_blocker_on_conflict():
    docs = {
        "house_profiles.json": {
            "profiles": [
                {
                    "consumers": [
                        {
                            "id": "wm",
                            "type": "generic",
                            "ehal_bindings": {
                                "flex.wm.set_enable": "A",
                                "consumer.wm.set_enable": "B",
                            },
                        }
                    ]
                }
            ]
        }
    }
    result = STEP.apply(docs, {})
    assert result.blockers
    assert "Konflikt" in result.blockers[0].message_de
    assert result.changed_files == ()
