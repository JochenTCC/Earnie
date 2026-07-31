"""Loxone Miniserver markers → EHAL documents (schema_version 3 / §C Design C1)."""
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
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
    "set_evcs_max_current",
    "set_evcs_mode",
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
    active_power_name: str = ""
    control_cmd_name: str = ""
    consumers_power_name: str = ""
    evcs_max_current_name: str = ""
    pv_follow_name: str = ""
    charge_immediate_name: str = ""
    timeout_sec: float = 10.0


class LoxoneAdapterError(RuntimeError):
    """Raised when required Loxone marker reads fail."""


def _utc_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def loxone_battery_kw_to_ehal_w(battery_kw: float) -> float:
    """Loxone Live: +charge → EHAL sens_ess_power: +discharge."""
    return -float(battery_kw) * 1000.0


def ehal_limit_w_to_loxone_kw(limit_w: float) -> float:
    """EHAL ESS limit magnitude (W) → Loxone charge/discharge marker (kW)."""
    return max(0.0, float(limit_w)) / 1000.0


def ehal_active_power_w_to_loxone_kw(active_w: float) -> float:
    """EHAL signed active power (W, +discharge) → Loxone Merker (kW, same sign)."""
    return float(active_w) / 1000.0


class LoxoneAdapter:
    """Marker HTTP via loxone_client ↔ EHAL (§C wire names)."""

    def __init__(self, cfg: LoxoneConfig) -> None:
        self.cfg = cfg
        self._supports_ess_write = bool(
            cfg.charge_power_name
            or cfg.discharge_power_name
            or cfg.active_power_name
        )
        self._supports_evcs_current = bool(cfg.evcs_max_current_name)
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
        soc = self._require_marker(self.cfg.soc_name, "sens_ess_soc")
        pv_kw = self._require_marker(self.cfg.pv_power_name, "sens_pv_production_active")
        grid_kw = self._require_marker(self.cfg.grid_power_name, "sens_grid_power_active")
        battery_kw = self._require_marker(
            self.cfg.battery_power_name, "sens_ess_power"
        )

        grid_w = float(grid_kw) * 1000.0
        pv_w = max(0.0, float(pv_kw)) * 1000.0
        ess_w = loxone_battery_kw_to_ehal_w(battery_kw)
        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
            "sens_grid_power_active": grid_w,
            "sens_pv_production_active": pv_w,
            "sens_ess_soc": float(soc),
            "sens_ess_power": ess_w,
            "sens_power_consumers": self._read_or_derive_consumers(pv_w, grid_w, ess_w),
        }
        return validate_telemetry(doc)

    def write_setpoints(
        self,
        setpoint: EhalSetpoint | dict[str, Any],
        **_kwargs: Any,
    ) -> EhalWriteError | None:
        """Write ESS/EV setpoints to Loxone markers (transitional EV bindings)."""
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
        flip_ess = False
        flip_evcs = False

        flip_ess = self._write_ess_setpoints(doc, failed, messages) or flip_ess
        if "set_ess_mode" in doc:
            ok, msg = self._try_marker_write(
                self.cfg.control_cmd_name, float(doc["set_ess_mode"])
            )
            if not ok:
                failed.append("set_ess_mode")
                messages.append(msg)

        flip_evcs = self._write_evcs_setpoints(doc, failed, messages) or flip_evcs

        if not failed:
            self._last_write_error = None
            return None

        return self._record_write_error(
            failed_fields=failed,
            message="; ".join(messages),
            hub_status=None,
            retryable=True,
            flip_ess=flip_ess,
            flip_evcs=flip_evcs,
        )

    def _write_ess_setpoints(
        self, doc: dict[str, Any], failed: list[str], messages: list[str]
    ) -> bool:
        flip = False
        if "set_ess_active_power" in doc and self.cfg.active_power_name:
            ok, msg = self._try_marker_write(
                self.cfg.active_power_name,
                ehal_active_power_w_to_loxone_kw(doc["set_ess_active_power"]),
            )
            if not ok:
                failed.append("set_ess_active_power")
                messages.append(msg)
                flip = True
        if "set_ess_charge_power_limit" in doc and self._supports_ess_write:
            ok, msg = self._try_marker_write(
                self.cfg.charge_power_name,
                ehal_limit_w_to_loxone_kw(doc["set_ess_charge_power_limit"]),
            )
            if not ok:
                failed.append("set_ess_charge_power_limit")
                messages.append(msg)
                flip = True
        if "set_ess_discharge_power_limit" in doc and self._supports_ess_write:
            ok, msg = self._try_marker_write(
                self.cfg.discharge_power_name,
                ehal_limit_w_to_loxone_kw(doc["set_ess_discharge_power_limit"]),
            )
            if not ok:
                failed.append("set_ess_discharge_power_limit")
                messages.append(msg)
                flip = True
        return flip

    def _write_evcs_setpoints(
        self, doc: dict[str, Any], failed: list[str], messages: list[str]
    ) -> bool:
        flip = False
        if not self._supports_evcs_current:
            return flip
        if "set_evcs_max_current" in doc:
            ok, msg = self._try_marker_write(
                self.cfg.evcs_max_current_name,
                float(doc["set_evcs_max_current"]),
            )
            if not ok:
                failed.append("set_evcs_max_current")
                messages.append(msg)
                flip = True
        if "set_evcs_mode" in doc:
            ok, msg = self._try_evcs_mode_write(str(doc["set_evcs_mode"]))
            if not ok:
                failed.append("set_evcs_mode")
                messages.append(msg)
                flip = True
        return flip

    def _try_evcs_mode_write(self, mode: str) -> tuple[bool, str]:
        """Map set_evcs_mode pv|now → pv_follow / charge_immediate until 2.4.k."""
        mode_l = str(mode or "").strip().lower()
        if mode_l not in ("pv", "now"):
            return False, f"Unsupported set_evcs_mode: {mode!r}"
        pv_val = 1.0 if mode_l == "pv" else 0.0
        now_val = 1.0 if mode_l == "now" else 0.0
        wrote = False
        if self.cfg.pv_follow_name:
            ok, msg = self._try_marker_write(self.cfg.pv_follow_name, pv_val)
            if not ok:
                return False, msg
            wrote = True
        if self.cfg.charge_immediate_name:
            ok, msg = self._try_marker_write(self.cfg.charge_immediate_name, now_val)
            if not ok:
                return False, msg
            wrote = True
        if not wrote:
            return False, "No pv_follow/charge_immediate markers for set_evcs_mode"
        return True, ""

    def _read_or_derive_consumers(self, pv_w: float, grid_w: float, ess_w: float) -> float:
        marker = str(self.cfg.consumers_power_name or "").strip()
        if marker:
            value = loxone_client.fetch_loxone_generic_value(marker)
            if value is not None:
                return max(0.0, float(value) * 1000.0)
        return max(0.0, pv_w - grid_w - ess_w)

    def _require_marker(self, name: str, field: str) -> float:
        marker = str(name or "").strip()
        if not marker:
            raise LoxoneAdapterError(f"Loxone marker for {field} is not configured")
        value = loxone_client.fetch_loxone_generic_value(marker)
        if value is None:
            raise LoxoneAdapterError(f"Loxone marker read failed for {field} ({marker})")
        return float(value)

    def _try_marker_write(self, marker_name: str, value: float) -> tuple[bool, str]:
        marker = str(marker_name or "").strip()
        if not marker:
            return False, "Loxone write marker name is empty"
        try:
            ok = loxone_client.send_loxone_value(marker, float(value))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "Loxone write failed adapter_id=%s marker=%s: %s",
                self.cfg.adapter_id,
                marker,
                exc,
            )
            return False, str(exc)
        if not ok:
            msg = f"Loxone POST failed for marker {marker}"
            logger.warning(
                "Loxone write failed adapter_id=%s marker=%s",
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
