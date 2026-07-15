"""Tests für house_config.earnie_role und profiles_store-Normalisierung."""
from __future__ import annotations

import pytest

from house_config.earnie_role import (
    EARNIE_ROLE_FLEX,
    EARNIE_ROLE_KNOWN,
    EARNIE_ROLE_MANUAL,
    infer_earnie_role_from_legacy,
    is_earnie_flex,
    is_earnie_known,
    is_earnie_manual,
    manual_recommendation_horizon_h,
    resolve_earnie_role,
)
from house_config.planning_flex_bridge import split_planning_generic_consumers
from house_config.profiles_store import normalize_house_profiles_document


def test_infer_role_manual_from_appliance_recommendation():
    consumer = {
        "type": "generic",
        "appliance_recommendation": {"power_source": "manual"},
        "schedule": {"runs_per_week": 5, "start_shift_h": 4.0},
    }
    assert infer_earnie_role_from_legacy(consumer) == EARNIE_ROLE_MANUAL


def test_infer_role_flex_from_positive_shift():
    consumer = {
        "type": "generic",
        "schedule": {"runs_per_week": 3, "start_shift_h": 6.0},
    }
    assert infer_earnie_role_from_legacy(consumer) == EARNIE_ROLE_FLEX


def test_infer_role_known_default():
    consumer = {
        "type": "generic",
        "schedule": {"runs_per_week": 7, "start_shift_h": 0.0},
    }
    assert infer_earnie_role_from_legacy(consumer) == EARNIE_ROLE_KNOWN


def test_manual_recommendation_horizon_h():
    consumer = {
        "schedule": {"start_shift_h": 4.0},
    }
    assert manual_recommendation_horizon_h(consumer) == 4


def test_normalize_assigns_earnie_role_known():
    doc = normalize_house_profiles_document(
        {
            "profiles": [
                {
                    "id": "p1",
                    "annual_kwh": 1000,
                    "consumers": [
                        {
                            "id": "kochen",
                            "type": "generic",
                            "nominal_power_kw": 2.0,
                            "schedule": {
                                "runs_per_week": 7,
                                "duration_h": 1.0,
                                "start_hour": 19,
                                "start_shift_h": 0.0,
                            },
                        }
                    ],
                }
            ]
        }
    )
    consumer = doc["profiles"]["p1"]["consumers"][0]
    assert consumer["earnie_role"] == EARNIE_ROLE_KNOWN
    assert consumer["schedule"]["start_shift_h"] == 0.0


def test_normalize_manual_excludes_from_milp_split():
    doc = normalize_house_profiles_document(
        {
            "profiles": [
                {
                    "id": "p1",
                    "annual_kwh": 1000,
                    "consumers": [
                        {
                            "id": "wm",
                            "type": "generic",
                            "nominal_power_kw": 2.0,
                            "earnie_role": "manual",
                            "schedule": {
                                "runs_per_week": 5,
                                "duration_h": 2.0,
                                "start_hour": 15,
                                "start_shift_h": 6.0,
                            },
                            "appliance_recommendation": {
                                "power_source": "manual",
                                "default_power_kw": 2.0,
                                "default_runtime_h": 2.0,
                            },
                        },
                        {
                            "id": "flex_load",
                            "type": "generic",
                            "nominal_power_kw": 1.0,
                            "earnie_role": "flex",
                            "schedule": {
                                "runs_per_week": 3,
                                "duration_h": 1.0,
                                "start_hour": 12,
                                "start_shift_h": 4.0,
                            },
                        },
                    ],
                }
            ]
        }
    )
    profile = doc["profiles"]["p1"]
    fixed, flex = split_planning_generic_consumers(profile)
    assert fixed == []
    assert len(flex) == 1
    assert flex[0]["id"] == "flex_load"


def test_normalize_flex_requires_positive_shift():
    with pytest.raises(ValueError, match="start_shift_h > 0"):
        normalize_house_profiles_document(
            {
                "profiles": [
                    {
                        "id": "p1",
                        "annual_kwh": 1000,
                        "consumers": [
                            {
                                "id": "x",
                                "type": "generic",
                                "nominal_power_kw": 1.0,
                                "earnie_role": "flex",
                                "schedule": {
                                    "runs_per_week": 1,
                                    "duration_h": 1.0,
                                    "start_hour": 10,
                                    "start_shift_h": 0.0,
                                },
                            }
                        ],
                    }
                ]
            }
        )


def test_resolve_explicit_role():
    consumer = {"earnie_role": "manual", "schedule": {"start_shift_h": 0.0}}
    assert resolve_earnie_role(consumer) == EARNIE_ROLE_MANUAL
    assert is_earnie_manual(consumer)
    assert not is_earnie_known(consumer)
    assert not is_earnie_flex(consumer)


def test_normalize_migrates_legacy_loxone_power_name_to_inputs():
    doc = normalize_house_profiles_document(
        {
            "profiles": [
                {
                    "id": "p1",
                    "annual_kwh": 1000,
                    "consumers": [
                        {
                            "id": "wm",
                            "type": "generic",
                            "nominal_power_kw": 2.0,
                            "earnie_role": "manual",
                            "schedule": {
                                "runs_per_week": 5,
                                "duration_h": 2.0,
                                "start_hour": 15,
                                "start_shift_h": 4.0,
                            },
                            "appliance_recommendation": {
                                "power_source": "loxone",
                                "loxone_power_name": "Leistung Waschmaschine",
                                "default_power_kw": 2.0,
                                "default_runtime_h": 2.0,
                            },
                        }
                    ],
                }
            ]
        }
    )
    consumer = doc["profiles"]["p1"]["consumers"][0]
    assert consumer["loxone_inputs"] == {"power_name": "Leistung Waschmaschine"}
    assert "loxone_power_name" not in consumer["appliance_recommendation"]


def test_normalize_known_preserves_loxone_inputs():
    doc = normalize_house_profiles_document(
        {
            "profiles": [
                {
                    "id": "p1",
                    "annual_kwh": 1000,
                    "consumers": [
                        {
                            "id": "pool",
                            "type": "generic",
                            "nominal_power_kw": 0.8,
                            "earnie_role": "known",
                            "schedule": {
                                "runs_per_week": 7,
                                "duration_h": 8.0,
                                "start_hour": 10,
                                "start_shift_h": 0.0,
                            },
                            "loxone_inputs": {"power_name": "Ernie_PoolFilter_P_act"},
                        }
                    ],
                }
            ]
        }
    )
    consumer = doc["profiles"]["p1"]["consumers"][0]
    assert consumer["earnie_role"] == EARNIE_ROLE_KNOWN
    assert consumer["loxone_inputs"] == {"power_name": "Ernie_PoolFilter_P_act"}


def test_normalize_manual_loxone_requires_power_name():
    with pytest.raises(ValueError, match="loxone_inputs.power_name"):
        normalize_house_profiles_document(
            {
                "profiles": [
                    {
                        "id": "p1",
                        "annual_kwh": 1000,
                        "consumers": [
                            {
                                "id": "wm",
                                "type": "generic",
                                "nominal_power_kw": 2.0,
                                "earnie_role": "manual",
                                "schedule": {
                                    "runs_per_week": 5,
                                    "duration_h": 2.0,
                                    "start_hour": 15,
                                    "start_shift_h": 4.0,
                                },
                                "appliance_recommendation": {
                                    "power_source": "loxone",
                                    "default_power_kw": 2.0,
                                    "default_runtime_h": 2.0,
                                },
                            }
                        ],
                    }
                ]
            }
        )
