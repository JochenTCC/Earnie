"""Tests für Zeitzonen-Ableitung aus Koordinaten."""
from __future__ import annotations

from house_config.geo_timezone import lookup_timezone_name
from house_config.profiles_store import normalize_house_profiles_document


def test_lookup_timezone_vienna_area():
    assert lookup_timezone_name(48.2, 16.37) == "Europe/Vienna"


def test_lookup_timezone_munich_area():
    assert lookup_timezone_name(48.2, 11.0) == "Europe/Berlin"


def test_lookup_timezone_zurich_area():
    assert lookup_timezone_name(47.37, 8.54) == "Europe/Zurich"


def test_profile_normalization_derives_timezone():
    doc = normalize_house_profiles_document(
        {
            "profiles": [
                {
                    "id": "efh",
                    "annual_kwh": 4000.0,
                    "latitude": 48.2,
                    "longitude": 16.37,
                    "consumers": [],
                }
            ]
        }
    )
    profile = doc["profiles"]["efh"]
    assert profile["timezone_name"] == "Europe/Vienna"
