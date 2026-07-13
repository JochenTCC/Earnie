"""Step 1: profile_spec matrix — Hausprofil-Spec statt cons_data für Optimierung."""
from __future__ import annotations

import os
from datetime import date, datetime

import pandas as pd
import pytest

from house_config.planning_flex_bridge import (
    PROFILE_SPEC,
    planning_flex_daily_targets,
    profile_flat_baseload_kw,
    resolve_consumption_source,
    resolve_profile_spec_flex_targets,
    split_planning_generic_consumers,
)
from simulation.engine import (
    HistoricalDataCache,
    build_historical_matrix_for_slots,
    window_anchor_for_date,
    window_slot_datetimes,
)
from tests.fixtures.backtesting_fixtures import build_synthetic_prices_df
from tests.fixtures.historical_fixtures import CONS_DATA_FILE

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


HOUSE_PROFILE = {
    "id": "test_home",
    "annual_kwh": 8760.0,
    "baseload_kwh": 4000.0,
    "latitude": 48.0,
    "longitude": 10.0,
    "consumers": [
        {
            "id": "washer",
            "label": "Washer",
            "type": "generic",
            "nominal_power_kw": 2.0,
            "schedule": {
                "runs_per_week": 7,
                "duration_h": 2.0,
                "start_hour": 14,
                "start_shift_h": 6.0,
            },
        },
        {
            "id": "fixed_oven",
            "label": "Oven",
            "type": "generic",
            "nominal_power_kw": 1.5,
            "schedule": {
                "runs_per_week": 3,
                "duration_h": 1.0,
                "start_hour": 18,
                "start_shift_h": 0.0,
            },
        },
    ],
}


@pytest.fixture(scope="module")
def historical_cache() -> HistoricalDataCache:
    if not CONS_DATA_FILE.is_file():
        pytest.skip("historical cons_data fixture missing")
    cache = HistoricalDataCache(str(CONS_DATA_FILE))
    cache.load()
    return cache


def test_resolve_consumption_source_defaults():
    assert resolve_consumption_source(None) == "logged_day"
    assert resolve_consumption_source({}) == "logged_day"
    assert resolve_consumption_source({"_house_profile": HOUSE_PROFILE}) == PROFILE_SPEC
    assert (
        resolve_consumption_source(
            {"_house_profile": HOUSE_PROFILE, "consumption_source": "logged_day"}
        )
        == "logged_day"
    )


def test_profile_flat_baseload_kw():
    assert profile_flat_baseload_kw(HOUSE_PROFILE) == pytest.approx(4000.0 / 8760.0)


def test_planning_flex_targets_independent_of_cons_data():
    anchor = datetime(2025, 6, 14, 7, 0)
    slots = window_slot_datetimes(anchor)
    _fixed, flex = split_planning_generic_consumers(HOUSE_PROFILE)
    targets = planning_flex_daily_targets(flex, HOUSE_PROFILE, slots)
    assert "washer" in targets
    assert targets["washer"] > 0.0
    assert "fixed_oven" not in targets


def test_profile_spec_matrix_uses_profile_baseload_not_cons_data_total(
    historical_cache: HistoricalDataCache,
    monkeypatch,
):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)

    anchor = window_anchor_for_date(date(2025, 6, 14))
    slots = window_slot_datetimes(anchor)
    _fixed, flex = split_planning_generic_consumers(HOUSE_PROFILE)
    scenario = {
        "_house_profile": HOUSE_PROFILE,
        "_planning_flex_consumers": flex,
        "latitude": 48.0,
        "longitude": 10.0,
        "timezone_name": "Europe/Berlin",
    }
    prices_df = build_synthetic_prices_df(
        pd.Timestamp(anchor) - pd.Timedelta(days=1),
        pd.Timestamp(anchor) + pd.Timedelta(days=1),
    )

    matrix, meta = build_historical_matrix_for_slots(
        slots,
        historical_cache,
        prices_df,
        window_end=anchor,
        scenario_params=scenario,
    )

    assert meta["consumption_source"] == PROFILE_SPEC
    assert matrix[0]["consumption_mode"] == PROFILE_SPEC
    for row in matrix:
        assert row["expected_p_total"] == row["expected_p_act"]

    spec_targets = meta["consumer_daily_targets_kwh"]
    assert spec_targets.get("washer", 0.0) > 0.0
    assert meta["spec_flex_targets_kwh"]["washer"] == spec_targets["washer"]
    assert meta["spec_total_kwh"] == pytest.approx(
        meta["spec_baseload_kwh"] + sum(spec_targets.values()), rel=1e-6
    )


def test_logged_day_matrix_unchanged_without_house_profile(
    historical_cache: HistoricalDataCache,
):
    anchor = window_anchor_for_date(date(2025, 6, 14))
    slots = window_slot_datetimes(anchor)
    prices_df = build_synthetic_prices_df(pd.Timestamp(anchor), pd.Timestamp(anchor))
    matrix, meta = build_historical_matrix_for_slots(
        slots,
        historical_cache,
        prices_df,
        window_end=anchor,
        scenario_params=None,
    )
    assert meta["consumption_source"] == "logged_day"
    assert matrix[0]["consumption_mode"] == "logged_day"
    assert meta["consumer_daily_targets_kwh"] == meta["historical_totals"]


def test_resolve_profile_spec_flex_targets_merges_config_consumer():
    anchor = datetime(2025, 6, 14, 7, 0)
    slots = window_slot_datetimes(anchor)
    _fixed, flex = split_planning_generic_consumers(HOUSE_PROFILE)
    config_consumer = {"id": "eauto", "name": "E-Auto"}
    targets = resolve_profile_spec_flex_targets(
        flex + [config_consumer],
        HOUSE_PROFILE,
        slots,
        historical_totals={"eauto": 12.5},
    )
    assert targets["washer"] > 0.0
    assert targets["eauto"] == 12.5


EV_PROFILE = {
    "id": "ev_home",
    "annual_kwh": 6000.0,
    "baseload_kwh": 2000.0,
    "consumers": [
        {
            "id": "ev",
            "label": "EV",
            "type": "ev",
            "nominal_power_kw": 11.0,
            "min_power_kw": 1.4,
            "min_on_quarterhours": 4,
            "battery_capacity_kwh": 40.0,
            "charging_schedule": {
                "target_soc_percent": 100.0,
                "charging_efficiency": 0.95,
                "forecast_when_absent": True,
                "weekday": {
                    "car_available_from_hour": 18,
                    "ready_by_hour": 7,
                    "daily_rest_soc": 60.0,
                },
                "weekend": {
                    "car_available_from_hour": 18,
                    "ready_by_hour": 7,
                    "daily_rest_soc": 30.0,
                },
            },
        },
    ],
}


def test_planning_ev_to_milp_matches_prod_shape():
    from house_config.planning_flex_bridge import planning_ev_consumers, planning_ev_to_milp

    ev = EV_PROFILE["consumers"][0]
    milp = planning_ev_to_milp(ev)
    assert milp["id"] == "ev"
    assert milp["signal_type"] == "power"
    assert milp["daily_target_source"] == "config"
    assert milp["charging_schedule"]["enabled"] is True
    assert milp["battery_capacity_kwh"] == 40.0
    assert "loxone" not in milp["charging_schedule"]
    bridged = planning_ev_consumers(EV_PROFILE)
    assert len(bridged) == 1
    assert bridged[0]["charging_schedule"]["weekday"]["daily_rest_soc"] == 60.0


def test_planning_ev_daily_targets_from_profile():
    from house_config.planning_flex_bridge import (
        planning_ev_consumers,
        planning_ev_daily_targets,
    )

    anchor = datetime(2025, 6, 14, 7, 0)
    slots = window_slot_datetimes(anchor)
    flex = planning_ev_consumers(EV_PROFILE)
    targets = planning_ev_daily_targets(flex, EV_PROFILE, slots)
    assert targets["ev"] > 0.0


def test_resolve_consumer_battery_capacity_from_profile():
    from house_config.planning_flex_bridge import planning_ev_to_milp
    from integrations import loxone_client

    milp = planning_ev_to_milp(EV_PROFILE["consumers"][0])
    assert loxone_client.resolve_consumer_battery_capacity_kwh(milp) == pytest.approx(40.0)


def test_collect_planning_flex_includes_generic_and_ev():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    profile = {
        **HOUSE_PROFILE,
        "consumers": [
            *HOUSE_PROFILE["consumers"],
            EV_PROFILE["consumers"][0],
        ],
    }
    flex_ids = {item["id"] for item in collect_planning_flex_consumers(profile)}
    assert flex_ids == {"washer", "ev"}
    assert "fixed_oven" not in flex_ids


def test_validate_window_consumption_uses_spec_totals_for_profile_spec():
    from simulation.engine import validate_window_consumption

    meta = {
        "window_end": datetime(2025, 6, 14, 7, 0),
        "consumption_source": "profile_spec",
        "spec_total_kwh": 20.0,
        "spec_baseload_kwh": 12.0,
        "spec_flex_targets_kwh": {"washer": 8.0},
        "historical_total_kwh": 99.0,
        "historical_totals": {"washer": 50.0},
        "baseload_kwh": 12.0,
        "_flexible_consumers": [{"id": "washer", "name": "Washer"}],
    }
    rows = [
        {"Verbrauch-Prognose (kW)": 12.0, "Washer (kW)": 8.0},
    ]
    result = validate_window_consumption(rows, meta)
    assert result.ok
    assert result.historical_kwh == pytest.approx(20.0)
    assert result.historical_flex_kwh == pytest.approx(8.0)


def test_reference_hourly_load_uses_profile_not_cons_data(
    historical_cache: HistoricalDataCache,
    monkeypatch,
):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    from simulation.engine import resolve_reference_hourly_load

    install_open_meteo_climate_mock(monkeypatch)
    anchor = window_anchor_for_date(date(2025, 6, 14))
    slots = window_slot_datetimes(anchor)
    scenario = {
        "_house_profile": HOUSE_PROFILE,
        "latitude": 48.0,
        "longitude": 10.0,
        "timezone_name": "Europe/Berlin",
    }
    profile_load = resolve_reference_hourly_load(
        historical_cache, slots, scenario_params=scenario
    )
    cons_load = resolve_reference_hourly_load(
        historical_cache, slots, scenario_params=None
    )
    assert sum(profile_load) != pytest.approx(sum(cons_load), rel=0.01)


def test_build_per_scenario_reference_costs_adds_tariff_specific_ref(
    historical_cache: HistoricalDataCache,
):
    from simulation.engine import (
        HISTORICAL_REFERENCE_ID,
        build_per_scenario_reference_costs,
        scenario_reference_id,
        scenario_reference_label,
    )

    scenarios = {
        "live": {
            "_import_tariff_spec": {"id": "awattar_at", "type": "awattar"},
            "_export_tariff_spec": {"id": "fixed_37ct", "type": "fixed", "k_push_cent": 37.0},
            "feed_in_mode": "fixed",
            "k_push_cent": 37.0,
        },
        "fixed_only": {
            "_import_tariff_spec": {"id": "fixed_25ct", "type": "fixed_cent", "fix_cent_kwh": 25.0},
            "_export_tariff_spec": {"id": "fixed_37ct", "type": "fixed", "k_push_cent": 37.0},
            "feed_in_mode": "fixed",
            "k_push_cent": 37.0,
            "import_tariff_type": "fixed_cent",
            "import_fixed_cent_kwh": 25.0,
        },
    }
    anchor = window_anchor_for_date(date(2025, 6, 14))
    prices_df = build_synthetic_prices_df(pd.Timestamp(anchor), pd.Timestamp(anchor))
    extra, labels, mapping = build_per_scenario_reference_costs(
        pd.Timestamp(anchor.date()),
        pd.Timestamp(anchor.date()),
        prices_df,
        historical_cache,
        scenarios,
        live_scenario_id="live",
        scenario_labels={"fixed_only": "Fixed"},
    )
    assert mapping["live"] == HISTORICAL_REFERENCE_ID
    ref_id = scenario_reference_id("fixed_only")
    assert mapping["fixed_only"] == ref_id
    assert ref_id in extra
    assert ref_id in labels
    assert labels[ref_id] == scenario_reference_label("Fixed")
    assert len(extra[ref_id]) == 24


def test_build_per_scenario_reference_costs_pv_variant(
    historical_cache: HistoricalDataCache,
):
    from simulation.engine import (
        HISTORICAL_REFERENCE_ID,
        build_per_scenario_reference_costs,
        scenario_reference_id,
    )

    tariff_block = {
        "_import_tariff_spec": {"id": "fixed_25ct", "type": "fixed_cent", "fix_cent_kwh": 25.0},
        "_export_tariff_spec": {"id": "fixed_37ct", "type": "fixed", "k_push_cent": 37.0},
        "feed_in_mode": "fixed",
        "k_push_cent": 37.0,
        "import_tariff_type": "fixed_cent",
        "import_fixed_cent_kwh": 25.0,
    }
    scenarios = {
        "live": {**tariff_block, "pv_kwp": 8.0},
        "no_pv": {**tariff_block, "pv_kwp": 0.0},
        "no_battery": {**tariff_block, "pv_kwp": 8.0},
    }
    anchor = window_anchor_for_date(date(2025, 6, 14))
    prices_df = build_synthetic_prices_df(pd.Timestamp(anchor), pd.Timestamp(anchor))
    extra, _labels, mapping = build_per_scenario_reference_costs(
        pd.Timestamp(anchor.date()),
        pd.Timestamp(anchor.date()),
        prices_df,
        historical_cache,
        scenarios,
        live_scenario_id="live",
        scenario_labels={"no_pv": "No PV", "no_battery": "No Battery"},
    )
    assert mapping["no_pv"] == HISTORICAL_REFERENCE_ID
    live_ref_id = scenario_reference_id("live")
    assert mapping["live"] == live_ref_id
    assert mapping["no_battery"] == live_ref_id
    assert live_ref_id in extra
