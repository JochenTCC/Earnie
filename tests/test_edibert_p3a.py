"""Edibert P3a: Earnie's pricing engine and the Edibert adapter give the same slot prices."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import config
from data.backtesting_prices import import_brutto_cent_for_slots, pricing_kwargs_from_resolved
from data.edibert_slot_prices import (
    EDIBERT_PRICING_KEY,
    import_cents,
    pricing_reference,
    require_pricing_reference,
)
from data.feed_in_prices import enrich_matrix_feed_in_prices, feed_in_settings_from_dict
from house_config.edibert_tariffs import EdibertLoadError
from house_config.scenario_resolution import resolve_scenario_settings
from scripts.edibert_parity import (
    FIXTURE_CASES,
    Case,
    build_fixture,
    earnie_prices,
    edibert_points,
)
from settings.pricing_engine import PRICING_ENGINE_ENV, pricing_engine, uses_edibert_pricing

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = str(REPO_ROOT / "share" / "config" / "tariffs.json")
GRID_FEES = str(REPO_ROOT / "share" / "config" / "grid_fees.json")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "edibert_parity" / "expected_prices.json"
TOLERANCE = 1e-4


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fixture_params() -> list:
    params = []
    for window in _fixture()["windows"]:
        for expected in window["expected"]:
            case_id = f"{window['name']}-{expected['direction']}-{expected['tariff_id']}"
            params.append(pytest.param(window, expected, id=case_id))
    return params


def _case(expected: dict) -> Case:
    return next(
        case
        for case in FIXTURE_CASES
        if case.direction == expected["direction"]
        and case.tariff_id == expected["tariff_id"]
        and case.area_id == expected["area_id"]
    )


# --- Flag -----------------------------------------------------------------------------


def test_engine_defaults_to_earnie(monkeypatch):
    monkeypatch.delenv(PRICING_ENGINE_ENV, raising=False)
    assert pricing_engine() == "earnie"
    assert not uses_edibert_pricing()
    monkeypatch.setenv(PRICING_ENGINE_ENV, "  ")
    assert pricing_engine() == "earnie"


def test_engine_edibert(monkeypatch):
    monkeypatch.setenv(PRICING_ENGINE_ENV, "Edibert")
    assert uses_edibert_pricing()


def test_unknown_engine_fails(monkeypatch):
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edbert")
    with pytest.raises(ValueError, match="EARNIE_PRICING_ENGINE"):
        pricing_engine()


# --- Committed fixture ----------------------------------------------------------------


def test_fixture_is_current():
    """Earnie still yields the committed prices (drops out with Earnie's engine in P3b)."""
    assert build_fixture(CATALOG, GRID_FEES) == _fixture()


# Triaged deviations (docs/dev/edibert-integration.md § P3a, triage table): Earnie bug, Edibert
# correct. Hourly settlement groups by wall-clock hour, so on the autumn DST night Earnie
# averages both 02:00 hours (CEST and CET, eight quarter-hours); Edibert per real hour.
DST_REPEATED_HOUR = {
    ("dst_autumn_2025", "import", "awattar_at"),
    ("dst_autumn_2025", "export", "dynamic_epex"),
}


@pytest.mark.parametrize(("window", "expected"), _fixture_params())
def test_edibert_matches_fixture(window, expected):
    slots = [datetime.fromisoformat(slot) for slot in window["slots"]]
    warnings: list[str] = []
    points = edibert_points(_case(expected), slots, window["epex_cent"], CATALOG, GRID_FEES, warnings)
    cents = [p.cent for p in points]
    if (window["name"], expected["direction"], expected["tariff_id"]) in DST_REPEATED_HOUR:
        repeated = [slot.hour == 2 for slot in slots]  # 02:00 CEST and 02:00 CET
        assert sum(repeated) == 8
        hours = [cents[i:i + 4] for i in range(0, len(cents), 4)]
        assert all(len(set(hour)) == 1 for hour in hours)  # one price per real hour
        assert hours[2][0] != hours[3][0]  # the two 02:00 hours are priced apart
        assert expected["cent"][8:16] == [expected["cent"][8]] * 8  # Earnie: one shared mean
        others = [(c, e) for c, e, r in zip(cents, expected["cent"], repeated) if not r]
        assert [c for c, _ in others] == pytest.approx([e for _, e in others], abs=TOLERANCE)
    else:
        assert cents == pytest.approx(expected["cent"], abs=TOLERANCE)
    if expected["grid_net_cent"] is not None:
        assert [p.grid_cent for p in points] == pytest.approx(expected["grid_net_cent"], abs=TOLERANCE)


def test_fixture_covers_dst_and_snap():
    windows = {window["name"]: window for window in _fixture()["windows"]}
    assert len(windows["dst_spring_2026"]["slots"]) == 12  # 23-hour day: 00:00–04:00 is 3 h
    assert len(windows["dst_autumn_2025"]["slots"]) == 20  # 25-hour day: 00:00–04:00 is 5 h
    snap = windows["snap_day"]
    awattar = next(e for e in snap["expected"] if e["tariff_id"] == "awattar_at")
    assert len(set(awattar["grid_net_cent"])) == 2  # base price outside, SNAP inside 10–16 h


# --- Seams with the flag --------------------------------------------------------------


@pytest.fixture
def scenario(tmp_path):
    profiles = tmp_path / "house_profiles.json"
    profiles.write_text(
        json.dumps({
            "profiles": [{
                "id": "home",
                "annual_kwh": 4000,
                "land": "AT",
                "latitude": 47.4,
                "longitude": 9.74,
                "timezone_name": "Europe/Vienna",
                "netznutzung": {"area_id": "AT-VBG", "quarter_hour_meter": True},
                "consumers": [],
            }]
        }),
        encoding="utf-8",
    )

    def resolve(import_id: str = "awattar_at", export_id: str = "dynamic_epex", **extra) -> dict:
        return resolve_scenario_settings(
            {"house_profile_id": "home", "import_tariff_id": import_id,
             "export_tariff_id": export_id, **extra},
            raw_config=config.CONFIG._raw_config,
            components_path=config.CONFIG.components_path,
            tariffs_path=CATALOG,
            house_profiles_path=str(profiles),
            grid_fees_path=GRID_FEES,
        )

    return resolve


def _snap_day_slots() -> tuple[list[datetime], list[float]]:
    """Naive house-time slots as the SE builds them, SNAP window inside."""
    slots = [datetime(2026, 7, 1, 6) + timedelta(minutes=15 * i) for i in range(48)]
    epex = [round(4.0 + 7.0 * ((i * 7) % 11 - 5) / 5.0, 4) for i in range(48)]
    return slots, epex


def test_reference_only_with_edibert_engine(monkeypatch, scenario):
    monkeypatch.delenv(PRICING_ENGINE_ENV, raising=False)
    assert EDIBERT_PRICING_KEY not in scenario()
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edibert")
    ref = scenario()[EDIBERT_PRICING_KEY]
    assert ref["import_tariff_id"] == "awattar_at"
    assert ref["netznutzung"]["area_id"] == "AT-VBG"
    json.dumps(ref)  # plain data: travels through SE workers and debug dumps


def test_import_seam_same_with_both_engines(monkeypatch, scenario):
    slots, epex = _snap_day_slots()
    monkeypatch.delenv(PRICING_ENGINE_ENV, raising=False)
    earnie = import_brutto_cent_for_slots(epex, slots, **pricing_kwargs_from_resolved(scenario()))
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edibert")
    edibert = import_brutto_cent_for_slots(epex, slots, **pricing_kwargs_from_resolved(scenario()))
    assert edibert == pytest.approx(earnie, abs=TOLERANCE)


def test_export_seam_same_with_both_engines(monkeypatch, scenario):
    slots, epex = _snap_day_slots()

    def k_push(resolved: dict) -> list[float]:
        matrix = [{"slot_datetime": s, "price_buy": e} for s, e in zip(slots, epex)]
        enrich_matrix_feed_in_prices(matrix, feed_in_settings_from_dict(resolved))
        return [row["k_push_act"] for row in matrix]

    monkeypatch.delenv(PRICING_ENGINE_ENV, raising=False)
    earnie = k_push(scenario())
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edibert")
    assert k_push(scenario()) == pytest.approx(earnie, abs=TOLERANCE)


def test_edibert_engine_never_falls_back_to_earnie(monkeypatch, scenario):
    """An hour the input covers only partly is Edibert's error, not Earnie's partial mean."""
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edibert")
    kwargs = pricing_kwargs_from_resolved(scenario())
    slots = [datetime(2026, 7, 1, 10, 30), datetime(2026, 7, 1, 10, 45)]
    with pytest.raises(EdibertLoadError) as info:
        import_brutto_cent_for_slots([5.0, 6.0], slots, **kwargs)
    assert info.value.code == "PRICE_MISSING"


def test_edibert_engine_needs_reference(monkeypatch):
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edibert")
    with pytest.raises(ValueError, match="Edibert-Preisreferenz"):
        import_brutto_cent_for_slots([5.0], [datetime(2026, 7, 1, 10)])
    with pytest.raises(ValueError, match="Edibert-Preisreferenz"):
        require_pricing_reference({}, where="Test")


def test_user_fixed_price_not_yet_on_edibert(monkeypatch, scenario):
    monkeypatch.setenv(PRICING_ENGINE_ENV, "edibert")
    with pytest.raises(ValueError, match="Eigener Festpreis"):
        scenario(import_id="__user_fixed__", user_import_cent_kwh=30.0)


def test_unknown_tariff_is_edibert_error():
    ref = pricing_reference(
        tariffs_path=CATALOG,
        grid_fees_path=GRID_FEES,
        import_tariff_id="no_such_tariff",
        export_tariff_id=None,
        timezone_name="Europe/Vienna",
        profile={"land": "AT"},
    )
    with pytest.raises(EdibertLoadError):
        import_cents([datetime(2026, 7, 1, 10)], [5.0], ref)


def test_harness_case_runs_on_aware_slots():
    case = Case("import", "awattar_at", "spot_hourly", "AT", "AT-VBG")
    slots = [datetime.fromisoformat(s) for s in _fixture()["windows"][2]["slots"]]
    epex = _fixture()["windows"][2]["epex_cent"]
    cents, grid = earnie_prices(case, slots, epex, CATALOG, GRID_FEES)
    assert len(cents) == len(slots) and grid is not None
