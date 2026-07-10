"""Stabiler Fingerprint über Backtesting-Szenarien und aufgelöste Settings."""
from __future__ import annotations

import hashlib
import json
from typing import Any

_FINGERPRINT_TARIFF_KEYS = frozenset({
    "_import_tariff_spec",
    "_export_tariff_spec",
    "_monthly_fixed_tariffs",
})
_AWATTAR_PRICING_KEYS = (
    "fix_aufschlag_cent",
    "netzverlust_faktor",
    "mwst_austria_faktor",
    "feed_in_fee_factor",
    "feed_in_fix_cent",
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _canonical_scenario_settings(settings: dict) -> dict:
    return _json_safe({
        key: value
        for key, value in settings.items()
        if not str(key).startswith("_") or key in _FINGERPRINT_TARIFF_KEYS
    })


def _awattar_pricing_block(raw_config: dict) -> dict:
    block = raw_config.get("awattar")
    if not isinstance(block, dict):
        return {}
    return _json_safe({
        key: block[key]
        for key in _AWATTAR_PRICING_KEYS
        if key in block
    })


def _scenario_needs_awattar_pricing(settings: dict) -> bool:
    import_spec = settings.get("_import_tariff_spec") or {}
    export_spec = settings.get("_export_tariff_spec") or {}
    import_type = str(
        import_spec.get("type", settings.get("import_tariff_type", ""))
    ).lower()
    export_type = str(export_spec.get("type", "")).lower()
    return import_type == "awattar" or export_type == "dynamic_epex"


def _needs_awattar_pricing(resolved_settings_by_id: dict[str, dict]) -> bool:
    return any(
        _scenario_needs_awattar_pricing(settings)
        for settings in resolved_settings_by_id.values()
    )


def compute_backtesting_fingerprint(
    scenario_ids: list[str],
    resolved_settings_by_id: dict[str, dict],
    period: dict | None = None,
    *,
    awattar_pricing: dict | None = None,
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
    if awattar_pricing:
        payload["awattar_pricing"] = awattar_pricing
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
    awattar_pricing = (
        _awattar_pricing_block(config.CONFIG._raw_config)
        if _needs_awattar_pricing(scenarios)
        else None
    )
    return compute_backtesting_fingerprint(
        list(scenarios.keys()),
        scenarios,
        period=period,
        awattar_pricing=awattar_pricing,
    )
