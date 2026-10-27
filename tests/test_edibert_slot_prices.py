"""Slot prices through Edibert (P3a parity fixture, P3b only engine): adapter and seams."""
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
    price_points,
    pricing_reference,
    require_pricing_reference,
)
from data.feed_in_prices import enrich_matrix_feed_in_prices, feed_in_settings_from_dict
from house_config.edibert_tariffs import EdibertLoadError
from house_config.netznutzung import default_netznutzung_config
from house_config.scenario_resolution import resolve_scenario_settings

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


def _fixture_points(expected: dict, slots: list[datetime], epex: list[float]) -> list:
    """The adapter for one fixture case, ``netznutzung`` as the house profile writes it."""
    profile: dict = {"land": expected["land"]}
    if expected["area_id"]:
        profile["netznutzung"] = {**default_netznutzung_config(), "area_id": expected["area_id"]}
    direction = expected["direction"]
    ref = pricing_reference(
        tariffs_path=CATALOG,
        grid_fees_path=GRID_FEES,
        import_tariff_id=expected["tariff_id"] if direction == "import" else None,
        export_tariff_id=expected["tariff_id"] if direction == "export" else None,
        timezone_name=_fixture()["timezone"],
        profile=profile,
    )
    return price_points(direction, slots, epex, ref)


# --- Committed fixture (Earnie's prices before P3b; also Edibert's compatibility data) ---

# Triaged deviations (docs/dev/edibert-integration.md § P3a, triage table): Earnie bug, Edibert
# correct. Hourly settlement grouped by wall-clock hour, so on the autumn DST night Earnie
# averaged both 02:00 hours (CEST and CET, eight quarter-hours); Edibert per real hour.
DST_REPEATED_HOUR = {
    ("dst_autumn_2025", "import", "awattar_at"),
    ("dst_autumn_2025", "export", "dynamic_epex"),
}


@pytest.mark.parametrize(("window", "expected"), _fixture_params())
def test_edibert_matches_fixture(window, expected):
    slots = [datetime.fromisoformat(slot) for slot in window["slots"]]
    points = _fixture_points(expected, slots, window["epex_cent"])
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


# --- Seams ------------------------------------------------------------------------------


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


def test_resolution_attaches_plain_reference(scenario):
    ref = scenario()[EDIBERT_PRICING_KEY]
    assert ref["import_tariff_id"] == "awattar_at"
    assert ref["netznutzung"]["area_id"] == "AT-VBG"
    json.dumps(ref)  # plain data: travels through SE workers and debug dumps


def test_import_seam_prices_snap_window(scenario):
    slots, epex = _snap_day_slots()
    kwargs = pricing_kwargs_from_resolved(scenario())
    k_act = import_brutto_cent_for_slots(epex, slots, **kwargs)
    points = price_points("import", slots, epex, kwargs["edibert_pricing"])
    assert k_act == [p.cent for p in points]
    grid = {round(p.grid_cent, 4) for p in points}
    assert grid == {4.96, 3.968}  # base price outside, SNAP (−20 %) inside 10–16 h


def test_export_seam_fills_every_row(scenario):
    slots, epex = _snap_day_slots()
    matrix = [{"slot_datetime": s, "price_buy": e} for s, e in zip(slots, epex)]
    enrich_matrix_feed_in_prices(matrix, feed_in_settings_from_dict(scenario()))
    ref = scenario()[EDIBERT_PRICING_KEY]
    assert [row["k_push_act"] for row in matrix] == [
        p.cent for p in price_points("export", slots, epex, ref)
    ]


def test_partial_hour_without_market_source_is_an_error(scenario):
    """An hour the input covers only partly is Edibert's error, never a partial mean."""
    kwargs = pricing_kwargs_from_resolved(scenario())
    slots = [datetime(2026, 7, 1, 10, 30), datetime(2026, 7, 1, 10, 45)]
    with pytest.raises(EdibertLoadError) as info:
        import_brutto_cent_for_slots([5.0, 6.0], slots, **kwargs)
    assert info.value.code == "PRICE_MISSING"


def test_pricing_needs_reference():
    with pytest.raises(ValueError, match="Edibert-Preisreferenz"):
        import_brutto_cent_for_slots([5.0], [datetime(2026, 7, 1, 10)])
    with pytest.raises(ValueError, match="Edibert-Preisreferenz"):
        require_pricing_reference({}, where="Test")


USER_FIXED = {
    "import_id": "__user_fixed__",
    "export_id": "__user_fixed__",
    "user_import_cent_kwh": 30.0,
    "user_export_cent_kwh": 8.0,
}


def test_user_fixed_price_with_land_vat_on_grid_fee(scenario):
    """T3: Eigener Festpreis, gross with the land's VAT on the net grid fee (AT-VBG, SNAP day)."""
    slots, epex = _snap_day_slots()
    resolved = scenario(**USER_FIXED)
    assert resolved[EDIBERT_PRICING_KEY]["user_fixed"] == {
        "import": {"cent": 30.0, "vat_percent": 20.0},
        "export": {"cent": 8.0, "vat_percent": 0.0},
    }
    k_act = import_brutto_cent_for_slots(epex, slots, **pricing_kwargs_from_resolved(resolved))
    matrix = [{"slot_datetime": s, "price_buy": e} for s, e in zip(slots, epex)]
    enrich_matrix_feed_in_prices(matrix, feed_in_settings_from_dict(resolved))
    assert sorted(set(k_act)) == pytest.approx([30.0 + 3.968 * 1.2, 30.0 + 4.96 * 1.2])
    assert {row["k_push_act"] for row in matrix} == {8.0}


def test_user_fixed_reference_needs_values():
    with pytest.raises(ValueError, match="Eigener Festpreis"):
        pricing_reference(
            tariffs_path=CATALOG,
            grid_fees_path=GRID_FEES,
            import_tariff_id="__user_fixed__",
            export_tariff_id=None,
            timezone_name="Europe/Vienna",
            profile={"land": "AT"},
        )


@pytest.mark.parametrize(
    ("month", "rule", "used", "cent"),
    [((2026, 6), "prior_year", "2025-06", 7.5), ((2026, 8), "prior_month", "2026-07", 9.25)],
)
def test_monthly_fallback_surfaced(tmp_path, month, rule, used, cent):
    """Edibert's MONTH_RATE_FALLBACK (Earnie's former order): prior year, then prior month."""
    rates = [
        {"year": 2025, "month": 6, "tariff_cent_kwh": 7.5},
        {"year": 2026, "month": 7, "tariff_cent_kwh": 9.25},
    ]
    tariff = {
        "id": "gap_table", "label": "Gap", "type": "monthly_table", "land": "AT",
        "supplier_id": "test", "prices_include_vat": False, "vat_percent": 0.0,
        "monthly_rates": rates,
    }
    tariffs_path = tmp_path / "tariffs.json"
    tariffs_path.write_text(
        json.dumps({"tariff_format": 1, "import_tariffs": [], "export_tariffs": [tariff]}),
        encoding="utf-8",
    )
    ref = pricing_reference(
        tariffs_path=str(tariffs_path), grid_fees_path=None, import_tariff_id=None,
        export_tariff_id="gap_table", timezone_name="Europe/Vienna", profile={"land": "AT"},
    )
    warnings: list[str] = []
    slot = datetime(month[0], month[1], 15, 12)
    points = price_points("export", [slot], [None], ref, warnings_out=warnings)
    assert points[0].cent == pytest.approx(cent)
    assert any(
        w.startswith("MONTH_RATE_FALLBACK(") and f"rule={rule}" in w and f"used_month={used}" in w
        for w in warnings
    )


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
