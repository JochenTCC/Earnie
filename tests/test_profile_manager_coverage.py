"""Additional coverage for profile_manager helpers (offline / mocked)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data import profile_manager as pm

VIENNA = ZoneInfo("Europe/Vienna")


def test_load_cons_data_profile_dataframe_empty():
    with patch.object(pm.cons_data_store, "load_cons_data", return_value=pd.DataFrame()):
        assert pm.load_cons_data_profile_dataframe() is None


def test_load_cons_data_pv_series_empty():
    with patch.object(pm.cons_data_store, "load_cons_data", return_value=pd.DataFrame()):
        series = pm.load_cons_data_pv_series()
    assert series.empty


def test_load_cons_data_pv_series_values():
    idx = pd.date_range("2024-01-01", periods=2, freq="h")
    cons = pd.DataFrame({"pv_kw": [1.5, 2.0]}, index=idx)
    with patch.object(pm.cons_data_store, "load_cons_data", return_value=cons):
        series = pm.load_cons_data_pv_series()
    assert series.tolist() == [1.5, 2.0]


def test_load_hourly_profile_missing_file_uses_defaults(tmp_path):
    hours = [datetime(2024, 6, 1, h) for h in (0, 12)]
    values = pm._load_hourly_profile(hours, str(tmp_path / "missing.csv"))
    assert values == [0.5, 0.5]


def test_load_hourly_profile_lookup_and_hour_fallback(tmp_path):
    path = tmp_path / "profiles.csv"
    path.write_text(
        "Month;Weekday;Hour;Consumption\n"
        "6;5;10;1.25\n"
        "6;5;11;0.75\n"
        "7;0;10;9.0\n",
        encoding="utf-8",
    )
    # Saturday 2024-06-01 is weekday 5
    exact = datetime(2024, 6, 1, 10)
    fallback_hour = datetime(2024, 6, 8, 11)  # different weekday, same hour fallback
    values = pm._load_hourly_profile([exact, fallback_hour], str(path))
    assert values[0] == pytest.approx(1.25)
    assert values[1] == pytest.approx(0.75)


def test_flex_profile_needs_regeneration_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(tmp_path / "flex.csv"))
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev"}]):
        assert pm._flex_profile_needs_regeneration() is True


def test_flex_profile_needs_regeneration_false_when_column_present(tmp_path, monkeypatch):
    path = tmp_path / "flex.csv"
    path.write_text("Month;Weekday;Hour;ev\n6;0;10;0.5\n", encoding="utf-8")
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(path))
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev"}]):
        assert pm._flex_profile_needs_regeneration() is False


def test_flex_profile_status_message_ok(tmp_path, monkeypatch):
    path = tmp_path / "flex.csv"
    path.write_text("Month;Weekday;Hour;ev;pool\n", encoding="utf-8")
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(path))
    msg = pm._flex_profile_status_message()
    assert "OK" in msg
    assert "2 Spalten" in msg


def test_check_and_update_profile_triggers_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "consumption_profiles_file", lambda: str(tmp_path / "c.csv"))
    monkeypatch.setattr(pm, "total_consumption_profiles_file", lambda: str(tmp_path / "t.csv"))
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(tmp_path / "f.csv"))
    called = {"n": 0}

    def _fake_generate() -> bool:
        called["n"] += 1
        return True

    monkeypatch.setattr(pm, "generate_consumption_profile", _fake_generate)
    with patch.object(pm.config, "get_flexible_consumers", return_value=[]):
        pm.check_and_update_profile_if_new_month()
    assert called["n"] == 1


def test_build_optimization_matrix_requires_equal_lengths():
    with pytest.raises(ValueError, match="gleiche Länge"):
        pm._build_optimization_matrix(
            market_data=[],
            forecast_consumption=[1.0],
            forecast_pv=[1.0, 2.0],
            target_hours=[datetime(2024, 1, 1, 0)],
        )


def test_build_optimization_matrix_builds_rows(monkeypatch):
    hours = [datetime(2024, 6, 1, h) for h in range(2)]
    monkeypatch.setattr(
        pm.market_prices,
        "resolve_market_slots",
        lambda _m, targets, **_k: [
            {
                "hour": t.hour,
                "k_act": 10.0,
                "price_buy": 0.1,
                "price_source": "exact",
            }
            for t in targets
        ],
    )
    monkeypatch.setattr(pm, "resolve_market_slots_kwargs", lambda _targets: {})
    monkeypatch.setattr(
        "data.backtesting_prices.enrich_slots_import_prices",
        lambda slots, *_a, **_k: slots,
    )
    monkeypatch.setattr(
        "data.backtesting_prices.pricing_kwargs_from_resolved",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        pm.config,
        "get_resolved_runtime_settings",
        lambda: {},
    )
    monkeypatch.setattr(pm.config, "get_feed_in_settings", lambda: {})
    monkeypatch.setattr(
        pm.feed_in_prices,
        "enrich_matrix_feed_in_prices",
        lambda *_a, **_k: None,
    )
    matrix = pm._build_optimization_matrix(
        market_data=[{"x": 1}],
        forecast_consumption=[0.5, 0.6],
        forecast_pv=[0.1, 0.2],
        forecast_total_consumption=[1.0, 1.1],
        target_hours=hours,
    )
    assert len(matrix) == 2
    assert matrix[0]["expected_p_act"] == 0.5
    assert matrix[0]["expected_p_total"] == 1.0
    assert matrix[1]["expected_p_pv"] == 0.2


def test_get_cons_data_date_bounds_empty():
    with patch.object(pm.cons_data_store, "get_date_bounds", return_value=(None, None)):
        assert pm.get_cons_data_date_bounds() == (None, None)


def test_get_cons_data_date_bounds_from_store():
    with patch.object(
        pm.cons_data_store,
        "get_date_bounds",
        return_value=(datetime(2024, 1, 2, 3), datetime(2024, 6, 7, 8)),
    ):
        assert pm.get_cons_data_date_bounds() == (date(2024, 1, 2), date(2024, 6, 7))


def test_get_historical_date_picker_bounds_without_cons_data(monkeypatch):
    monkeypatch.setattr(pm, "get_cons_data_date_bounds", lambda: (None, None))
    lo, hi = pm.get_historical_date_picker_bounds(months_back=1)
    assert lo < hi


def test_get_historical_day_data_empty_cons(monkeypatch):
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: None)
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev", "name": "EV"}]):
        base, totals, total = pm.get_historical_day_data("2024-06-01")
    assert base == [0.5] * 24
    assert totals == {"ev": 0.0}
    assert total == [0.5] * 24


def test_get_historical_day_data_from_frame(monkeypatch):
    idx = pd.date_range("2024-06-01", periods=24, freq="h")
    frame = pd.DataFrame(
        {
            "Total": [2.0] * 24,
            "BaseLoad": [1.0] * 24,
            "EV": [0.5] * 24,
        },
        index=idx,
    )
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: frame)
    with patch.object(
        pm.config,
        "get_flexible_consumers",
        return_value=[{"id": "ev", "name": "EV"}],
    ):
        base, totals, total = pm.get_historical_day_data(date(2024, 6, 1))
    assert base == [1.0] * 24
    assert totals["ev"] == pytest.approx(12.0)
    assert total == [2.0] * 24


def test_compute_live_planning_window_requires_aware_now():
    with pytest.raises(ValueError, match="timezone-aware"):
        pm.compute_live_planning_window(datetime(2024, 6, 1, 12))


def test_compute_live_planning_window_delegates(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(pm.config, "get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr(pm.config, "get", lambda *_a, **_k: 48.0)
    monkeypatch.setattr(
        "data.planning_window.compute_planning_window",
        lambda *_a, **_k: sentinel,
    )
    now = datetime(2024, 6, 1, 12, tzinfo=VIENNA)
    assert pm.compute_live_planning_window(now) is sentinel


def test_cons_data_to_profile_dataframe_maps_columns(monkeypatch):
    idx = pd.date_range("2024-06-01", periods=2, freq="h")
    cons = pd.DataFrame(
        {
            "total_kw": [2.0, 3.0],
            "baseload_kw": [1.0, 1.5],
            "pv_kw": [0.2, 0.3],
            "ev_kw": [0.5, 0.7],
        },
        index=idx,
    )
    monkeypatch.setattr(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids",
        lambda: ["ev"],
    )
    monkeypatch.setattr(
        "data.cons_data_house_profile.consumer_labels_for_ids",
        lambda _ids: {"ev": "Smart"},
    )
    frame = pm._cons_data_to_profile_dataframe(cons)
    assert list(frame["Total"]) == [2.0, 3.0]
    assert list(frame["BaseLoad"]) == [1.0, 1.5]
    assert list(frame["Smart"]) == [0.5, 0.7]


def test_generate_consumption_profile_empty_returns_false(monkeypatch):
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: None)
    monkeypatch.setattr(pm.cons_data_store, "get_output_path", lambda: "missing.csv")
    assert pm.generate_consumption_profile() is False


def test_generate_consumption_profile_exception_returns_false(monkeypatch):
    monkeypatch.setattr(
        pm,
        "_load_profile_source_dataframe",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert pm.generate_consumption_profile() is False


def test_generate_consumption_profile_writes_base_and_total(tmp_path, monkeypatch):
    cons_path = tmp_path / "consumption_profiles.csv"
    total_path = tmp_path / "total_consumption_profiles.csv"
    flex_path = tmp_path / "flexible_consumer_profiles.csv"
    idx = pd.date_range("2024-06-01 10:00:00", periods=2, freq="h")
    source = pd.DataFrame(
        {"Total": [2.0, 3.0], "BaseLoad": [1.0, 1.5]},
        index=idx,
    )
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: source)
    monkeypatch.setattr(pm, "consumption_profiles_file", lambda: str(cons_path))
    monkeypatch.setattr(pm, "total_consumption_profiles_file", lambda: str(total_path))
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(flex_path))
    monkeypatch.setattr(pm, "_flex_profile_export_spec", lambda _df: ([], {}))
    assert pm.generate_consumption_profile() is True
    base = pd.read_csv(cons_path, sep=";")
    total = pd.read_csv(total_path, sep=";")
    assert "Consumption" in base.columns
    assert float(base["Consumption"].iloc[0]) == pytest.approx(1.0)
    assert float(total["Consumption"].iloc[1]) == pytest.approx(3.0)
    assert not flex_path.exists()


def test_flex_profile_needs_regeneration_consumption_only(tmp_path, monkeypatch):
    path = tmp_path / "flex.csv"
    path.write_text("Month;Weekday;Hour;Consumption\n6;0;10;0.5\n", encoding="utf-8")
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(path))
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev"}]):
        assert pm._flex_profile_needs_regeneration() is True


def test_flex_profile_status_missing_and_empty(tmp_path, monkeypatch):
    missing = tmp_path / "missing.csv"
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(missing))
    assert "fehlt" in pm._flex_profile_status_message()

    empty = tmp_path / "empty.csv"
    empty.write_text("Month;Weekday;Hour\n", encoding="utf-8")
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(empty))
    assert "ohne Verbraucher-Spalten" in pm._flex_profile_status_message()


def test_check_and_update_profile_skips_when_current(tmp_path, monkeypatch):
    cons = tmp_path / "c.csv"
    total = tmp_path / "t.csv"
    flex = tmp_path / "f.csv"
    for path in (cons, total, flex):
        path.write_text("Month;Weekday;Hour;ev\n", encoding="utf-8")
    monkeypatch.setattr(pm, "consumption_profiles_file", lambda: str(cons))
    monkeypatch.setattr(pm, "total_consumption_profiles_file", lambda: str(total))
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(flex))
    monkeypatch.setattr(pm, "_flex_profile_needs_regeneration", lambda: False)
    monkeypatch.setattr(
        pm,
        "planning_now",
        lambda: datetime.fromtimestamp(cons.stat().st_mtime),
    )
    called = {"n": 0}
    monkeypatch.setattr(
        pm,
        "generate_consumption_profile",
        lambda: called.__setitem__("n", called["n"] + 1) or True,
    )
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev"}]):
        pm.check_and_update_profile_if_new_month()
    assert called["n"] == 0


def test_check_and_update_profile_on_new_month(tmp_path, monkeypatch):
    cons = tmp_path / "c.csv"
    total = tmp_path / "t.csv"
    flex = tmp_path / "f.csv"
    for path in (cons, total, flex):
        path.write_text("Month;Weekday;Hour;ev\n", encoding="utf-8")
    # Force "old" mtime via planning_now in a later month.
    monkeypatch.setattr(pm, "consumption_profiles_file", lambda: str(cons))
    monkeypatch.setattr(pm, "total_consumption_profiles_file", lambda: str(total))
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(flex))
    monkeypatch.setattr(pm, "_flex_profile_needs_regeneration", lambda: False)
    file_month = datetime.fromtimestamp(cons.stat().st_mtime)
    later = file_month.replace(year=file_month.year + 1)
    monkeypatch.setattr(pm, "planning_now", lambda: later)
    called = {"n": 0}
    monkeypatch.setattr(
        pm,
        "generate_consumption_profile",
        lambda: called.__setitem__("n", called["n"] + 1) or True,
    )
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev"}]):
        pm.check_and_update_profile_if_new_month()
    assert called["n"] == 1


def test_apply_house_profile_baseload_overlay_noop_without_profile(monkeypatch):
    monkeypatch.setattr(
        pm.config,
        "get_resolved_runtime_settings",
        lambda: {},
    )
    hours = [datetime(2024, 6, 1, 12)]
    assert pm._apply_house_profile_baseload_overlay(hours, [0.4]) == [0.4]


def test_load_consumption_and_total_profiles(monkeypatch):
    hours = [datetime(2024, 6, 1, 10), datetime(2024, 6, 1, 11)]
    monkeypatch.setattr(pm, "_load_hourly_profile", lambda *_a, **_k: [0.2, 0.3])
    monkeypatch.setattr(
        pm, "_apply_house_profile_baseload_overlay", lambda _h, base: [b + 1 for b in base]
    )
    assert pm._load_consumption_profile(hours) == [1.2, 1.3]
    assert pm._load_total_consumption_profile(hours) == [0.2, 0.3]


def test_load_flexible_consumer_profiles_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "flexible_consumer_profiles_file", lambda: str(tmp_path / "missing.csv")
    )
    with patch.object(
        pm.config,
        "get_flexible_consumers",
        return_value=[{"id": "ev"}, {"id": "pool"}],
    ):
        profiles = pm._load_flexible_consumer_hourly_profiles(
            [datetime(2024, 6, 1, 10)]
        )
    assert profiles == {"ev": [0.0], "pool": [0.0]}


def test_load_flexible_consumer_profiles_corrupt_csv(tmp_path, monkeypatch):
    path = tmp_path / "flex.csv"
    path.write_text("not;a;valid\nprofile\n", encoding="utf-8")
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(path))
    with patch.object(pm.config, "get_flexible_consumers", return_value=[{"id": "ev"}]):
        profiles = pm._load_flexible_consumer_hourly_profiles(
            [datetime(2024, 6, 1, 10), datetime(2024, 6, 1, 11)]
        )
    assert profiles == {"ev": [0.0, 0.0]}


def test_build_live_planning_matrix_wires_helpers(monkeypatch):
    class _Window:
        slot_datetimes = [datetime(2024, 6, 1, 12), datetime(2024, 6, 1, 13)]

    matrix = [{"hour": 12}, {"hour": 13}]
    calls = {"check": 0, "log": 0, "warn": 0}

    monkeypatch.setattr(
        pm,
        "check_and_update_profile_if_new_month",
        lambda: calls.__setitem__("check", calls["check"] + 1),
    )
    monkeypatch.setattr(
        "data.live_planning_matrix.assemble_live_planning_rows",
        lambda _market, hours: (matrix, {"ev": [0.1] * len(hours)}),
    )
    monkeypatch.setattr(
        "data.live_planning_matrix.log_live_flex_horizon",
        lambda _flex: calls.__setitem__("log", calls["log"] + 1),
    )
    monkeypatch.setattr(
        "data.live_planning_matrix.warn_live_matrix_price_extrapolation",
        lambda _matrix: calls.__setitem__("warn", calls["warn"] + 1),
    )
    out = pm.build_live_planning_matrix([{"m": 1}], _Window())
    assert out is matrix
    assert calls == {"check": 1, "log": 1, "warn": 1}


def test_get_forecast_vectors_assembles_matrix(monkeypatch):
    now = datetime(2024, 6, 1, 8, 0, 0)
    monkeypatch.setattr(pm, "planning_now", lambda: now)
    monkeypatch.setattr(pm, "check_and_update_profile_if_new_month", lambda: None)
    monkeypatch.setattr(pm, "_load_consumption_profile", lambda hours: [0.5] * len(hours))
    monkeypatch.setattr(
        pm, "_load_total_consumption_profile", lambda hours: [1.0] * len(hours)
    )
    monkeypatch.setattr(
        pm,
        "_load_flexible_consumer_hourly_profiles",
        lambda hours: {"ev": [0.2] * len(hours)},
    )
    monkeypatch.setattr(pm.pv_forecast, "get_hourly_pv_forecast", lambda: [0.1] * 24)

    def _matrix(market, cons, pv, forecast_total_consumption=None, target_hours=None):
        assert len(cons) == 24
        assert forecast_total_consumption == [1.0] * 24
        return [
            {
                "hour": i,
                "expected_p_act": cons[i],
                "expected_p_pv": pv[i],
            }
            for i in range(24)
        ]

    monkeypatch.setattr(pm, "_build_optimization_matrix", _matrix)
    cons, pv, matrix = pm.get_forecast_vectors([{"x": 1}])
    assert cons == [0.5] * 24
    assert pv == [0.1] * 24
    assert matrix[0]["expected_flex_kw"] == {"ev": 0.2}
    assert len(matrix) == 24


def test_get_historical_date_picker_bounds_intersects(monkeypatch):
    today = datetime.now().date()
    cons_min = today - timedelta(days=60)
    cons_max = today - timedelta(days=5)
    monkeypatch.setattr(
        pm,
        "get_cons_data_date_bounds",
        lambda: (cons_min, cons_max),
    )
    lo, hi = pm.get_historical_date_picker_bounds(months_back=12)
    assert lo == cons_min
    assert hi == cons_max


