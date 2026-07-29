"""OpenEMS Edge REST client → EHAL documents (network API only; Separate Works)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

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


@dataclass(frozen=True)
class OpenemsConfig:
    base_url: str
    username: str
    password: str
    adapter_id: str
    ess_component: str = "ess0"
    evcs_component: str = "evcs0"
    timeout_sec: float = 10.0


class OpenemsHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _utc_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def openems_grid_to_ehal_w(openems_grid_w: float) -> float:
    """OpenEMS: − = sell-to-grid; EHAL: + = import."""
    return -float(openems_grid_w)


def ehal_charge_limit_to_openems(charge_limit_w: float) -> float:
    """EHAL charge magnitude (W) → SetActivePowerGreaterOrEquals value."""
    return -abs(float(charge_limit_w))


def ehal_discharge_limit_to_openems(discharge_limit_w: float) -> float:
    """EHAL discharge magnitude (W) → SetActivePowerLessOrEquals value."""
    return abs(float(discharge_limit_w))


def evcs_amps_to_watts(amps: float, *, voltage_v: float, phases: int) -> float:
    return float(amps) * float(voltage_v) * max(1, int(phases))


class OpenemsAdapter:
    """REST-only OpenEMS ↔ EHAL adapter (no OpenEMS libraries)."""

    def __init__(self, cfg: OpenemsConfig) -> None:
        self.cfg = cfg
        self._supports_ess_write = True
        self._supports_evcs_current = bool(cfg.evcs_component)
        self._last_write_error: EhalWriteError | None = None
        self._auth = HTTPBasicAuth(cfg.username, cfg.password)
        self._base = cfg.base_url.rstrip("/")

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

    def read_channel(self, component: str, channel: str) -> float | None:
        url = self._channel_url(component, channel)
        try:
            response = requests.get(url, auth=self._auth, timeout=self.cfg.timeout_sec)
        except requests.RequestException as exc:
            raise OpenemsHttpError(f"OpenEMS GET failed: {exc}") from exc
        if response.status_code != 200:
            raise OpenemsHttpError(
                f"OpenEMS GET {component}/{channel} → HTTP {response.status_code}",
                status_code=response.status_code,
            )
        payload = response.json()
        value = payload.get("value")
        if value is None:
            return None
        return float(value)

    def write_channel(self, component: str, channel: str, value: float) -> None:
        url = self._channel_url(component, channel)
        try:
            response = requests.post(
                url,
                auth=self._auth,
                json={"value": int(round(value))},
                headers={"Content-Type": "application/json"},
                timeout=self.cfg.timeout_sec,
            )
        except requests.RequestException as exc:
            raise OpenemsHttpError(f"OpenEMS POST failed: {exc}") from exc
        if response.status_code != 200:
            raise OpenemsHttpError(
                f"OpenEMS POST {component}/{channel} → HTTP {response.status_code}",
                status_code=response.status_code,
            )

    def read_telemetry(self) -> EhalTelemetry:
        grid_raw = self.read_channel("_sum", "GridActivePower")
        pv_raw = self.read_channel("_sum", "ProductionActivePower")
        soc = self.read_channel(self.cfg.ess_component, "Soc")
        if soc is None:
            soc = self.read_channel("_sum", "EssSoc")
        if grid_raw is None or pv_raw is None or soc is None:
            raise OpenemsHttpError("OpenEMS telemetry missing required channel value(s)")

        grid_w = openems_grid_to_ehal_w(grid_raw)
        pv_w = max(0.0, float(pv_raw))
        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
            "sens_grid_power_active": grid_w,
            "sens_pv_production_active": pv_w,
            "sens_ess_soc": float(soc),
        }
        ess_power = self._optional_channel(self.cfg.ess_component, "ActivePower")
        if ess_power is None:
            ess_power = self._optional_channel("_sum", "EssActivePower")
        if ess_power is not None:
            doc["sens_ess_power"] = float(ess_power)

        if self.cfg.evcs_component:
            evcs_power = self._optional_channel(self.cfg.evcs_component, "ActivePower")
            if evcs_power is None:
                evcs_power = self._optional_channel(self.cfg.evcs_component, "ChargePower")
            if evcs_power is not None:
                doc["sens_evcs_active_power"] = max(0.0, float(evcs_power))

        ess_w = float(doc.get("sens_ess_power") or 0.0)
        doc["sens_power_consumers"] = max(0.0, pv_w - grid_w - ess_w)
        return validate_telemetry(doc)

    def write_setpoints(
        self,
        setpoint: EhalSetpoint | dict[str, Any],
        *,
        evcs_voltage_v: float = 230.0,
        evcs_phases: int = 1,
    ) -> EhalWriteError | None:
        """Write setpoints; on failure degrade capabilities and return write_error."""
        raw = dict(setpoint)
        try:
            doc = validate_setpoint(raw)
        except EhalValidationError as exc:
            known = [
                k
                for k in (
                    "set_ess_charge_power_limit",
                    "set_ess_discharge_power_limit",
                    "set_ess_mode",
                    "set_evcs_max_current",
                    "set_evcs_mode",
                )
                if k in raw
            ]
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

        if "set_ess_charge_power_limit" in doc and self._supports_ess_write:
            ok, status, msg = self._try_ess_write(
                "SetActivePowerGreaterOrEquals",
                ehal_charge_limit_to_openems(doc["set_ess_charge_power_limit"]),
            )
            if not ok:
                failed.append("set_ess_charge_power_limit")
                messages.append(msg)
                hub_status = status
                flip_ess = True

        if "set_ess_discharge_power_limit" in doc and self._supports_ess_write:
            ok, status, msg = self._try_ess_write(
                "SetActivePowerLessOrEquals",
                ehal_discharge_limit_to_openems(doc["set_ess_discharge_power_limit"]),
            )
            if not ok:
                failed.append("set_ess_discharge_power_limit")
                messages.append(msg)
                hub_status = status or hub_status
                flip_ess = True

        if "set_evcs_max_current" in doc and self._supports_evcs_current:
            watts = evcs_amps_to_watts(
                doc["set_evcs_max_current"],
                voltage_v=evcs_voltage_v,
                phases=evcs_phases,
            )
            ok, status, msg = self._try_evcs_write(watts)
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

    def _channel_url(self, component: str, channel: str) -> str:
        comp = quote(component, safe="")
        chan = quote(channel, safe="")
        return f"{self._base}/rest/channel/{comp}/{chan}"

    def _optional_channel(self, component: str, channel: str) -> float | None:
        try:
            return self.read_channel(component, channel)
        except OpenemsHttpError:
            return None

    def _try_ess_write(self, channel: str, value: float) -> tuple[bool, str | None, str]:
        try:
            self.write_channel(self.cfg.ess_component, channel, value)
            return True, None, ""
        except OpenemsHttpError as exc:
            logger.warning(
                "OpenEMS ESS write failed adapter_id=%s channel=%s: %s",
                self.cfg.adapter_id,
                channel,
                exc,
            )
            status = str(exc.status_code) if exc.status_code is not None else None
            return False, status, str(exc)

    def _try_evcs_write(self, watts: float) -> tuple[bool, str | None, str]:
        try:
            self.write_channel(
                self.cfg.evcs_component, "SetChargePowerLimit", watts
            )
            return True, None, ""
        except OpenemsHttpError as exc:
            logger.warning(
                "OpenEMS EVCS write failed adapter_id=%s: %s",
                self.cfg.adapter_id,
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
