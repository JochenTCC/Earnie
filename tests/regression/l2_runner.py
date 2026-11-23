"""L2 backtest window via simulation engine + offline fixtures."""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import pandas as pd

from tests.fixtures.backtesting_fixtures import (
    install_fixture_flex_consumers,
    FIXTURES_ROOT,
    build_synthetic_prices_df,
    fixture_path,
    load_fixture_cache,
)
from tests.regression.climate_fixture import frozen_climate_fixture
from tests.regression.fingerprint import l2_input_fingerprint
from tests.regression.l2_case_inputs import (
    case_inputs,
    consumer_metric_ids,
    scenario_id,
    write_case_config,
)
from tests.regression.loader import RegressionCase
from tests.regression.pv_shape import assert_pv_day_shape

_ENV_KEYS = (
    "EARNIE_CONFIG_PATH",
    "EARNIE_BACKTESTING_SCENARIOS_PATH",
    "EARNIE_TARIFFS_PATH",
    "EARNIE_HOUSE_PROFILES_PATH",
    "EARNIE_COMPONENTS_PATH",
    "EARNIE_OFFLINE",
)


@contextmanager
def activate_backtesting_fixture_env(
    overrides: Mapping[str, Path] | None = None,
) -> Iterator[Any]:
    """Bind config to ``tests/fixtures/backtesting/`` without pytest monkeypatch.

    ``overrides``: env var → patched copy of a fixture file (``l2_case_inputs``).
    """
    import config as config_module

    unknown = sorted(set(overrides or {}) - set(_ENV_KEYS))
    if unknown:
        raise ValueError(f"fixture env overrides not allowed: {unknown}")
    install_fixture_flex_consumers()
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    os.environ["EARNIE_CONFIG_PATH"] = str(fixture_path("config.json"))
    os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"] = str(
        fixture_path("backtesting_scenarios.json")
    )
    os.environ["EARNIE_TARIFFS_PATH"] = str(fixture_path("tariffs.json"))
    os.environ["EARNIE_HOUSE_PROFILES_PATH"] = str(fixture_path("house_profiles.json"))
    os.environ["EARNIE_OFFLINE"] = "1"
    for key, path in (overrides or {}).items():
        os.environ[key] = str(path)
    try:
        # Climate (PV irradiance, temperature) comes from the committed fixture only.
        with frozen_climate_fixture():
            config_module.reinit_config()
            yield config_module
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config_module.reinit_config()


_CASE_GRID_AREA = "user_regression_case"


def _edibert_case_pricing(
    out: dict,
    tariff: dict | None,
    fee: float | None,
    work_dir: Path,
    capacity_charges: list[dict] | None = None,
) -> None:
    """The case's inline tariff and flat grid fee as tariff-track files plus a pricing
    reference, so Edibert prices exactly these inputs."""
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, pricing_reference
    from house_config.edibert_tariffs import EDIBERT_TARIFF_FORMAT, flat_user_grid_area

    ref = dict(out.get(EDIBERT_PRICING_KEY) or {})
    tariffs_path = work_dir / "tariffs.json"
    grid_path = work_dir / "grid_fees.json"
    import_id = ref.get("import_tariff_id")
    if tariff is not None:
        entry = {"supplier_id": "regression", "land": "AT", **tariff}
        tariffs_path.write_text(
            json.dumps({"tariff_format": EDIBERT_TARIFF_FORMAT, "import_tariffs": [entry],
                        "export_tariffs": []}),
            encoding="utf-8",
        )
        import_id = entry["id"]
    grid_path.write_text(
        json.dumps({"tariff_format": EDIBERT_TARIFF_FORMAT, "rule_sets": {}, "areas": []}),
        encoding="utf-8",
    )
    profile: dict[str, Any] = {"land": "AT"}
    if fee is not None:
        area = flat_user_grid_area(_CASE_GRID_AREA, float(fee), label="Regression", land="AT")
        if capacity_charges:
            area["capacity_charges"] = [dict(charge) for charge in capacity_charges]
        (work_dir / "user_grid_fees.json").write_text(
            json.dumps({"tariff_format": EDIBERT_TARIFF_FORMAT, "rule_sets": {}, "areas": [area]}),
            encoding="utf-8",
        )
        profile["netznutzung"] = {"area_id": _CASE_GRID_AREA, "quarter_hour_meter": True}
    if tariff is not None:
        # The case tariff lives in its own file; the export tariff stays the scenario's.
        export_id = ref.get("export_tariff_id")
        if export_id:
            source = json.loads(Path(ref["tariffs_path"]).read_text(encoding="utf-8"))
            doc = json.loads(tariffs_path.read_text(encoding="utf-8"))
            doc["export_tariffs"] = [
                t for t in source.get("export_tariffs", []) if t.get("id") == export_id
            ]
            tariffs_path.write_text(json.dumps(doc), encoding="utf-8")
    out[EDIBERT_PRICING_KEY] = pricing_reference(
        tariffs_path=str(tariffs_path) if tariff is not None else ref["tariffs_path"],
        grid_fees_path=str(grid_path),
        import_tariff_id=import_id,
        export_tariff_id=ref.get("export_tariff_id"),
        timezone_name=str(out.get("timezone_name") or "Europe/Vienna"),
        profile=profile,
        user_fixed=ref.get("user_fixed") or None,
    )


def _apply_case_pricing(scenario: dict, case_inputs: dict[str, Any], work_dir: Path) -> dict:
    """Optional pricing overrides: ``import_tariff`` (spec), ``grid_fee_base_cent_kwh`` and
    ``grid_capacity_charges`` (capacity charges of that flat grid area).

    Without them the fixture scenario keeps its own tariffs.
    """
    tariff = case_inputs.get("import_tariff")
    fee = case_inputs.get("grid_fee_base_cent_kwh")
    if tariff is None and fee is None:
        return scenario
    out = dict(scenario)
    if tariff is not None:
        out["_import_tariff_spec"] = dict(tariff)
    _edibert_case_pricing(out, tariff, fee, work_dir, case_inputs.get("grid_capacity_charges"))
    return out


def case_scenario_params(sid: str) -> dict:
    """Resolved params of one fixture scenario (after the case's file overrides)."""
    import config

    scenarios = config.get_backtesting_scenarios()
    if sid not in scenarios:
        raise KeyError(f"scenario {sid!r} missing in the fixture backtesting_scenarios.json")
    return dict(scenarios[sid])


def run_l2(case: RegressionCase) -> dict[str, Any]:
    window = case.meta["window"]
    start = pd.Timestamp(str(window["start"]))
    end = pd.Timestamp(str(window["end"]))
    if end < start:
        raise ValueError(f"case {case.id}: window.end before start")

    inputs = case_inputs(case.meta, case.id)
    consumers = consumer_metric_ids(case.meta, case.id)
    priced = consumer_metric_ids(case.meta, case.id, "consumer_price_ct")
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        overrides = write_case_config(
            inputs, work_dir, fixtures_root=FIXTURES_ROOT, case_id=case.id
        )
        with activate_backtesting_fixture_env(overrides):
            df, plausibility, scenario = _simulate(inputs, start, end, work_dir)
            assert_pv_day_shape(df, case_id=case.id)
            metrics = metrics_from_l2_frame(
                df, plausibility, scenario=scenario, consumers=consumers,
                priced_consumers=priced,
            )
    metrics["inputs"] = l2_input_fingerprint(
        fixtures_root=FIXTURES_ROOT,
        case_inputs=inputs,
        result_df=df,
    )
    return metrics


def _simulate(
    inputs: dict[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
    work_dir: Path,
) -> tuple[pd.DataFrame, Any, dict]:
    from simulation.engine import run_simulation

    cache = load_fixture_cache()
    sid = scenario_id(inputs)
    scenario = _apply_case_pricing(case_scenario_params(sid), inputs, work_dir)
    prices = build_synthetic_prices_df(
        start - pd.Timedelta(days=1),
        end + pd.Timedelta(days=1),
    )
    # Inject a negative-price hour when requested (synthetic stress).
    if inputs.get("force_negative_price"):
        prices = prices.copy()
        mid = prices.index[len(prices.index) // 2]
        prices.loc[mid, "price_cent_kwh"] = -5.0
    df, plausibility, _cbc = run_simulation(
        start,
        end,
        scenario,
        prices,
        cache=cache,
        scenario_id=sid,
        initial_soc=float(inputs.get("initial_soc", 50.0)),
    )
    return df, plausibility, scenario


_DT_H = 0.25


def metrics_from_l2_frame(
    df: pd.DataFrame,
    plausibility: Any,
    *,
    scenario: dict | None = None,
    consumers: tuple[str, ...] = (),
    priced_consumers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Compared L2 metrics. The compare reads only the keys a golden lists, so a metric added
    here leaves older goldens untouched.

    ``scenario``: the resolved params of the run; adds ``capacity_charge_eur`` (0 without a
    capacity charge in the grid area). ``consumers``: IDs whose energy becomes
    ``consumer_kwh_<id>``; ``priced_consumers``: IDs whose energy-weighted import price
    (``k_act``, ct/kWh) becomes ``consumer_price_ct_<id>``. A missing result column raises.
    """
    import_kwh = float(df["import_kwh"].fillna(0).sum()) if "import_kwh" in df else 0.0
    export_kwh = float(df["export_kwh"].fillna(0).sum()) if "export_kwh" in df else 0.0
    cost = float(df["sim_cost"].fillna(0).sum()) if "sim_cost" in df else 0.0
    batt = (
        float(df["batt_action_kw"].abs().fillna(0).sum()) * _DT_H
        if "batt_action_kw" in df
        else 0.0
    )
    failed = list(getattr(plausibility, "failed", []) or [])
    metrics: dict[str, Any] = {
        "status_optimal": 1 if not failed else 0,
        "n_slots": int(len(df)),
        "cost_euro": cost,
        "import_kwh": import_kwh,
        "export_kwh": export_kwh,
        "battery_throughput_kwh": batt,
        "plausibility_failures": float(len(failed)),
        "plan_hash": None,
        "peak_import_kw": _peak_import_kw(df),
    }
    if scenario is not None:
        from simulation.capacity_charge import capacity_for_result

        metrics["capacity_charge_eur"] = float(capacity_for_result(df, scenario).gross_eur)
    for consumer_id in consumers:
        column = f"{consumer_id}_kw"
        if column not in df.columns:
            raise ValueError(
                f"extra_metrics.consumer_kwh: no column {column!r} in the L2 result "
                f"(consumer {consumer_id!r} not planned?)"
            )
        metrics[f"consumer_kwh_{consumer_id}"] = float(df[column].fillna(0).sum()) * _DT_H
    for consumer_id in priced_consumers:
        metrics[f"consumer_price_ct_{consumer_id}"] = _consumer_price_ct(df, consumer_id)
    if "import_cap_limit" in df.columns:
        metrics["import_cap_slots_over_without_cause"] = _slots_over_without_cause(df)
    return metrics


def _consumer_price_ct(df: pd.DataFrame, consumer_id: str) -> float:
    """Import price (``k_act``, ct/kWh) weighted by the consumer's energy per slot.

    Shows when a consumer runs: a store that can hold its heat longer moves the run into cheaper
    slots. A consumer without energy in the window raises (no price to weigh).
    """
    column = f"{consumer_id}_kw"
    for needed in (column, "k_act"):
        if needed not in df.columns:
            raise ValueError(
                f"extra_metrics.consumer_price_ct: no column {needed!r} in the L2 result"
            )
    energy = df[column].fillna(0).clip(lower=0.0)
    total = float(energy.sum())
    if total <= 0.0:
        raise ValueError(
            f"extra_metrics.consumer_price_ct: consumer {consumer_id!r} has no energy in the window"
        )
    return float((energy * pd.to_numeric(df["k_act"], errors="raise")).sum()) / total


# Booked import above the slot's limit by more than this counts as over (kW; rounding of rows).
_CAP_OVER_TOLERANCE_KW = 0.02


def _slots_over_without_cause(df: pd.DataFrame) -> float:
    """Slots whose booked import exceeds the import limit although the plan names no cause.

    The plan sets ``import_cap_cause`` wherever it goes over the limit; a booked slot over it
    without a cause means the control did not follow the plan.
    """
    limit = pd.to_numeric(df["import_cap_limit"], errors="raise")
    import_kw = df["import_kwh"].fillna(0) / _DT_H
    cause = df["import_cap_cause"] if "import_cap_cause" in df.columns else pd.Series(None, index=df.index)
    over = limit.notna() & (import_kw > limit + _CAP_OVER_TOLERANCE_KW) & cause.isna()
    return float(over.sum())


def _peak_import_kw(df: pd.DataFrame) -> float:
    """Highest 15-minute grid import of the window, in kW."""
    if "import_kwh" not in df or df.empty:
        return 0.0
    return float(df["import_kwh"].fillna(0).clip(lower=0).max()) / _DT_H


def fixtures_root() -> Any:
    return FIXTURES_ROOT
