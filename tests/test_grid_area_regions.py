"""Grid areas by region: the ``regions`` of the catalog and the unique-area lookup."""
from __future__ import annotations

from pathlib import Path

from house_config.edibert_tariffs import area_in_region, grid_area_view, region_grid_area

SHARE_GRID_FEES = Path(__file__).resolve().parents[1] / "share" / "config" / "grid_fees.json"


def _area(land: str, regions: list[str]) -> dict:
    return {"label": "x", "land": land, "regions": regions}


def test_region_grid_area_needs_exactly_one_area_naming_the_region() -> None:
    areas = {
        "A": _area("AT", ["1"]),
        "B": _area("AT", ["2"]),
        "C": _area("AT", ["2"]),
        "U": _area("AT", []),  # user area: covers the whole land, never decides a region
        "D": _area("DE", ["1"]),
    }
    assert region_grid_area(areas, "AT", "1") == "A"
    assert region_grid_area(areas, "AT", "2") is None
    assert region_grid_area(areas, "AT", "3") is None


def test_area_in_region_treats_missing_regions_as_whole_land() -> None:
    assert area_in_region(_area("AT", ["4"]), "AT", "4")
    assert not area_in_region(_area("AT", ["4"]), "AT", "5")
    assert area_in_region(_area("AT", []), "AT", "5")
    assert not area_in_region(_area("DE", []), "AT", "5")


def test_catalog_unique_regions_of_austria() -> None:
    """Every AT catalog area names its Bundesland; unique are 1, 3, 5 and 9."""
    areas = grid_area_view(str(SHARE_GRID_FEES))["areas"]
    assert all(area["regions"] for area in areas.values() if area["land"] == "AT")
    unique = {
        region: region_grid_area(areas, "AT", region)
        for region in "123456789"
        if region_grid_area(areas, "AT", region)
    }
    assert unique == {"1": "AT-BGLD", "3": "AT-NOE", "5": "AT-SBG", "9": "AT-WIEN"}
