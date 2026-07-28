"""Loxone Miniserver markers → EHAL documents (M1 plant surface)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
from integrations import loxone_client

logger = logging.getLogger(__name__)

SETPOINT_FIELDS = (
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_evcs_max_current",
)


@dataclass(frozen=True)
class LoxoneConfig:
    adapter_id: str
    soc_name: str
    pv_power_name: str
    battery_power_name: str
    grid_power_name: str
    charge_power_name: str = ""
    discharge_power_name: str = ""
    timeout_sec: float = 10.0


class LoxoneAdapterError(RuntimeError):
    """Raised when required Loxone marker reads fail."""


def _utc_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def loxone_battery_kw_to_ehal_w(battery_kw: float) -> float:
    """Loxone Live: +charge → EHAL ess_power: +discharge."""
    return -float(battery_kw) * 1000.0


def ehal_limit_w_to_loxone_kw(limit_w: float) -> float:
    """EHAL ESS limit magnitude (W) → Loxone charge/discharge marker (kW)."""
    return max(0.0, float(limit_w)) / 1000.0


class LoxoneAdapter:
    """Marker HTTP via loxone_client ↔ EHAL (no new EHAL flex/extras fields)."""

    def __init__(self, cfg: LoxoneConfig) -> None:
        self.cfg = cfg
        self._supports_ess_write = bool(cfg.charge_power_name or cfg.discharge_power_name)
        self._supports_evcs_current = False
        self._last_write_error: EhalWriteError | None = None

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

    def read_telemetry(self) -> EhalTelemetry:
        soc = self._require_marker(self.cfg.soc_name, "ess_soc")
        pv_kw = self._require_marker(self.cfg.pv_power_name, "pv_production_active")
        grid_kw = self._require_marker(self.cfg.grid_power_name, "grid_power_active")
        battery_kw = self._require_marker(self.cfg.battery_power_name, "ess_power")

        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
            "grid_power_active": float(grid_kw) * 1000.0,
            "pv_production_active": max(0.0, float(pv_kw)) * 1000.0,
            "ess_soc": float(soc),
            "ess_power": loxone_battery_kw_to_ehal_w(battery_kw),
        }
        return validate_telemetry(doc)

    def write_setpoints(
        self,
        setpoint: EhalSetpoint | dict[str, Any],
        **_kwargs: Any,
    ) -> EhalWriteError | None:
        """Write ESS limits to Loxone markers; EVCS Ampere remains pre-EHAL (flex path)."""
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
            )

        failed: list[str] = []
        messages: list[str] = []
        flip_ess = False

        if "set_ess_charge_power_limit" in doc and self._supports_ess_write:
            ok, msg = self._try_ess_marker_write(
                self.cfg.charge_power_name,
                ehal_limit_w_to_loxone_kw(doc["set_ess_charge_power_limit"]),
            )
            if not ok:
                failed.append("set_ess_charge_power_limit")
                messages.append(msg)
                flip_ess = True

        if "set_ess_discharge_power_limit" in doc and self._supports_ess_write:
            ok, msg = self._try_ess_marker_write(
                self.cfg.discharge_power_name,
                ehal_limit_w_to_loxone_kw(doc["set_ess_discharge_power_limit"]),
            )
            if not ok:
                failed.append("set_ess_discharge_power_limit")
                messages.append(msg)
                flip_ess = True

        # set_evcs_max_current: skipped (supports_evcs_current=false; EV on flex path)

        if not failed:
            self._last_write_error = None
            return None

        return self._record_write_error(
            failed_fields=failed,
            message="; ".join(messages),
            hub_status=None,
            retryable=True,
            flip_ess=flip_ess,
        )

    def _require_marker(self, name: str, field: str) -> float:
        marker = str(name or "").strip()
        if not marker:
            raise LoxoneAdapterError(f"Loxone marker for {field} is not configured")
        value = loxone_client.fetch_loxone_generic_value(marker)
        if value is None:
            raise LoxoneAdapterError(f"Loxone marker read failed for {field} ({marker})")
        return float(value)

    def _try_ess_marker_write(self, marker_name: str, value_kw: float) -> tuple[bool, str]:
        marker = str(marker_name or "").strip()
        if not marker:
            return False, "Loxone ESS write marker name is empty"
        try:
            ok = loxone_client.send_loxone_value(marker, float(value_kw))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "Loxone ESS write failed adapter_id=%s marker=%s: %s",
                self.cfg.adapter_id,
                marker,
                exc,
            )
            return False, str(exc)
        if not ok:
            msg = f"Loxone POST failed for marker {marker}"
            logger.warning(
                "Loxone ESS write failed adapter_id=%s marker=%s",
                self.cfg.adapter_id,
                marker,
            )
            return False, msg
        return True, ""

    def _record_write_error(
        self,
        *,
        failed_fields: list[str],
        message: str,
        hub_status: str | None,
        retryable: bool,
        flip_ess: bool,
    ) -> EhalWriteError:
        if flip_ess:
            self._supports_ess_write = False
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
