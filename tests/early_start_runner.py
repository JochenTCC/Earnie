"""Subprocess runner for the EarlyStart equivalence test.

Runs one full ``main.main()`` cycle offline on the backtesting fixture config
with a globally frozen clock (``time_machine``) and dumps everything the cycle
planned and wrote as JSON. A fresh interpreter per run keeps process-wide
caches (forecasts, thermal memo, config documents) from leaking between the
runs that are compared.

Usage::

    python -m tests.early_start_runner --runtime DIR --frozen ISO [--tick ISO] --out FILE

``--tick`` set: early-started cycle for that tick (``main.main(tick=…)``); the
hold moves the frozen clock to the tick, as the real wait would.
Inputs are deterministic and depend only on absolute time, never on "now":
telemetry is fixed, network is blocked (fixture config is offline).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_BT = ROOT / "tests" / "fixtures" / "backtesting"


def _private_config(runtime: Path) -> Path:
    """Per-run copy of the fixture config with cons_data inside the runtime.

    The fixture's ``path_cons_data`` points at the committed CSV, which the
    cycle appends to — parallel runs would race on it and dirty the fixture.
    The copy lives inside the runtime, so seed copies carry it along.
    """
    config_dir = runtime / "_config"
    config_path = config_dir / "config.json"
    if not config_path.is_file():
        config_dir.mkdir(parents=True, exist_ok=True)
        doc = json.loads((_BT / "config.json").read_text(encoding="utf-8"))
        doc["scenario_explorer_conf"]["path_cons_data"] = "runtime/cons_data.csv"
        config_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        shutil.copyfile(_BT / "cons_data.csv", runtime / "cons_data.csv")
    return config_path


def _configure_env(runtime: Path) -> None:
    os.environ["EARNIE_CONFIG_PATH"] = str(_private_config(runtime))
    os.environ["EARNIE_OFFLINE"] = "1"
    os.environ["EARNIE_CBC_STRICT"] = "1"
    os.environ["EARNIE_TARIFFS_PATH"] = str(_BT / "tariffs.json")
    os.environ["EARNIE_HOUSE_PROFILES_PATH"] = str(_BT / "house_profiles.json")
    os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"] = str(_BT / "backtesting_scenarios.json")
    os.environ["EARNIE_COMPONENTS_PATH"] = str(_BT / "components.json")
    os.environ["EARNIE_RUNTIME_PATH"] = str(runtime)
    os.environ.pop("EARNIE_CYCLE_TIMING", None)
    os.environ.pop("EARNIE_CYCLE_PROFILE", None)
    # Fake Open-Meteo payloads must not land in the repo's data/cache/open_meteo
    # (cwd = repo root): scripts.run_regression reads the same cache keys.
    from data import open_meteo_solar_archive as archive

    archive.OPEN_METEO_CACHE_DIR = runtime / "_open_meteo_cache"


def _block_network() -> None:
    def refuse(*_a, **_k):
        raise OSError("early_start_runner: network blocked")

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.getaddrinfo = refuse  # type: ignore[assignment]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_jsonable(v) for v in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return repr(value)


def run(
    runtime: Path,
    frozen: datetime,
    tick: datetime | None,
    prefetch_at: datetime | None = None,
) -> dict:
    _configure_env(runtime)
    _block_network()
    import time_machine

    capture: dict[str, Any] = {"writes": [], "milp_calls": []}
    with time_machine.travel(frozen, tick=False) as traveller:
        import main as main_module

        _install_stubs(main_module, capture, traveller)
        if prefetch_at is not None:
            # Daemon order: prefetch in the idle time, then the cycle — same process,
            # so the in-process caches carry over as in production.
            from data.live_prefetch import prefetch_live_inputs

            traveller.move_to(prefetch_at)
            result = prefetch_live_inputs(
                (tick or frozen).replace(tzinfo=None), frozen.replace(tzinfo=None)
            )
            capture["prefetch"] = {"events": list(result.events), "errors": list(result.errors)}
            traveller.move_to(frozen)
        if os.environ.get("EARLY_START_TRACE_CLOCK") == "1":
            _trace_clock_reads(capture)
        main_module.main(
            run_trigger=main_module.TRIGGER_QUARTER_HOUR,
            tick=tick.replace(tzinfo=None) if tick is not None else None,
            lead_sec=(tick.timestamp() - frozen.timestamp()) if tick is not None else 0.0,
        )
    return _jsonable(capture)


# Day-ahead results appear at this local time (D+1 prices); away from any tick
# within the lead, so A and B runs see the same published data.
_PUBLISH_HOUR, _PUBLISH_MINUTE = 12, 52


def _price_cent(slot: datetime) -> float:
    """Deterministic QH price from absolute time only."""
    import math

    hour = slot.hour + slot.minute / 60.0
    return round(12.0 + 9.0 * math.sin((hour - 7.0) / 24.0 * 2 * math.pi) + (slot.day % 5) * 0.7, 4)


def _fake_energy_charts(start_ts, end_ts, bzn="AT"):
    """Like Energy-Charts: QH series up to the last published day as of the real clock."""
    from datetime import timedelta

    import pandas as pd

    now = datetime.now()
    last_day = now.date() + timedelta(days=1)
    if (now.hour, now.minute) < (_PUBLISH_HOUR, _PUBLISH_MINUTE):
        last_day = now.date()
    end = min(
        pd.Timestamp(end_ts).to_pydatetime(),
        datetime.combine(last_day, datetime.min.time()).replace(hour=23, minute=45),
    )
    index = pd.date_range(pd.Timestamp(start_ts), end, freq="15min")
    return pd.DataFrame(
        {"price_cent_kwh": [_price_cent(ts.to_pydatetime()) for ts in index]}, index=index
    )


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _weather_value(var: str, moment: datetime, lat: float) -> float:
    import math

    hour = moment.hour
    day = moment.timetuple().tm_yday
    if "temperature" in var:
        return round(8.0 + 6.0 * math.sin((hour - 9) / 24 * 2 * math.pi) + (day % 3), 2)
    if "radiation" in var or "irradiance" in var:
        return round(max(0.0, 600.0 * math.sin((hour - 6) / 12 * math.pi)) if 6 <= hour <= 18 else 0.0, 1)
    if "wind" in var:
        return round(12.0 + 5.0 * math.cos(hour / 24 * 2 * math.pi) + lat % 2, 2)
    return round(10.0 + hour * 0.1, 2)


def _open_meteo_payload(params: dict, lat: float) -> dict:
    """Like Open-Meteo /v1/forecast: hourly from real today 00:00 for forecast_days."""
    from datetime import timedelta

    days = int(params.get("forecast_days") or 1)
    start = datetime.combine(datetime.now().date(), datetime.min.time())
    times = [start + timedelta(hours=h) for h in range(days * 24)]
    hourly: dict[str, list] = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}
    for var in str(params.get("hourly") or "").split(","):
        if var:
            hourly[var] = [_weather_value(var, t, lat) for t in times]
    return {"latitude": lat, "hourly": hourly}


def _forecast_solar_payload() -> dict:
    """Hourly watts from real yesterday to real today + 3 days.

    The real API covers only today and tomorrow of the *request* date, so a
    cycle at 23:58 lacks the day after the tick (an availability difference,
    not an anchoring one). The wider window keeps this test about anchoring.
    """
    import math
    from datetime import timedelta

    start = datetime.combine(datetime.now().date() - timedelta(days=1), datetime.min.time())
    watts = {}
    for h in range(5 * 24):
        moment = start + timedelta(hours=h)
        if 7 <= moment.hour <= 18:
            watts[moment.strftime("%Y-%m-%d %H:%M:%S")] = round(
                2400 * math.sin((moment.hour - 6.5) / 12.5 * math.pi)
            )
    return {"result": {"watts": watts}}


def _fake_requests_get(url, params=None, **_kwargs):
    import requests

    params = dict(params or {})
    if "api.open-meteo.com" in url:
        lats = [float(v) for v in str(params.get("latitude", "0")).split(",")]
        payloads = [_open_meteo_payload(params, lat) for lat in lats]
        return _FakeResponse(payloads if len(payloads) > 1 else payloads[0])
    if "api.forecast.solar" in url:
        return _FakeResponse(_forecast_solar_payload())
    raise requests.ConnectionError(f"early_start_runner: no fake for {url}")


def _install_stubs(main_module, capture: dict, traveller) -> None:
    import time

    import requests

    import data.live_market_prices as lmp

    requests.get = _fake_requests_get
    time.sleep = lambda _s: None
    lmp.fetch_energy_charts_prices = _fake_energy_charts
    ehal = main_module.ehal_live
    ehal.read_ess_soc = lambda: 50.0
    ehal.read_ess_soc_by_id = lambda: {"test_battery": 50.0}
    ehal.read_live_power_kw = lambda: {"pv": 2.4, "house": 1.6, "battery": -0.5, "grid": -0.3}
    ehal.fetch_flexible_consumers_live_kw = lambda *a, **k: {}
    main_module.config.is_loxone_silent_mode = lambda: False

    def recorder(name):
        def _write(*args, **kwargs):
            capture["writes"].append({"fn": name, "args": args, "kwargs": kwargs})
            if name == "write_inv_ac_limits_from_plan":
                return None, []
            return []
        return _write

    for name in (
        "write_huawei_modbus_states",
        "write_flexible_consumer_states",
        "write_inv_ac_limits_from_plan",
        "write_ess_setpoints_from_control",
        "write_evcs_max_current_from_consumers",
    ):
        setattr(ehal, name, recorder(name))
    import optimizer.powerstation_live as psl

    psl.write_cycle_powerstation_setpoints = recorder("write_cycle_powerstation_setpoints")

    real_window = main_module.profile_manager.compute_live_planning_window

    def window(*a, **k):
        result = real_window(*a, **k)
        capture["planning_window"] = main_module.serialize_planning_window(result)
        return result

    main_module.profile_manager.compute_live_planning_window = window

    real_milp = main_module.optimizer.milp_optimizer

    def milp(matrix, current_hour, current_soc, **kwargs):
        result = real_milp(matrix, current_hour, current_soc, **kwargs)
        capture["milp_calls"].append(
            {
                "matrix": matrix,
                "current_hour": current_hour,
                "current_soc": current_soc,
                "kwargs": kwargs,
                "result": result[:6],
            }
        )
        return result

    main_module.optimizer.milp_optimizer = milp

    real_targets = main_module.consumer_targets.resolve_consumer_daily_targets

    def targets(*a, **k):
        result = real_targets(*a, **k)
        capture.setdefault("daily_targets_calls", []).append(result)
        return result

    main_module.consumer_targets.resolve_consumer_daily_targets = targets

    import optimizer as optimizer_pkg

    real_load_state = optimizer_pkg._load_consumer_state

    def load_state(*a, **k):
        result = real_load_state(*a, **k)
        capture.setdefault("consumer_state_loads", []).append(result)
        return result

    optimizer_pkg._load_consumer_state = load_state

    def hold(tick, **_k):
        sys.setprofile(None)  # end of the planning phase for _trace_clock_reads
        capture["hold_from"] = datetime.now().isoformat()
        traveller.move_to(tick.astimezone() if tick.tzinfo is None else tick)

    main_module._hold_until_tick = hold

    real_append = main_module.cycle_duration_stats.append_record

    def append_record(record, **kwargs):
        capture["cycle_events"] = list(record.get("events") or [])
        return real_append(record, **kwargs)

    main_module.cycle_duration_stats.append_record = append_record

    def save_run_state(payload):
        capture["run_state"] = payload

    main_module.run_state.save_run_state = save_run_state
    main_module.optimization_history.append_production_run = (
        lambda payload: capture.__setitem__("history", payload)
    )


_CLOCK_FUNCS = frozenset({"now", "today", "utcnow", "time", "localtime", "time_ns"})


def _trace_clock_reads(capture: dict) -> None:
    """Diagnostics: record project call sites reading the wall clock directly.

    Active until the hold (planning phase); ``planning_clock`` itself is skipped.
    Set ``EARLY_START_TRACE_CLOCK=1``; result in ``capture["clock_reads"]``.
    """
    seen: dict[str, int] = {}
    capture["clock_reads"] = seen
    root = str(ROOT)

    def profiler(frame, event, arg):
        if event != "c_call" or getattr(arg, "__name__", "") not in _CLOCK_FUNCS:
            return
        filename = frame.f_code.co_filename
        if not filename.startswith(root) or "planning_clock" in filename or "tests" in filename:
            return
        key = f"{Path(filename).relative_to(ROOT)}:{frame.f_lineno} {arg.__name__}"
        seen[key] = seen.get(key, 0) + 1

    sys.setprofile(profiler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--frozen", required=True)
    parser.add_argument("--tick")
    parser.add_argument("--prefetch-at")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    frozen = datetime.fromisoformat(args.frozen)
    tick = datetime.fromisoformat(args.tick) if args.tick else None
    prefetch_at = datetime.fromisoformat(args.prefetch_at) if args.prefetch_at else None
    capture = run(args.runtime, frozen, tick, prefetch_at)
    args.out.write_text(json.dumps(capture, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
