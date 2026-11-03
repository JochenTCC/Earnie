"""SUSI P6: household-electricity reference values and the D3a VAT flag (dm5.vat_deductible)."""
from __future__ import annotations

import pytest

from house_config.household_reference import household_comparison, household_reference_kwh


@pytest.mark.parametrize(
    "persons,expected",
    [(1, 1700.0), (2, 3400.0), (3, 4200.0), (4, 4700.0), (6, 4700.0)],
)
def test_reference_value_per_persons(persons, expected):
    assert household_reference_kwh(persons) == expected


def test_reference_value_rejects_zero_persons():
    with pytest.raises(ValueError, match="persons"):
        household_reference_kwh(0)


def test_comparison_subtracts_heating_ev_and_pool_but_not_appliances(monkeypatch):
    import house_config.household_reference as reference

    monkeypatch.setattr(reference, "consumer_annual_kwh", lambda c: c["annual_kwh"])
    consumers = [
        {"id": "wp", "label": "Haus Wärme", "type": "thermal_annual", "annual_kwh": 1500.0},
        {"id": "ev", "label": "E-Auto", "type": "ev", "annual_kwh": 2000.0},
        {"id": "pool", "label": "Pool", "type": "thermal_rc", "annual_kwh": 1000.0},
        {"id": "wasch", "label": "Waschmaschine", "type": "generic", "annual_kwh": 300.0},
    ]
    result = household_comparison(7900.0, 2, consumers)
    assert result["excluded_labels"] == ["Haus Wärme", "E-Auto", "Pool"]
    assert result["excluded_kwh"] == pytest.approx(4500.0)
    assert result["household_kwh"] == pytest.approx(3400.0)
    assert result["deviation"] == pytest.approx(0.0)
    assert result["warn"] is False


@pytest.mark.parametrize(
    "annual,warn",
    [(3400.0 * 1.4, False), (3400.0 * 1.41, True), (3400.0 * 0.6, False), (3400.0 * 0.59, True)],
)
def test_comparison_warns_only_above_40_percent(annual, warn):
    assert household_comparison(annual, 2, [])["warn"] is warn


def _raw_profile(**extra) -> dict:
    return {
        "id": "haus",
        "label": "Haus",
        "annual_kwh": 4000,
        "latitude": 47.0,
        "longitude": 10.0,
        "netznutzung": {"area_id": "user_haus"},
        "consumers": [],
        "heating_enabled": False,
        "persons": 2,
        **extra,
    }


def test_vat_step_writes_false_and_keeps_a_stored_value():
    from runtime_store.migration.steps.vat_deductible import STEP

    docs = {
        "house_profiles.json": {
            "profiles": [_raw_profile(), _raw_profile(id="b", vat_deductible=True)]
        }
    }
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    profiles = result.docs["house_profiles.json"]["profiles"]
    assert [p["vat_deductible"] for p in profiles] == [False, True]
    assert result.changed_files == ("house_profiles.json",)
    assert not STEP.detect(result.docs)
    assert "vat_deductible" not in docs["house_profiles.json"]["profiles"][0]


def test_loader_carries_vat_flag_and_rejects_non_bool(tmp_path):
    import json

    from house_config.profiles_store import (
        load_house_profiles_document,
        save_house_profiles_document,
    )

    path = tmp_path / "house_profiles.json"
    path.write_text(
        json.dumps({"profiles": [_raw_profile(vat_deductible=True)], "earnie_data_model": 5}),
        encoding="utf-8",
    )
    doc = load_house_profiles_document(str(path))
    assert doc["profiles"]["haus"]["vat_deductible"] is True
    save_house_profiles_document(str(path), {"profiles": list(doc["profiles"].values())})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["profiles"][0]["vat_deductible"] is True

    path.write_text(
        json.dumps({"profiles": [_raw_profile(vat_deductible="ja")], "earnie_data_model": 5}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="vat_deductible"):
        load_house_profiles_document(str(path))
