# tests/test_multi_scenario_pv_charts.py
"""SE cons_data PV overlays: unique configs + per-PV weekly series."""
from __future__ import annotations

from datetime import datetime

from ui.chart_colors import PV_YELLOW_PALETTE
from ui.consumption_display.adapters import (
    collect_unique_planning_pv,
    collect_unique_pv_configs,
    joined_pv_config_label,
    with_modeled_pv_from_all_scenarios,
)
from ui.consumption_display.charts import stacked_monthly_chart, week_timeseries_chart
from ui.consumption_display.types import ConsumptionSeriesBundle


def _pv(pv_id: str, label: str, *, kwp: float = 5.0, tilt: float = 20.0) -> dict:
    return {
        "id": pv_id,
        "label": label,
        "pv_kwp": kwp,
        "pv_tilt": tilt,
        "pv_azimuth": 0.0,
    }


def _scenario(*, planning: list[dict], lat: float = 48.0) -> dict:
    return {
        "latitude": lat,
        "longitude": 10.0,
        "timezone_name": "Europe/Vienna",
        "_house_profile": {
            "id": "home",
            "latitude": lat,
            "longitude": 10.0,
            "default_pv_tilt": 20.0,
            "default_pv_azimuth": 0.0,
            "consumers": [],
        },
        "pv_kwp": sum(float(item["pv_kwp"]) for item in planning),
        "_planning_pv_systems": planning,
    }


def test_collect_unique_planning_pv_dedupes_by_id():
    scenarios = {
        "live": _scenario(planning=[_pv("a", "Süd"), _pv("b", "Ost")]),
        "alt": _scenario(planning=[_pv("b", "Ost (dup)"), _pv("c", "West")]),
    }
    unique = collect_unique_planning_pv(scenarios)
    assert [item["id"] for item in unique] == ["a", "b", "c"]
    assert unique[1]["label"] == "Ost"


def test_collect_unique_pv_configs_and_joined_label():
    scenarios = {
        "live": _scenario(planning=[_pv("dach_sued", "Dach Süd")]),
        "batt": _scenario(planning=[_pv("dach_sued", "Dach Süd")]),
        "dual": _scenario(
            planning=[
                _pv("dach_sued", "Dach Süd"),
                _pv("dach_nord", "Dach Nord"),
            ]
        ),
    }
    configs = collect_unique_pv_configs(scenarios)
    assert configs == [
        frozenset({"dach_sued"}),
        frozenset({"dach_sued", "dach_nord"}),
    ]
    labels = {"dach_sued": "Dach Süd", "dach_nord": "Dach Nord"}
    assert joined_pv_config_label(configs[0], labels) == "Dach Süd"
    assert joined_pv_config_label(configs[1], labels) == "Dach Nord + Dach Süd"


def test_with_modeled_pv_from_all_scenarios_attaches_union_and_configs(monkeypatch):
    timestamps = [
        "2024-07-13 12:00:00",
        "2024-07-13 13:00:00",
    ]
    bundle = ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series={},
        baseload=[0.0, 0.0],
        pv=[3.0, 2.0],
    )
    scenarios = {
        "live": _scenario(planning=[_pv("dach_sued", "Dach Süd", kwp=4.0)]),
        "dual": _scenario(
            planning=[
                _pv("dach_sued", "Dach Süd", kwp=4.0),
                _pv("dach_nord", "Dach Nord", kwp=6.0),
            ]
        ),
    }

    class _FakeClimate:
        def __init__(self, scenario_params: dict):
            self._systems = scenario_params.get("_planning_pv_systems") or []

        def pv_kw_by_system_for_slots(self, slots):
            out = {}
            for item in self._systems:
                pv_id = item["id"]
                kwp = float(item["pv_kwp"])
                out[pv_id] = [kwp, kwp * 0.5]
            return out

        def pv_system_labels(self):
            return {item["id"]: item["label"] for item in self._systems}

    monkeypatch.setattr(
        "data.modeled_climate.ModeledClimateContext.from_scenario",
        classmethod(lambda cls, params: _FakeClimate(params)),
    )

    enriched = with_modeled_pv_from_all_scenarios(
        bundle,
        scenarios,
        live_scenario_id="live",
    )
    assert set(enriched.pv_by_system) == {"dach_sued", "dach_nord"}
    assert enriched.pv_system_labels == {
        "dach_sued": "Dach Süd",
        "dach_nord": "Dach Nord",
    }
    assert enriched.pv == [3.0, 2.0]
    assert enriched.pv_by_system["dach_sued"] == [4.0, 2.0]
    assert enriched.pv_by_system["dach_nord"] == [6.0, 3.0]
    assert set(enriched.pv_by_config) == {"dach_sued", "dach_nord+dach_sued"}
    assert enriched.pv_config_labels["dach_sued"] == "Dach Süd"
    assert enriched.pv_config_labels["dach_nord+dach_sued"] == "Dach Nord + Dach Süd"
    assert enriched.pv_by_config["dach_sued"] == [4.0, 2.0]
    assert enriched.pv_by_config["dach_nord+dach_sued"] == [10.0, 5.0]


def _pv_trace_colors(fig) -> list[str]:
    colors: list[str] = []
    for trace in fig.data:
        if getattr(trace, "mode", None) and "lines" in str(trace.mode):
            line = getattr(trace, "line", None)
            color = getattr(line, "color", None) if line is not None else None
            if color and color in PV_YELLOW_PALETTE:
                colors.append(color)
    return colors


def test_stacked_monthly_chart_uses_config_summaries_not_pv_ist():
    timestamps = [
        datetime(2024, 1, 15, 12).strftime("%Y-%m-%d %H:%M:%S"),
        datetime(2024, 2, 15, 12).strftime("%Y-%m-%d %H:%M:%S"),
    ]
    bundle = ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series={"load": [1.0, 1.0]},
        baseload=[0.5, 0.5],
        pv=[2.0, 2.0],
        consumer_labels={"load": "Last"},
        pv_by_system={
            "dach_sued": [4.0, 3.0],
            "dach_nord": [1.0, 2.0],
        },
        pv_system_labels={"dach_sued": "Dach Süd", "dach_nord": "Dach Nord"},
        pv_by_config={
            "dach_sued": [4.0, 3.0],
            "dach_nord+dach_sued": [5.0, 5.0],
        },
        pv_config_labels={
            "dach_sued": "Dach Süd",
            "dach_nord+dach_sued": "Dach Nord + Dach Süd",
        },
    )
    fig = stacked_monthly_chart(bundle, title="Monatsverbrauch: cons_data (kWh)")
    names = [trace.name for trace in fig.data]
    assert "Dach Süd" in names
    assert "Dach Nord + Dach Süd" in names
    assert "Dach Nord" not in names  # monthly: configs only, not per-roof
    assert "PV Ist (cons_data)" not in names
    assert "live" not in names
    assert _pv_trace_colors(fig)
    assert all(color in PV_YELLOW_PALETTE for color in _pv_trace_colors(fig))


def test_week_timeseries_chart_per_pv_plus_multi_summary():
    timestamps = [
        datetime(2024, 7, 15, 12).strftime("%Y-%m-%d %H:%M:%S"),
        datetime(2024, 7, 15, 13).strftime("%Y-%m-%d %H:%M:%S"),
    ]
    bundle = ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series={},
        baseload=[0.0, 0.0],
        pv=[1.0, 1.0],
        pv_by_system={
            "dach_sued": [2.0, 3.0],
            "dach_nord": [1.0, 1.5],
        },
        pv_system_labels={"dach_sued": "Dach Süd", "dach_nord": "Dach Nord"},
        pv_by_config={
            "dach_sued": [2.0, 3.0],
            "dach_nord+dach_sued": [3.0, 4.5],
        },
        pv_config_labels={
            "dach_sued": "Dach Süd",
            "dach_nord+dach_sued": "Dach Nord + Dach Süd",
        },
    )
    fig = week_timeseries_chart(bundle, iso_year=2024, iso_week=29)
    names = [trace.name for trace in fig.data]
    assert names.count("Dach Süd") == 1  # no duplicate single-PV summary
    assert "Dach Nord" in names
    assert "Dach Nord + Dach Süd" in names
    assert "PV Ist (cons_data)" not in names
    assert "PV · Dach Süd" not in names
    assert _pv_trace_colors(fig)
    assert all(color in PV_YELLOW_PALETTE for color in _pv_trace_colors(fig))
