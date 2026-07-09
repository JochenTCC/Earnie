"""Stabiler Fingerprint über Backtesting-Szenarien und aufgelöste Settings."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _canonical_scenario_settings(settings: dict) -> dict:
    return _json_safe(
        {key: value for key, value in settings.items() if not str(key).startswith("_")}
    )


def compute_backtesting_fingerprint(
    scenario_ids: list[str],
    resolved_settings_by_id: dict[str, dict],
    period: dict | None = None,
) -> str:
    """Hash über Szenario-IDs und kanonische aufgelöste Parameter."""
    payload: dict[str, Any] = {
        "scenario_ids": sorted(scenario_ids),
        "scenarios": {
            sid: _canonical_scenario_settings(resolved_settings_by_id[sid])
            for sid in sorted(scenario_ids)
            if sid in resolved_settings_by_id
        },
    }
    if period:
        payload["period"] = {
            key: period[key]
            for key in ("start", "end", "horizon_mode", "price_strategy", "windows")
            if key in period
        }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint_for_current_config(*, period: dict | None = None) -> str:
    import config

    scenarios = config.get_backtesting_scenarios()
    return compute_backtesting_fingerprint(list(scenarios.keys()), scenarios, period=period)
