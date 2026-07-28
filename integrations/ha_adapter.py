"""Home Assistant REST client → EHAL documents (network API only; Separate Works)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from ehal import (
    EHAL_SCHEMA_VERSION,
    EhalCapabilities,
    EhalSetpoint,
    EhalTelemetry,
    EhalWriteError,
    validate_capabilities,
    validate_setpoint,
    validate_telemetry,
    validate_write_error,
)
from ehal.validate import EhalValidationError

logger = logging.getLogger(__name__)

TELEMETRY_REQUIRED = ("grid_power_active", "pv_production_active", "ess_soc")
TELEMETRY_OPTIONAL = ("ess_power", "evcs_active_power")
SETPOINT_FIELDS = (
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_evcs_max_current",
)
MAPPABLE_DOMAINS = frozenset({"sensor", "number", "select", "input_number"})
WRITE_DOMAINS = frozenset({"number", "select", "input_number"})


@dataclass(frozen=True)
class HaConfig:
    base_url: str
    token: str
    adapter_id: str
    entities: dict[str, str] = field(default_factory=dict)
    sign: dict[str, str] = field(default_factory=dict)
    timeout_sec: float = 10.0


class HaHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _utc_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def apply_sign(value: float, mode: str | None) -> float:
    """Apply configured sign mode: ehal (noop) or negate."""
    if str(mode or "ehal").strip().lower() == "negate":
        return -float(value)
    return float(value)


def parse_ha_numeric_state(state: str, *, unit: str | None) -> float:
    """Parse HA state string; convert kW→W when unit indicates kilowatts."""
    text = str(state).strip().replace(",", ".")
    if text.lower() in ("", "unavailable", "unknown", "none"):
        raise ValueError(f"HA state is not numeric: {state!r}")
    value = float(text)
    unit_l = str(unit or "").strip().lower()
    if unit_l in ("kw", "kilowatt", "kilowatts"):
        return value * 1000.0
    return value


def entity_domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0].strip().lower()


class HaAdapter:
    """REST-only Home Assistant ↔ EHAL adapter (no HA libraries)."""

    def __init__(self, cfg: HaConfig) -> None:
        self.cfg = cfg
        self._supports_ess_write = bool(
            cfg.entities.get("set_ess_charge_power_limit")
            or cfg.entities.get("set_ess_discharge_power_limit")
        )
        self._supports_evcs_current = bool(cfg.entities.get("set_evcs_max_current"))
        self._last_write_error: EhalWriteError | None = None
        self._base = cfg.base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {cfg.token}",
            "Content-Type": "application/json",
        }

    def last_write_error(self) -> EhalWriteError | None:
        return self._last_write_error

    def capabilities(self) -> EhalCapabilities:
        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
            "supports_ess_write": self._supports_ess_write,
            "supports_evcs_current": self._supports_evcs_current,
        }
        return validate_capabilities(doc)

    def list_mappable_entities(self) -> list[dict[str, Any]]:
        """Return sensor/number/select/input_number entities for mapping UI."""
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
                    "friendly_name": attrs.get("friendly_name") or entity_id,
                }
            )
        rows.sort(key=lambda row: str(row["entity_id"]))
        return rows

    def read_state(self, entity_id: str) -> dict[str, Any]:
        return self._get_json(f"/api/states/{entity_id}")

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
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

    def read_telemetry(self) -> EhalTelemetry:
        missing = [name for name in TELEMETRY_REQUIRED if not self.cfg.entities.get(name)]
        if missing:
            raise HaHttpError(
                "HA telemetry mapping incomplete: " + ", ".join(missing)
            )

        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
        }
        for field_name in TELEMETRY_REQUIRED:
            doc[field_name] = self._read_mapped_numeric(field_name)
        for field_name in TELEMETRY_OPTIONAL:
            if not self.cfg.entities.get(field_name):
                continue
            try:
                value = self._read_mapped_numeric(field_name)
            except (HaHttpError, ValueError):
                continue
            if field_name in ("pv_production_active", "evcs_active_power"):
                value = max(0.0, value)
            doc[field_name] = value

        if "pv_production_active" in doc:
            doc["pv_production_active"] = max(0.0, float(doc["pv_production_active"]))
        return validate_telemetry(doc)

    def write_setpoints(
        self,
        setpoint: EhalSetpoint | dict[str, Any],
        *,
        evcs_voltage_v: float = 230.0,
        evcs_phases: int = 1,
    ) -> EhalWriteError | None:
        """Write setpoints; on failure degrade capabilities and return write_error."""
        del evcs_voltage_v, evcs_phases  # HA max_current entity is already Amps
        raw = dict(setpoint)
        try:
            doc = validate_setpoint(raw)
        except EhalValidationError as exc:
            known = [k for k in SETPOINT_FIELDS if k in raw]
            return self._record_write_error(
                failed_fields=known or ["set_ess_charge_power_limit"],
                message=f"Invalid EHAL setpoint: {exc}",
                hub_status=None,
                retryable=False,
                flip_ess=False,
                flip_evcs=False,
            )

        failed: list[str] = []
        messages: list[str] = []
        hub_status: str | None = None
        flip_ess = False
        flip_evcs = False

        for field_name in ("set_ess_charge_power_limit", "set_ess_discharge_power_limit"):
            if field_name not in doc or not self._supports_ess_write:
                continue
            ok, status, msg = self._try_setpoint_write(field_name, float(doc[field_name]))
            if not ok:
                failed.append(field_name)
                messages.append(msg)
                hub_status = status or hub_status
                flip_ess = True

        if "set_evcs_max_current" in doc and self._supports_evcs_current:
            ok, status, msg = self._try_setpoint_write(
                "set_evcs_max_current", float(doc["set_evcs_max_current"])
            )
            if not ok:
                failed.append("set_evcs_max_current")
                messages.append(msg)
                hub_status = status or hub_status
                flip_evcs = True

        if not failed:
            self._last_write_error = None
            return None

        return self._record_write_error(
            failed_fields=failed,
            message="; ".join(messages),
            hub_status=hub_status,
            retryable=True,
            flip_ess=flip_ess,
            flip_evcs=flip_evcs,
        )

    def _get_json(self, path: str) -> Any:
        url = f"{self._base}{path}"
        try:
            response = requests.get(
                url, headers=self._headers, timeout=self.cfg.timeout_sec
            )
        except requests.RequestException as exc:
            raise HaHttpError(f"HA GET failed: {exc}") from exc
        if response.status_code != 200:
            raise HaHttpError(
                f"HA GET {path} → HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response.json()

    def _read_mapped_numeric(self, field_name: str) -> float:
        entity_id = self.cfg.entities[field_name]
        payload = self.read_state(entity_id)
        attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        unit = attrs.get("unit_of_measurement")
        raw = parse_ha_numeric_state(str(payload.get("state")), unit=unit)
        if field_name == "ess_soc":
            return float(raw)
        return apply_sign(raw, self.cfg.sign.get(field_name))

    def _try_setpoint_write(
        self, field_name: str, value: float
    ) -> tuple[bool, str | None, str]:
        entity_id = str(self.cfg.entities.get(field_name) or "").strip()
        if not entity_id:
            return False, None, f"Missing HA write entity for {field_name}"
        domain = entity_domain(entity_id)
        if domain not in WRITE_DOMAINS:
            return False, None, f"Unsupported write domain for {entity_id}"
        try:
            if domain == "select":
                self.call_service(
                    "select",
                    "select_option",
                    {"entity_id": entity_id, "option": str(value)},
                )
            elif domain == "input_number":
                self.call_service(
                    "input_number",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                )
            else:
                self.call_service(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                )
            return True, None, ""
        except HaHttpError as exc:
            logger.warning(
                "HA setpoint write failed adapter_id=%s field=%s: %s",
                self.cfg.adapter_id,
                field_name,
                exc,
            )
            status = str(exc.status_code) if exc.status_code is not None else None
            return False, status, str(exc)

    def _record_write_error(
        self,
        *,
        failed_fields: list[str],
        message: str,
        hub_status: str | None,
        retryable: bool,
        flip_ess: bool,
        flip_evcs: bool,
    ) -> EhalWriteError:
        if flip_ess:
            self._supports_ess_write = False
        if flip_evcs:
            self._supports_evcs_current = False
        payload: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
            "failed_fields": failed_fields,
            "message": message,
            "retryable": retryable,
        }
        if hub_status is not None:
            payload["hub_status"] = hub_status
        error = validate_write_error(payload)
        self._last_write_error = error
        return error
