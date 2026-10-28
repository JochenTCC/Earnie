"""Edibert P6: the weather / power-data access returns the pre-P6 outputs on recorded responses.

The golden ``tests/fixtures/opendata/`` was recorded with the pre-P6 access code against the real
services (``scripts.opendata_golden``); the replay answers ``requests.get`` from it, never the network.
"""
from __future__ import annotations

import json

import pytest

from scripts import opendata_golden as golden


@pytest.fixture(scope="module")
def expected():
    with (golden.FIXTURE_DIR / golden.EXPECTED_FILE).open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("opendata-cache")


@pytest.fixture(scope="module")
def replayed(cache_dir):
    """Cold Energy-Charts / EU archive cache: the same requests as before P6."""
    return golden.run_cases(golden.replay_get(golden.load_responses()), cache_dir=cache_dir)


def test_golden_covers_every_case(expected):
    assert sorted(golden.cases()) == sorted(expected["outputs"])


def _approx_floats(value):
    """Floats under a relative tolerance: the hourly mean of quarter slots may differ in the last ulp
    between pandas builds (summation order), which is not a P6 regression."""
    if isinstance(value, float):
        return pytest.approx(value, rel=1e-12, abs=1e-12)
    if isinstance(value, list):
        return [_approx_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _approx_floats(item) for key, item in value.items()}
    return value


@pytest.mark.parametrize("name", sorted(golden.cases()))
def test_output_matches_pre_p6(name, expected, replayed):
    outputs, _calls = replayed
    assert outputs[name] == _approx_floats(expected["outputs"][name])


@pytest.mark.parametrize("name", sorted(golden.cases()))
def test_requests_match_pre_p6(name, expected, replayed):
    _outputs, calls = replayed
    assert calls[name] == expected["requests"][name]


def test_warm_cache_serves_settled_archive_days_without_requests(cache_dir, replayed):
    """Second run on the filled cache: same outputs; Energy-Charts and the EU archive ask nothing."""
    outputs, _calls = replayed
    warm_outputs, warm_calls = golden.run_cases(golden.replay_get(golden.load_responses()), cache_dir=cache_dir)
    assert warm_outputs == outputs
    for name in ("eu_power", "country_power_month_edge", "at_day_ahead", "eu_weather_archive"):
        assert warm_calls[name] == [], name
    # Not cached: forecasts, and the site archive (own cache, use_cache=False / PV series)
    assert warm_calls["eu_weather_forecast"] and warm_calls["site_climate_bundle"]
