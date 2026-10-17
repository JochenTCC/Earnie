"""Home Assistant REST client → EHAL documents (network API only; Separate Works).

Implementation is split across sibling modules (behavior unchanged):
``ha_adapter_core`` (config, errors, helpers), ``ha_adapter_telemetry`` (reads),
``ha_adapter_write`` (setpoints). Public names stay importable from here.
"""
from __future__ import annotations

from typing import Any

import requests

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
    incomplete_function_messages,
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
    MAPPABLE_DOMAINS,
    WRITE_DOMAINS,
    HaConfig,
    HaHttpError,
    _HaWriteOutcome,
    _NONNEG_TELEMETRY,
    _parse_ha_number,
    _safe_json_or_text,
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


class HaAdapter(HaTelemetryMixin, HaWriteMixin):
    """REST-only Home Assistant ↔ EHAL adapter (no HA libraries)."""

    def __init__(self, cfg: HaConfig) -> None:
        from house_config.ha_ess_force import ha_ess_force_enables_ess_active, normalize_ha_ess_force
        from runtime_store.ehal_setup import HA_TRANSPORT_PUSH, normalize_ha_transport

        transport = normalize_ha_transport(cfg.transport)
        keep_empty = transport == HA_TRANSPORT_PUSH
        entities = canonicalize_ha_entity_keys(dict(cfg.entities), keep_empty=keep_empty)
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
            transport=transport,
            push_read_qids=push_read_qids,
            setpoint_qids=setpoint_qids,
        )
        self._push = transport == HA_TRANSPORT_PUSH
        map_nonempty = not self._push
        # A function is only usable when all its fields are mapped (ehal.functions).
        functions = available_functions(
            entities,
            vendor_ess_active=vendor_ess_active,
            require_nonempty_value=map_nonempty,
        )
        self._supports_ess_write = "ess_limits" in functions
        self._supports_ess_active = "ess_active" in functions
        self._supports_evcs_current = "evcs_current" in functions
        self._supports_ess_source_select = "ess_source_select" in functions
        self._supports_inv_power_limit = "inverter_limit" in functions
        self._vendor_ess_active = vendor_ess_active
        for message in incomplete_function_messages(
            entities, vendor_ess_active=vendor_ess_active
        ):
            logger.warning("HA mapping adapter_id=%s: %s", cfg.adapter_id, message)
        self._incomplete_fields = incomplete_function_fields(
            entities,
            vendor_ess_active=vendor_ess_active,
            require_nonempty_value=map_nonempty,
        )
        self._last_write_error: EhalWriteError | None = None
        self._last_skipped: list[str] = []
        self._warned_skips: set[str] = set()
        self._base = cfg.base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {cfg.token}",
            "Content-Type": "application/json",
        }

    def last_write_error(self) -> EhalWriteError | None:
        return self._last_write_error

    def last_skipped_fields(self) -> list[str]:
        """Setpoint fields of the last write dropped because a function is incomplete."""
        return list(self._last_skipped)

    def _skip(self, field_name: str, outcome: _HaWriteOutcome) -> None:
        # Live trace only for a half-mapped function. Never-configured fields
        # (and unmapped modes) are still not written, but not shown as Übersprungen.
        if field_name in self._incomplete_fields:
            outcome.skipped.append(field_name)
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

    def list_mappable_entities(self) -> list[dict[str, Any]]:
        """Return sensor/number/select/switch/… entities for mapping UI."""
        from runtime_store.shadow.replay import assert_not_shadow_backend

        assert_not_shadow_backend("ha_adapter.list_mappable_entities")
        payload = self._get_json("/api/states")
        if not isinstance(payload, list):
            raise HaHttpError("HA /api/states did not return a list")
        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("entity_id") or "").strip()
            domain = entity_domain(entity_id)
            if domain not in MAPPABLE_DOMAINS:
                continue
            attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            rows.append(
                {
                    "entity_id": entity_id,
                    "domain": domain,
                    "state": item.get("state"),
                    "unit": attrs.get("unit_of_measurement"),
                    "device_class": attrs.get("device_class"),
                    "state_class": attrs.get("state_class"),
                    "friendly_name": attrs.get("friendly_name") or entity_id,
                }
            )
        rows.sort(key=lambda row: str(row["entity_id"]))
        return rows

    def read_state(self, entity_id: str) -> dict[str, Any]:
        self._fence_rest_entity(entity_id)
        return self._get_json(f"/api/states/{entity_id}")

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        from runtime_store.shadow.writes import block_write_if_shadow

        entity = str((data or {}).get("entity_id") or f"{domain}.{service}")
        if block_write_if_shadow(
            backend="ha",
            target=entity,
            value={"domain": domain, "service": service, "data": data},
            source="ha_adapter.call_service",
        ):
            return
        url = f"{self._base}/api/services/{domain}/{service}"
        try:
            response = requests.post(
                url,
                headers=self._headers,
                json=data,
                timeout=self.cfg.timeout_sec,
            )
        except requests.RequestException as exc:
            raise HaHttpError(f"HA service call failed: {exc}") from exc
        if response.status_code not in (200, 201):
            raise HaHttpError(
                f"HA {domain}.{service} → HTTP {response.status_code}",
                status_code=response.status_code,
            )


    def _get_json(self, path: str) -> Any:
        feed_key = f"ha:get:{path}"
        from runtime_store.shadow.replay import replay_ha_get
        from runtime_store.shadow.transport import hub_get, safe_record

        def _live() -> Any:
            url = f"{self._base}{path}"
            try:
                response = requests.get(
                    url, headers=self._headers, timeout=self.cfg.timeout_sec
                )
            except requests.RequestException as exc:
                safe_record(feed_key, ok=False, error=str(exc))
                raise HaHttpError(f"HA GET failed: {exc}") from exc
            if response.status_code != 200:
                safe_record(
                    feed_key,
                    ok=False,
                    status=int(response.status_code),
                    payload=_safe_json_or_text(response),
                    error=f"HTTP {response.status_code}",
                )
                raise HaHttpError(
                    f"HA GET {path} → HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            payload = response.json()
            safe_record(
                feed_key, ok=True, payload=payload, status=int(response.status_code)
            )
            return payload

        return hub_get(replay=lambda: replay_ha_get(feed_key), live=_live)
