"""Stabiler Fingerprint über Backtesting-Szenarien und aufgelöste Settings."""
from __future__ import annotations

import hashlib
import json
from typing import Any

_FINGERPRINT_TARIFF_KEYS = frozenset({
    "_import_tariff_spec",
    "_export_tariff_spec",
})
_SPOT_EXPORT_FEE_KEYS = (
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
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, pricing_digest

    canonical = {
        key: value
        for key, value in settings.items()
        if not str(key).startswith("_") or key in _FINGERPRINT_TARIFF_KEYS
    }
    ref = settings.get(EDIBERT_PRICING_KEY)
    if isinstance(ref, dict):
        # Tariff and grid-fee file content (Edibert P3b, D4): a catalog edit changes prices.
        canonical["_pricing_digest"] = pricing_digest(ref)
    return _json_safe(canonical)


def _spot_export_fee_from_specs(settings: dict) -> dict:
    payload: dict[str, Any] = {}
    export_spec = settings.get("_export_tariff_spec") or {}
    for key in _SPOT_EXPORT_FEE_KEYS:
        if key in export_spec:
            payload[key] = export_spec[key]
    return _json_safe(payload)


def _scenario_needs_spot_export_fees(settings: dict) -> bool:
    export_spec = settings.get("_export_tariff_spec") or {}
    if str(export_spec.get("type", "")).lower() not in {"spot_hourly", "ex_post_spot"}:
        return False
    return any(key in export_spec for key in _SPOT_EXPORT_FEE_KEYS)


def _needs_spot_export_fees(resolved_settings_by_id: dict[str, dict]) -> bool:
    return any(
        _scenario_needs_spot_export_fees(settings)
        for settings in resolved_settings_by_id.values()
    )


def _merged_spot_export_fees(resolved_settings_by_id: dict[str, dict]) -> dict:
    merged: dict[str, Any] = {}
    for settings in resolved_settings_by_id.values():
        if not _scenario_needs_spot_export_fees(settings):
            continue
        block = _spot_export_fee_from_specs(settings)
        for key, value in block.items():
            if key not in merged:
                merged[key] = value
            elif merged[key] != value:
                raise ValueError(
                    f"Widersprüchliche Spot-Export-Preisfelder zwischen Szenarien: '{key}'."
                )
    return merged


def compute_backtesting_fingerprint(
    scenario_ids: list[str],
    resolved_settings_by_id: dict[str, dict],
    period: dict | None = None,
    *,
    awattar_pricing: dict | None = None,
    own_reference_by_id: dict[str, bool] | None = None,
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
    if own_reference_by_id:
        payload["own_reference"] = {
            sid: bool(own_reference_by_id[sid])
            for sid in sorted(own_reference_by_id)
        }
    # Keep payload key name for cache compatibility with older fingerprints.
    if awattar_pricing:
        payload["awattar_pricing"] = awattar_pricing
    if period:
        payload["period"] = {
            key: period[key]
            for key in (
                "start",
                "end",
                "horizon_mode",
                "price_strategy",
                "windows",
                "season_mirror_to_last_month",
            )
            if key in period
        }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint_for_current_config(*, period: dict | None = None) -> str:
    import config
    from data.cons_data_season_mirror import is_season_mirror_enabled

    scenarios = config.get_backtesting_scenarios()
    own_reference_by_id = {
        sid: flag
        for sid, flag in config.get_own_reference_flags().items()
        if flag is not None
    }
    awattar_pricing = (
        _merged_spot_export_fees(scenarios)
        if _needs_spot_export_fees(scenarios)
        else None
    )
    period_payload = dict(period) if period else {}
    period_payload["season_mirror_to_last_month"] = is_season_mirror_enabled()
    return compute_backtesting_fingerprint(
        list(scenarios.keys()),
        scenarios,
        period=period_payload,
        awattar_pricing=awattar_pricing or None,
        own_reference_by_id=own_reference_by_id or None,
    )
