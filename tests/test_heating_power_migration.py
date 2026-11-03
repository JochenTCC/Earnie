"""dm5.heating_power: heating-system catalog nominal_power_kw → heating_power_kw."""
from __future__ import annotations

import copy

import pytest

from runtime_store.migration.registry import STEPS
from runtime_store.migration.steps.heating_power import STEP, apply, detect


def _docs(*entries: dict) -> dict:
    return {"components.json": {"earnie_data_model": 5, "heating_systems": list(entries)}}


def _catalog(docs: dict) -> list[dict]:
    return docs["components.json"]["heating_systems"]


def test_heat_pump_gets_electric_power_times_jaz():
    docs = _docs(
        {
            "id": "wp",
            "heat_source": {"type": "heat_pump", "heat_pump_type": "erde", "efficiency": 4.0},
            "nominal_power_kw": 2.5,
            "min_on_quarterhours": 4,
        }
    )
    assert detect(docs)
    result = apply(docs, {})
    assert not result.blockers
    assert result.changed_files == ("components.json",)
    assert _catalog(result.docs) == [
        {
            "id": "wp",
            "heat_source": {"type": "heat_pump", "heat_pump_type": "erde", "efficiency": 4.0},
            "heating_power_kw": 10.0,
            "min_on_quarterhours": 4,
        }
    ]
    assert not detect(result.docs)


def test_default_efficiency_is_used_without_stored_value():
    from house_config.heat_source import default_efficiency

    source = {"type": "heat_pump", "heat_pump_type": "luft"}
    result = apply(_docs({"id": "wp", "heat_source": source, "nominal_power_kw": 3.0}), {})
    assert _catalog(result.docs)[0]["heating_power_kw"] == pytest.approx(
        3.0 * default_efficiency(source)
    )


def test_fuel_source_drops_min_on_and_uses_nutzungsgrad():
    result = apply(
        _docs(
            {
                "id": "gas",
                "heat_source": {"type": "gas", "efficiency": 0.9},
                "nominal_power_kw": 10.0,
                "min_on_quarterhours": 4,
            }
        ),
        {},
    )
    assert _catalog(result.docs) == [
        {"id": "gas", "heat_source": {"type": "gas", "efficiency": 0.9}, "heating_power_kw": 9.0}
    ]


def test_zero_power_gets_no_heating_power():
    result = apply(_docs({"id": "gas", "heat_source": {"type": "gas"}, "nominal_power_kw": 0.0}), {})
    assert not result.blockers
    assert _catalog(result.docs) == [{"id": "gas", "heat_source": {"type": "gas"}}]


def test_both_power_fields_block():
    docs = _docs(
        {"id": "x", "heat_source": {"type": "gas"}, "nominal_power_kw": 1.0, "heating_power_kw": 2.0}
    )
    before = copy.deepcopy(docs)
    result = apply(docs, {})
    assert result.blockers and result.blockers[0].step_id == STEP.id
    assert result.changed_files == ()
    assert docs == before


def test_migrated_entry_loads_with_the_same_electric_power():
    from house_config.heating_systems import apply_heating_system, heating_systems_by_id

    docs = _docs(
        {"id": "wp", "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
         "nominal_power_kw": 1.9, "min_on_quarterhours": 4}
    )
    entry = heating_systems_by_id(apply(docs, {}).docs["components.json"])["wp"]
    consumer: dict = {}
    apply_heating_system(consumer, entry)
    assert consumer["nominal_power_kw"] == 1.9
    assert consumer["min_on_quarterhours"] == 4


def test_runs_after_heating_systems():
    ids = [step.id for step in STEPS]
    assert ids.index("dm5.heating_power") > ids.index("dm5.heating_systems")
