"""Tests für Zeitzonen-Ableitung aus Land (AT/DE/CH)."""
from __future__ import annotations

from house_config.geo_timezone import timezone_for_land
from house_config.profiles_store import normalize_house_profiles_document


def test_timezone_for_land_at():
    assert timezone_for_land("AT") == "Europe/Vienna"


def test_timezone_for_land_de():
    assert timezone_for_land("DE") == "Europe/Berlin"


def test_timezone_for_land_ch():
    assert timezone_for_land("CH") == "Europe/Zurich"


def test_timezone_for_land_unknown_defaults_to_at():
    assert timezone_for_land("") == "Europe/Vienna"
    assert timezone_for_land("XX") == "Europe/Vienna"


def test_profile_normalization_derives_timezone_from_land():
    doc = normalize_house_profiles_document(
        {
            "profiles": [
                {
                    "id": "efh",
                    "annual_kwh": 4000.0,
                    "land": "DE",
                    "latitude": 48.2,
                    "longitude": 11.0,
                    "consumers": [],
                }
            ]
        }
    )
    profile = doc["profiles"]["efh"]
    assert profile["timezone_name"] == "Europe/Berlin"
