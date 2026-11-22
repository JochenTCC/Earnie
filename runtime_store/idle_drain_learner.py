"""Learn the idle drain of the house battery from its SoC reading (Reserve P4).

The plant reports the SoC in steps (whole percent on the maintainer's plant). The moment the
reading drops by one step, the true SoC crosses the same level every time, so two drops in a
row with no charge or discharge in between give the drain directly:

    drain_kw = capacity_kwh * step / 100 / hours between the two drops

The battery power sensor cannot measure this drain (it showed less than half of it), so only
the battery power decides whether the battery was idle: every sample between the two drops
must stay within ``hold_power_kw``. A rise of the reading, a gap in the samples or a change of
the battery starts over.

The learned value is a suggestion only (maintainer, 2026-11-22): the plan and the simulation
use the configured ``idle_drain_kw`` of the battery (``optimizer.battery.idle_drain_kw``). The
state file keeps the last episodes; ``learned_idle_drain`` gives their median.

Only one house battery is learned: with several, the reading is that of the first battery or
of the plant and the capacity is ambiguous, so the learner records the reason and stops.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
from datetime import datetime
from typing import Any

from runtime_store.file_metadata import stamp_payload, strip_metadata
from runtime_store.persist_paths_base import idle_drain_learner_state_file

logger = logging.getLogger(__name__)

_SCHEMA = 1
# Samples further apart than this leave the battery unobserved: the episode starts over.
MAX_SAMPLE_GAP_SEC = 10 * 60
# A drop of one step in less time is no idle drain (on 15 kWh: > 600 W).
MIN_EPISODE_HOURS = 0.25
MAX_EPISODE_HOURS = 48.0
# Largest drop of the reading that counts as one step (a 0.1 % reading drops by 0.1).
MAX_STEP_PCT = 1.0
MAX_EPISODES = 20
MIN_EPISODES_FOR_VALUE = 3
_EPS = 1e-9


def _state_path() -> str:
    return idle_drain_learner_state_file()


def _empty_state() -> dict[str, Any]:
    return {"battery_id": None, "capacity_kwh": None, "anchor": None, "last": None, "episodes": []}


def load_state(state_path: str | None = None) -> dict[str, Any]:
    path = state_path or _state_path()
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return _empty_state()
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("idle_drain_learner: state unreadable (%s) - starting over.", exc)
        return _empty_state()
    if not isinstance(raw, dict):
        logger.warning("idle_drain_learner: state is not an object - starting over.")
        return _empty_state()
    return {**_empty_state(), **strip_metadata(raw)}


def _save_state(path: str, state: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(stamp_payload(state, schema_version=_SCHEMA), handle, indent=2)
    os.replace(tmp, path)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def observe_sample(
    sample: dict[str, Any],
    *,
    battery_id: str,
    capacity_kwh: float,
    hold_power_kw: float,
    state_path: str | None = None,
) -> dict[str, Any] | None:
    """Feed one sampler sample (``ts``, ``soc_percent``, ``battery_kw``); returns a new episode.

    ``hold_power_kw``: largest battery power (either sign) that still counts as idle.
    A sample without SoC is ignored.
    """
    if capacity_kwh <= 0.0:
        raise ValueError(f"idle_drain_learner: capacity_kwh must be > 0 (got {capacity_kwh!r}).")
    if hold_power_kw < 0.0:
        raise ValueError(f"idle_drain_learner: hold_power_kw must be >= 0 (got {hold_power_kw!r}).")
    ts = _parse_ts(sample.get("ts"))
    if ts is None:
        raise ValueError(f"idle_drain_learner: sample without valid ts: {sample!r}")
    if sample.get("soc_percent") is None:
        return None
    soc = float(sample["soc_percent"])
    battery_kw = float(sample.get("battery_kw") or 0.0)
    path = state_path or _state_path()
    state = load_state(path)
    if state.get("battery_id") != battery_id or state.get("capacity_kwh") != float(capacity_kwh):
        # Another battery (or capacity): its episodes say nothing about this one.
        state = _empty_state()
        state["battery_id"] = battery_id
        state["capacity_kwh"] = float(capacity_kwh)
    state.pop("unsupported", None)
    idle = abs(battery_kw) <= hold_power_kw + _EPS
    anchor = state.get("anchor")
    last = state.get("last")
    last_ts = _parse_ts(last.get("ts")) if isinstance(last, dict) else None
    if last_ts is not None and ts == last_ts:
        return None  # the same sample again
    if last_ts is None or ts <= last_ts or (ts - last_ts).total_seconds() > MAX_SAMPLE_GAP_SEC:
        anchor = None
        last = None
    if anchor is not None and not idle:
        anchor["idle"] = False
    episode = None
    if last is not None and abs(soc - float(last["soc"])) > _EPS:
        step = float(last["soc"]) - soc
        if (
            anchor is not None
            and anchor.get("down")
            and anchor.get("idle")
            and abs(float(anchor["soc"]) - float(last["soc"])) <= _EPS
            and 0.0 < step <= MAX_STEP_PCT + _EPS
        ):
            episode = _episode(anchor, ts, soc, step, capacity_kwh)
        anchor = {"ts": ts.isoformat(timespec="seconds"), "soc": soc, "down": step > 0.0, "idle": idle}
    state["anchor"] = anchor
    state["last"] = {"ts": ts.isoformat(timespec="seconds"), "soc": soc}
    if episode is not None:
        state["episodes"] = (list(state.get("episodes") or []) + [episode])[-MAX_EPISODES:]
        logger.info(
            "idle_drain_learner: battery %s drained %.2f %% in %.2f h = %.3f kW (median of %d: %s)",
            battery_id,
            episode["step_pct"],
            episode["hours"],
            episode["drain_kw"],
            len(state["episodes"]),
            _median_text(state["episodes"]),
        )
    _save_state(path, state)
    return episode


def _episode(
    anchor: dict[str, Any], ts: datetime, soc: float, step: float, capacity_kwh: float
) -> dict[str, Any] | None:
    start = _parse_ts(anchor["ts"])
    if start is None:
        return None
    hours = (ts - start).total_seconds() / 3600.0
    if not MIN_EPISODE_HOURS <= hours <= MAX_EPISODE_HOURS:
        return None
    return {
        "start": anchor["ts"],
        "end": ts.isoformat(timespec="seconds"),
        "soc_from": float(anchor["soc"]),
        "soc_to": soc,
        "step_pct": round(step, 3),
        "hours": round(hours, 4),
        "drain_kw": round(capacity_kwh * step / 100.0 / hours, 4),
    }


def _median_text(episodes: list[dict[str, Any]]) -> str:
    if len(episodes) < MIN_EPISODES_FOR_VALUE:
        return f"needs {MIN_EPISODES_FOR_VALUE}"
    return f"{statistics.median(float(e['drain_kw']) for e in episodes):.3f} kW"


def mark_unsupported(reason: str, *, state_path: str | None = None) -> None:
    """Record why nothing is learned (e.g. several house batteries); drops the open episode."""
    path = state_path or _state_path()
    state = load_state(path)
    if state.get("unsupported") == reason and state.get("anchor") is None:
        return
    state["unsupported"] = reason
    state["anchor"] = None
    state["last"] = None
    _save_state(path, state)
    logger.info("idle_drain_learner: not learning - %s", reason)


def learned_idle_drain(state_path: str | None = None) -> dict[str, Any]:
    """Learned idle drain: median of the stored episodes.

    ``drain_kw`` is ``None`` until ``MIN_EPISODES_FOR_VALUE`` episodes exist; ``episodes`` is
    their count, ``unsupported`` the reason when the learner does not run.
    """
    state = load_state(state_path)
    episodes = list(state.get("episodes") or [])
    drain = (
        round(statistics.median(float(e["drain_kw"]) for e in episodes), 4)
        if len(episodes) >= MIN_EPISODES_FOR_VALUE
        else None
    )
    return {
        "battery_id": state.get("battery_id"),
        "capacity_kwh": state.get("capacity_kwh"),
        "drain_kw": drain,
        "episodes": len(episodes),
        "last_episode_end": episodes[-1]["end"] if episodes else None,
        "unsupported": state.get("unsupported"),
    }


def observe_latest_live_sample(
    battery_params_list: list[dict],
    *,
    state_path: str | None = None,
    sampler_state_path: str | None = None,
) -> dict[str, Any] | None:
    """Daemon hook: feed the sampler's newest sample for the single house battery."""
    from optimizer.sim_horizon_chart_soc import house_balance_batteries
    from runtime_store import power_interval_sampler

    house = [
        b
        for b in house_balance_batteries(list(battery_params_list))
        if float(b.get("battery_capacity_kwh") or 0.0) > 0.0
    ]
    if len(house) != 1:
        mark_unsupported(
            f"{len(house)} house batteries with capacity (learner needs exactly one)",
            state_path=state_path,
        )
        return None
    battery = house[0]
    sample = power_interval_sampler.latest_sample(state_path=sampler_state_path)
    if sample is None:
        return None
    max_power = max(
        float(battery.get("max_charge_power_kw") or 0.0),
        float(battery.get("max_discharge_power_kw") or 0.0),
        float(battery.get("max_power_kw") or 0.0),
    )
    if "threshold_power" not in battery:
        raise ValueError(
            f"idle_drain_learner: battery '{battery.get('id')}' without threshold_power."
        )
    return observe_sample(
        sample,
        battery_id=str(battery.get("id") or "primary"),
        capacity_kwh=float(battery["battery_capacity_kwh"]),
        hold_power_kw=float(battery["threshold_power"]) * max_power,
        state_path=state_path,
    )
