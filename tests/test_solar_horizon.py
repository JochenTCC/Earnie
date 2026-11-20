"""SUSI P3a — horizon shading: profile, sun position, mask, weather requests, house profile."""
from __future__ import annotations

import json

import math
from datetime import date, datetime, timedelta

import pytest
import requests

from data import open_meteo_solar_archive as archive
from data import outdoor_forecast as of
from data import solar_horizon as sh
from data.solar_horizon import HorizonProfile

# Dornbirn-like site; the sun is due south at about 11:21 UTC (longitude 9.7° E).
LAT, LON = 47.4, 9.7
_WALL = HorizonProfile(points=((-180.0, 90.0), (0.0, 90.0)))
# East half blocked up to 60°, west half free.
_EAST = HorizonProfile(
    points=((-179.0, 60.0), (-1.0, 60.0), (1.0, 0.0), (179.0, 0.0))
)


def _hours_utc(day: date) -> list[datetime]:
    return [datetime(day.year, day.month, day.day) + timedelta(hours=h) for h in range(24)]


# ------------------------------------------------------------------ profile


def test_elevation_is_interpolated_between_points_and_across_north():
    horizon = HorizonProfile(points=((-170.0, 10.0), (0.0, 0.0), (170.0, 30.0)))
    assert horizon.elevation_at(-85.0) == pytest.approx(5.0)
    assert horizon.elevation_at(85.0) == pytest.approx(15.0)
    # 170° → -170° spans 20° across ±180°: 30° falls to 10°.
    assert horizon.elevation_at(180.0) == pytest.approx(20.0)
    assert horizon.elevation_at(-180.0) == pytest.approx(20.0)
    assert horizon.elevation_at(175.0) == pytest.approx(25.0)
    assert horizon.elevation_at(-175.0) == pytest.approx(15.0)
    # 190° is the same direction as -170°.
    assert horizon.elevation_at(190.0) == pytest.approx(10.0)


def test_single_point_is_a_flat_horizon():
    assert HorizonProfile(points=((0.0, 12.0),)).elevation_at(123.0) == 12.0


def test_token_depends_on_the_points_only():
    a = HorizonProfile(points=((-90.0, 5.0), (90.0, 7.0)))
    assert a.token() == HorizonProfile(points=((-90.0, 5.0), (90.0, 7.0))).token()
    assert a.token() != HorizonProfile(points=((-90.0, 5.0), (90.0, 8.0))).token()


def test_missing_fields_mean_no_horizon():
    fields = sh.normalize_horizon_fields({}, label="p")
    assert fields == {"horizon_source": "none", "horizon": None}
    assert sh.stored_horizon_fields(fields) == {}
    assert sh.horizon_from_profile(fields) is None


def test_manual_horizon_is_sorted_and_applied():
    raw = {
        "horizon_source": "manual",
        "horizon": [
            {"azimuth_deg": 90, "elevation_deg": 5},
            {"azimuth_deg": -90, "elevation_deg": 20},
        ],
    }
    fields = sh.normalize_horizon_fields(raw, label="p")
    assert [p["azimuth_deg"] for p in fields["horizon"]] == [-90.0, 90.0]
    horizon = sh.horizon_from_profile(fields)
    assert horizon is not None and horizon.elevation_at(-90.0) == 20.0


def test_switched_off_horizon_is_kept_but_not_applied():
    raw = {"horizon_source": "none", "horizon": [{"azimuth_deg": 0, "elevation_deg": 20}]}
    fields = sh.normalize_horizon_fields(raw, label="p")
    assert sh.stored_horizon_fields(fields)["horizon_source"] == "none"
    assert sh.horizon_from_profile(fields) is None
    target = {"horizon": "old", "horizon_source": "manual"}
    sh.copy_horizon_fields(fields, target)
    assert target == {}


def test_flat_zero_horizon_shades_nothing():
    points = [{"azimuth_deg": a, "elevation_deg": 0.0} for a in (-90.0, 0.0, 90.0)]
    assert sh.horizon_from_profile({"horizon_source": "manual", "horizon": points}) is None


@pytest.mark.parametrize(
    "raw,match",
    [
        ({"horizon": [{"azimuth_deg": 0, "elevation_deg": 5}]}, "horizon_source fehlt"),
        ({"horizon_source": "manual"}, "horizon fehlt"),
        ({"horizon_source": "pvgis"}, "horizon_source muss"),
        ({"horizon_source": "manual", "horizon": []}, "nicht leere Liste"),
        (
            {"horizon_source": "manual", "horizon": [{"azimuth_deg": 200, "elevation_deg": 5}]},
            "zwischen -180 und 180",
        ),
        (
            {"horizon_source": "manual", "horizon": [{"azimuth_deg": 0, "elevation_deg": 95}]},
            "zwischen 0 und 90",
        ),
        (
            {"horizon_source": "manual", "horizon": [{"azimuth_deg": 0, "elevation_deg": True}]},
            "muss eine Zahl sein",
        ),
        (
            {
                "horizon_source": "manual",
                "horizon": [
                    {"azimuth_deg": 180, "elevation_deg": 5},
                    {"azimuth_deg": -180, "elevation_deg": 6},
                ],
            },
            "mehrfach",
        ),
        (
            {"horizon_source": "manual", "horizon": [{"azimuth_deg": 0, "elevation": 5}]},
            "unbekannte Felder",
        ),
    ],
)
def test_invalid_horizon_fields_fail_loud(raw, match):
    with pytest.raises(ValueError, match=match):
        sh.normalize_horizon_fields(raw, label="p")


# ------------------------------------------------------------------ sun position


def test_sun_position_at_solar_noon_of_the_solstices():
    elevation, azimuth = sh.sun_position(LAT, LON, datetime(2025, 6, 21, 11, 23))
    assert elevation == pytest.approx(90.0 - LAT + 23.44, abs=0.3)
    assert abs(azimuth) < 2.0
    winter, _ = sh.sun_position(LAT, LON, datetime(2025, 12, 21, 11, 19))
    assert winter == pytest.approx(90.0 - LAT - 23.44, abs=0.3)


def test_sun_azimuth_is_negative_in_the_morning_and_positive_in_the_evening():
    _, morning = sh.sun_position(LAT, LON, datetime(2025, 6, 21, 6, 0))
    _, evening = sh.sun_position(LAT, LON, datetime(2025, 6, 21, 17, 0))
    assert -120.0 < morning < -60.0
    assert 60.0 < evening < 120.0


def test_cos_incidence_of_horizontal_and_vertical_surfaces():
    assert sh.cos_incidence(30.0, 0.0, tilt_deg=0.0, azimuth_deg=0.0) == pytest.approx(0.5)
    assert sh.cos_incidence(0.0, 0.0, tilt_deg=90.0, azimuth_deg=0.0) == pytest.approx(1.0)
    # Sun behind a vertical surface.
    assert sh.cos_incidence(30.0, 180.0, tilt_deg=90.0, azimuth_deg=0.0) < 0.0


# ------------------------------------------------------------------ mask


def _shade(stamps, gti, dni, horizon, *, tilt=0.0, azimuth=0.0):
    return sh.shade_tilted_wm2(
        stamps, gti, dni, lat=LAT, lon=LON, tilt_deg=tilt, azimuth_deg=azimuth, horizon=horizon
    )


def test_sun_above_the_horizon_leaves_the_irradiance_unchanged():
    low = HorizonProfile(points=((-180.0, 5.0), (0.0, 5.0)))
    stamps = [datetime(2025, 6, 21, 12, 0)]
    assert _shade(stamps, [800.0], [700.0], low) == [800.0]


def test_sun_below_the_horizon_loses_the_beam_on_a_horizontal_surface():
    stamp = datetime(2025, 6, 21, 12, 0)
    # Hour 11:00–12:00 UTC: the mean of sin(elevation) over the four samples.
    mean_sin = sum(
        math.sin(math.radians(sh.sun_position(LAT, LON, stamp - timedelta(minutes=m))[0]))
        for m in (7.5, 22.5, 37.5, 52.5)
    ) / 4.0
    shaded = _shade([stamp], [800.0], [700.0], _WALL)
    assert shaded == [pytest.approx(800.0 - 700.0 * mean_sin, abs=0.01)]
    assert 100.0 < shaded[0] < 200.0


def test_shaded_irradiance_never_falls_below_zero():
    assert _shade([datetime(2025, 6, 21, 12, 0)], [100.0], [900.0], _WALL) == [0.0]


def test_night_hours_are_unchanged_and_need_no_dni():
    stamps = [datetime(2025, 6, 21, 0, 0), datetime(2025, 12, 21, 23, 0)]
    assert _shade(stamps, [0.0, 0.0], [None, None], _WALL) == [0.0, 0.0]


def test_a_surface_facing_away_from_the_sun_loses_nothing():
    # North-facing wall at noon: the beam does not reach it anyway.
    stamp = [datetime(2025, 12, 21, 12, 0)]
    assert _shade(stamp, [60.0], [700.0], _WALL, tilt=90.0, azimuth=180.0) == [60.0]


def test_the_hour_of_sunrise_counts_only_the_samples_with_the_sun_up():
    # Sunrise on 2025-03-20 at this site is about 05:28 UTC: part of the hour ending 06:00.
    stamp = datetime(2025, 3, 20, 6, 0)
    elevations = [
        sh.sun_position(LAT, LON, stamp - timedelta(minutes=m))[0] for m in (7.5, 22.5, 37.5, 52.5)
    ]
    up = [e for e in elevations if e > 0.0]
    assert 0 < len(up) < 4
    factor = sh.beam_blocked_factor(
        stamp, lat=LAT, lon=LON, tilt_deg=0.0, azimuth_deg=0.0, horizon=_WALL
    )
    assert factor == pytest.approx(sum(math.sin(math.radians(e)) for e in up) / len(up))


def test_east_horizon_shades_the_morning_only():
    stamps = _hours_utc(date(2025, 6, 21))
    gti = [500.0] * 24
    dni = [600.0] * 24
    shaded = _shade(stamps, gti, dni, _EAST)
    assert shaded[8] < 500.0  # 07:00–08:00 UTC, sun in the east below 60°
    assert shaded[15] == 500.0  # afternoon, sun in the west
    assert shaded[1] == 500.0  # night


def test_missing_values_stay_missing_and_missing_dni_is_not_guessed():
    stamps = [datetime(2025, 6, 21, 12, 0)] * 2
    assert _shade(stamps, [None, 800.0], [700.0, None], _WALL) == [None, None]


def test_series_of_different_length_fail_loud():
    with pytest.raises(ValueError, match="unterschiedlich lang"):
        _shade([datetime(2025, 6, 21, 12, 0)], [1.0, 2.0], [1.0], _WALL)


def test_payload_without_dni_fails_loud():
    payload = {"hourly": {"time": ["2025-06-21T12:00"], "global_tilted_irradiance": [800.0]}}
    with pytest.raises(ValueError, match="direct_normal_irradiance"):
        sh.shade_hourly_payload(
            payload,
            tilted_var="global_tilted_irradiance",
            dni_var="direct_normal_irradiance",
            lat=LAT,
            lon=LON,
            tilt_deg=0.0,
            azimuth_deg=0.0,
            horizon=_WALL,
        )


# ------------------------------------------------------------------ archive requests


class _Resp:
    status_code = 200
    headers: dict = {}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_archive(calls: list, *, gti: float = 500.0, dni: float = 600.0):
    def _get(url, params, timeout):
        calls.append(dict(params))
        first = date.fromisoformat(params["start_date"])
        last = date.fromisoformat(params["end_date"])
        times = []
        day = first
        while day <= last:
            times += [f"{day.isoformat()}T{hour:02d}:00" for hour in range(24)]
            day += timedelta(days=1)
        hourly = {"time": times}
        for name in params["hourly"].split(","):
            value = {"temperature_2m": 5.0, "direct_normal_irradiance": dni}.get(name, gti)
            hourly[name] = [value] * len(times)
        return _Resp({"hourly": hourly})

    return _get


def _bundle(monkeypatch, tmp_path, day: date, horizon, calls: list):
    monkeypatch.setattr(requests, "get", _fake_archive(calls))
    monkeypatch.setattr(archive, "archive_latest_complete_date", lambda: date(2026, 1, 1))
    surface = archive.TiltedSurface(tilt_deg=30.0, azimuth_deg=0.0)
    bundle = archive.build_open_meteo_climate_bundle(
        day,
        day,
        lat=LAT,
        lon=LON,
        timezone="Europe/Vienna",
        surfaces=[surface],
        cache_dir=tmp_path,
        horizon=horizon,
    )
    return bundle.tilted_wm2[surface]


def test_archive_without_horizon_asks_for_the_same_variables_and_file_as_before(
    monkeypatch, tmp_path
):
    calls: list = []
    series = _bundle(monkeypatch, tmp_path, date(2025, 6, 21), None, calls)
    assert sorted(call["hourly"] for call in calls) == [
        "global_tilted_irradiance",
        "temperature_2m",
    ]
    assert set(series) == {500.0}
    surface = [archive.TiltedSurface(30.0, 0.0)]
    args = (LAT, LON, "Europe/Vienna", date(2025, 6, 21), date(2025, 6, 21), surface)
    plain = archive.open_meteo_cache_path(*args, cache_dir=tmp_path)
    assert plain.name == "47.4000_9.7000_2025-06-21_2025-06-21_Europe-Vienna_30.0_0.0.json"
    assert plain.exists()
    shaded = archive.open_meteo_cache_path(*args, cache_dir=tmp_path, horizon=_EAST)
    assert shaded.name.endswith("_30.0_0.0_hzraw.json")
    assert not shaded.exists()


def test_archive_with_horizon_asks_for_dni_and_shades_the_local_morning(monkeypatch, tmp_path):
    calls: list = []
    series = _bundle(monkeypatch, tmp_path, date(2025, 6, 21), _EAST, calls)
    assert "global_tilted_irradiance,direct_normal_irradiance" in [c["hourly"] for c in calls]
    # Local summer time is UTC+2: 08:00–09:00 local is the hour stamped 07:00 UTC.
    assert series[datetime(2025, 6, 21, 9)] < 500.0
    assert series[datetime(2025, 6, 21, 17)] == 500.0
    assert series[datetime(2025, 6, 21, 2)] == 500.0
    # A second build needs no new request.
    before = len(calls)
    again = _bundle(monkeypatch, tmp_path, date(2025, 6, 21), _EAST, calls)
    assert len(calls) == before
    assert list(again) == list(series)


def test_another_horizon_reuses_the_weather_of_the_site(monkeypatch, tmp_path):
    """The cache file holds the unshaded data, so a changed horizon is masked locally."""
    calls: list = []
    day = date(2025, 6, 21)
    east = _bundle(monkeypatch, tmp_path, day, _EAST, calls)
    before = len(calls)
    wall = _bundle(monkeypatch, tmp_path, day, _WALL, calls)
    flat = _bundle(monkeypatch, tmp_path, day, HorizonProfile(points=((0.0, 0.0),)), calls)
    assert len(calls) == before
    assert [p.name for p in tmp_path.iterdir()] == [
        "47.4000_9.7000_2025-06-21_2025-06-21_Europe-Vienna_30.0_0.0_hzraw.json"
    ]
    assert set(flat) == {500.0}
    assert list(wall) != list(east)
    # A new process (no memory cache) reads the file and gets the same series.
    archive.clear_open_meteo_bundle_mem_cache()
    assert list(_bundle(monkeypatch, tmp_path, day, _EAST, calls)) == list(east)
    assert len(calls) == before


def test_incomplete_raw_cache_fails_loud(monkeypatch, tmp_path):
    calls: list = []
    day = date(2025, 6, 21)
    _bundle(monkeypatch, tmp_path, day, _EAST, calls)
    path = next(tmp_path.iterdir())
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["payloads"].pop(next(k for k in doc["payloads"] if k.startswith("temperature_2m")))
    path.write_text(json.dumps(doc), encoding="utf-8")
    archive.clear_open_meteo_bundle_mem_cache()
    with pytest.raises(ValueError, match="unvollständig"):
        _bundle(monkeypatch, tmp_path, day, _EAST, calls)


@pytest.mark.parametrize("day", [date(2025, 3, 30), date(2025, 10, 26)])
def test_dst_days_keep_the_mask_on_the_real_sun_time(monkeypatch, tmp_path, day):
    """The mask works on UTC stamps, so the clock change does not move it by an hour."""
    calls: list = []
    series = _bundle(monkeypatch, tmp_path, day, _EAST, calls)
    stamps = [datetime(day.year, day.month, day.day) + timedelta(hours=h) for h in range(-2, 24)]
    expected_utc = dict(
        zip(
            stamps,
            sh.shade_tilted_wm2(
                stamps,
                [500.0] * len(stamps),
                [600.0] * len(stamps),
                lat=LAT,
                lon=LON,
                tilt_deg=30.0,
                azimuth_deg=0.0,
                horizon=_EAST,
            ),
        )
    )
    # 12:00 local is 10:00 UTC in summer time (after the March change) and 11:00 UTC in
    # winter time (after the October change).
    noon_utc = datetime(day.year, day.month, day.day, 10 if day.month == 3 else 11)
    assert series[datetime(day.year, day.month, day.day, 12)] == expected_utc[noon_utc]
    assert series[datetime(day.year, day.month, day.day, 12)] < 500.0
    assert series[datetime(day.year, day.month, day.day, 16)] == 500.0
    if day.month == 3:
        assert datetime(day.year, day.month, day.day, 2) not in series.index


def test_previous_runs_with_horizon_use_the_dni_of_the_same_run(monkeypatch):
    calls: list = []
    monkeypatch.setattr(requests, "get", _fake_archive(calls))
    series = archive.fetch_hourly_tilted_irradiance_day1_forecast_wm2_series(
        date(2025, 6, 21),
        date(2025, 6, 21),
        lat=LAT,
        lon=LON,
        tilt=30.0,
        azimuth=0.0,
        timezone="Europe/Vienna",
        horizon=_EAST,
    )
    assert calls[0]["hourly"] == (
        "global_tilted_irradiance_previous_day1,direct_normal_irradiance_previous_day1"
    )
    assert series[datetime(2025, 6, 21, 9)] < 500.0
    assert series[datetime(2025, 6, 21, 17)] == 500.0


# ------------------------------------------------------------------ forecast request


@pytest.fixture
def _clear_forecast_caches():
    of._CACHE.clear()
    of._TILTED_CACHE.clear()
    yield
    of._CACHE.clear()
    of._TILTED_CACHE.clear()


def test_forecast_with_horizon_asks_for_dni_and_shades(monkeypatch, _clear_forecast_caches):
    calls: list = []
    today = datetime.now().date()

    def _forecast(_session, **kwargs):
        calls.append(kwargs)
        times, day = [], today - timedelta(days=1)
        while day <= today + timedelta(days=3):
            times += [f"{day.isoformat()}T{hour:02d}:00" for hour in range(24)]
            day += timedelta(days=1)
        hourly = {"time": times}
        for name in kwargs["hourly"]:
            value = {"temperature_2m": 5.0, "direct_normal_irradiance": 600.0}.get(name, 500.0)
            hourly[name] = [value] * len(times)
        return {"hourly": hourly}

    monkeypatch.setattr(of.open_meteo, "forecast", _forecast)
    monkeypatch.setattr(of.config, "get_planning_timezone", lambda: "UTC")
    start = datetime(today.year, today.month, today.day)
    kwargs = dict(
        horizon=24, tilt_deg=0.0, azimuth_deg=0.0, latitude=LAT, longitude=LON, start=start
    )
    plain = of.get_hourly_tilted_irradiance_forecast_wm2(**kwargs)
    shaded = of.get_hourly_tilted_irradiance_forecast_wm2(**kwargs, shading=_WALL)
    assert calls[0]["hourly"] == ("temperature_2m", "global_tilted_irradiance")
    assert calls[1]["hourly"] == (
        "temperature_2m",
        "global_tilted_irradiance",
        "direct_normal_irradiance",
    )
    assert plain == [500.0] * 24
    assert shaded[0] == 500.0  # midnight UTC
    assert shaded[12] < 500.0
    # Each horizon has its own cache entry; the unshaded one is not overwritten.
    assert of.get_hourly_tilted_irradiance_forecast_wm2(**kwargs) == plain
    assert len(calls) == 2


# ------------------------------------------------------------------ house profile


def _raw_profile(**extra) -> dict:
    return {
        "id": "home",
        "label": "Home",
        "annual_kwh": 4000.0,
        "latitude": LAT,
        "longitude": LON,
        "netznutzung": {"area_id": "AT-VBG"},
        "consumers": [],
        **extra,
    }


def _normalize(raw: dict) -> dict:
    from house_config.profiles_store import _normalize_profile

    return _normalize_profile(raw, 0, heating_systems=None)


def test_profile_without_horizon_has_no_horizon_keys():
    from house_config.profiles_store import _serialize_profile

    spec = _normalize(_raw_profile())
    assert "horizon" not in spec and "horizon_source" not in spec
    out = _serialize_profile(spec)
    assert "horizon" not in out and "horizon_source" not in out


def test_profile_horizon_survives_normalize_and_serialize():
    from house_config.profiles_store import _serialize_profile

    points = [{"azimuth_deg": -90.0, "elevation_deg": 12.0}, {"azimuth_deg": 90.0, "elevation_deg": 4.0}]
    spec = _normalize(_raw_profile(horizon_source="manual", horizon=points))
    assert spec["horizon_source"] == "manual" and spec["horizon"] == points
    out = _serialize_profile(spec)
    assert out["horizon_source"] == "manual" and out["horizon"] == points
    assert _normalize(out)["horizon"] == points


def test_profile_horizon_error_names_the_profile():
    with pytest.raises(ValueError, match="profiles 'home': horizon ist gesetzt"):
        _normalize(_raw_profile(horizon=[{"azimuth_deg": 0, "elevation_deg": 5}]))


def test_schema_accepts_the_horizon_fields():
    import json
    from pathlib import Path

    import jsonschema

    schema = json.loads(Path("share/config/house_profiles.schema.json").read_text(encoding="utf-8"))
    profile_schema = {**schema["definitions"]["profile"], "definitions": schema["definitions"]}
    good = _raw_profile(
        horizon_source="manual", horizon=[{"azimuth_deg": -180, "elevation_deg": 7.5}]
    )
    jsonschema.validate(good, profile_schema)
    bad = _raw_profile(horizon_source="manual", horizon=[{"azimuth_deg": 0, "elevation_deg": 120}])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, profile_schema)


# ------------------------------------------------------------------ wiring


def test_climate_context_passes_the_profile_horizon_to_the_bundle(monkeypatch):
    from data import modeled_climate as mc

    seen: list = []

    def _build(year, **kwargs):
        seen.append(kwargs["horizon"])
        return "bundle"

    monkeypatch.setattr(mc, "build_open_meteo_climate_bundle_for_year", _build)
    points = [{"azimuth_deg": 0.0, "elevation_deg": 15.0}]
    profile = {"latitude": LAT, "longitude": LON, "timezone_name": "Europe/Vienna"}
    mc.ModeledClimateContext.for_house_profile(profile, kwp=5.0)._bundle_for_calendar_year(2025)
    shaded_profile = {**profile, "horizon_source": "manual", "horizon": points}
    mc.ModeledClimateContext.for_house_profile(shaded_profile, kwp=5.0)._bundle_for_calendar_year(
        2025
    )
    assert seen[0] is None
    assert seen[1] == HorizonProfile(points=((0.0, 15.0),))


def test_reference_climate_reads_the_horizon_carried_by_the_thermal_block(monkeypatch):
    from data import modeled_climate as mc

    seen: list = []
    monkeypatch.setattr(
        mc,
        "build_open_meteo_climate_bundle_for_year",
        lambda year, **kwargs: seen.append(kwargs["horizon"]),
    )
    thermal = {
        "latitude": LAT,
        "longitude": LON,
        "timezone_name": "Europe/Vienna",
        "horizon_source": "manual",
        "horizon": [{"azimuth_deg": 0.0, "elevation_deg": 15.0}],
    }
    mc.reference_climate_for_thermal(thermal, house_profile=None, year=2025)
    mc.reference_climate_for_thermal(
        {k: v for k, v in thermal.items() if not k.startswith("horizon")},
        house_profile=None,
        year=2025,
    )
    assert seen == [HorizonProfile(points=((0.0, 15.0),)), None]


def test_thermal_parameters_are_derived_again_for_another_horizon(monkeypatch):
    from optimizer import thermal_parameters as tp
    from optimizer.thermal_year_cache import THERMAL_PARAMETERS_CACHE

    derived: list = []

    def _derive(thermal, house_profile, year):
        derived.append(thermal.get("horizon"))
        return tp.ThermalParameters(year, 1.0, None, None)

    monkeypatch.setattr(tp, "_derive_house_parameters", _derive)
    thermal = {
        "latitude": LAT,
        "longitude": LON,
        "timezone_name": "Europe/Vienna",
        "living_area_m2": 111.0,
        "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
    }
    points = [{"azimuth_deg": 0.0, "elevation_deg": 33.0}]
    profile = {"horizon_source": "manual", "horizon": points}
    try:
        tp.house_thermal_parameters(thermal, reference_year=2025)
        tp.house_thermal_parameters(thermal, house_profile=profile, reference_year=2025)
        tp.house_thermal_parameters(thermal, house_profile=profile, reference_year=2025)
    finally:
        THERMAL_PARAMETERS_CACHE.clear()
    # Without and with horizon are two derivations; the profile's horizon reaches the model.
    assert derived == [None, points]
