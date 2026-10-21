"""Home Assistant ↔ EHAL adapter (push transport only; Binding P5e).

Implementation is split across sibling modules:
``ha_adapter_core`` (config, errors, helpers), ``ha_adapter_telemetry`` (reads),
``ha_adapter_write`` (setpoints via status.json). Public names stay importable here.
"""
from __future__ import annotations

from typing import Any

from ehal import (
    EHAL_SCHEMA_VERSION,
    EhalCapabilities,
    EhalWriteError,
    validate_capabilities,
)
from ehal.models import canonicalize_ha_entity_keys
from ehal.functions import (
    available_functions,
    incomplete_function_fields,
)
from ehal.field_catalog import (  # noqa: F401  (re-exported for callers / tests)
    SETPOINT_FIELDS,
    TELEMETRY_BINARY_OPTIONAL,
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_OPTIONAL_HA as TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
)
from integrations.ha_adapter_core import (  # noqa: F401  (re-exported)
    BOOLEAN_INVERT_FIELDS,
    HaConfig,
    HaHttpError,
    _HaWriteOutcome,
    _NONNEG_TELEMETRY,
    _parse_ha_number,
    _utc_ts,
    apply_boolean_invert,
    apply_sign,
    entity_domain,
    logger,
    parse_ha_field_value,
)
from integrations.ha_adapter_telemetry import HaTelemetryMixin
from integrations.ha_adapter_write import HaWriteMixin
from integrations.ha_units import UnitMismatchError, field_quantity, from_ehal, to_ehal  # noqa: F401
from runtime_store.ehal_setup import HA_TRANSPORT_PUSH


class HaAdapter(HaTelemetryMixin, HaWriteMixin):
    """Home Assistant ↔ EHAL adapter (push inbox + status.json; no REST pull)."""

    def __init__(self, cfg: HaConfig) -> None:
        from house_config.ha_ess_force import (
            ha_ess_force_enables_ess_active,
            normalize_ha_ess_force,
        )

        # Binding P5e: always push; ignore leftover transport on HaConfig.
        entities = canonicalize_ha_entity_keys(dict(cfg.entities), keep_empty=True)
        sign = canonicalize_ha_entity_keys(dict(cfg.sign))
        boolean_invert = canonicalize_ha_entity_keys(dict(cfg.boolean_invert))
        force = normalize_ha_ess_force(cfg.ha_ess_force) if cfg.ha_ess_force else None
        vendor_ess_active = ha_ess_force_enables_ess_active(force)
        push_read_qids = dict(cfg.push_read_qids)
        setpoint_qids = dict(cfg.setpoint_qids)
        self.cfg = HaConfig(
            base_url=cfg.base_url,
            token=cfg.token,
            adapter_id=cfg.adapter_id,
            entities=entities,
            sign=sign,
            boolean_invert=boolean_invert,
            timeout_sec=cfg.timeout_sec,
            ha_ess_force=force,
            transport=HA_TRANSPORT_PUSH,
            push_read_qids=push_read_qids,
            setpoint_qids=setpoint_qids,
        )
        self._push = True
        # Activation = key presence (empty entity_id values).
        functions = available_functions(
            entities,
            vendor_ess_active=vendor_ess_active,
            require_nonempty_value=False,
        )
        self._supports_ess_write = "ess_limits" in functions
        self._supports_ess_active = "ess_active" in functions
        self._supports_evcs_current = "evcs_current" in functions
        self._supports_ess_source_select = "ess_source_select" in functions
        self._supports_inv_power_limit = "inverter_limit" in functions
        self._vendor_ess_active = vendor_ess_active
        self._incomplete_fields = incomplete_function_fields(
            entities,
            vendor_ess_active=vendor_ess_active,
            require_nonempty_value=False,
        )
        self._last_write_error: EhalWriteError | None = None
        self._last_skipped: list[str] = []
        self._last_unconfigured: list[str] = []
        self._warned_skips: set[str] = set()

    def last_write_error(self) -> EhalWriteError | None:
        return self._last_write_error

    def last_skipped_fields(self) -> list[str]:
        """Setpoint fields of the last write dropped because a function is incomplete."""
        return list(self._last_skipped)

    def last_unconfigured_fields(self) -> list[str]:
        """Setpoint fields of the last write that are not activated at all (nothing written)."""
        return list(self._last_unconfigured)

    def _skip(self, field_name: str, outcome: _HaWriteOutcome) -> None:
        if field_name in self._incomplete_fields:
            outcome.skipped.append(field_name)
        else:
            outcome.unconfigured.append(field_name)
        if field_name not in self._warned_skips:
            self._warned_skips.add(field_name)
            logger.warning(
                "HA setpoint %s skipped adapter_id=%s: function not available "
                "(mapping incomplete or not configured)",
                field_name,
                self.cfg.adapter_id,
            )

    def capabilities(self) -> EhalCapabilities:
        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
            "supports_ess_write": self._supports_ess_write,
            "supports_evcs_current": self._supports_evcs_current,
            "supports_ess_source_select": self._supports_ess_source_select,
            "supports_inv_power_limit": self._supports_inv_power_limit,
        }
        return validate_capabilities(doc)
