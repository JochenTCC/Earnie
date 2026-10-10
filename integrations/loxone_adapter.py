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
from ehal.field_registry import (
    PLANT_OPTIONAL_READ_FIELDS,
    PLANT_REQUIRED_READ_FIELDS,
    apply_loxone_read,
    loxone_spec,
    require_loxone_write,
)
from ehal.functions import (
    available_functions,
    incomplete_function_fields,
    incomplete_function_messages,
)
from ehal.qualified_ids import qualified_plant_id
from ehal.validate import EhalValidationError
from integrations import loxone_client

logger = logging.getLogger(__name__)

SETPOINT_FIELDS = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
    "set_ess_source_select",
    "set_evcs_max_current",
    "set_evcs_mode",
    "set_grid_export_power_limit",
)

# Numeric encoding of the Loxone Modus Merker (Pattern B).
EVCS_MODE_VALUES: dict[str, float] = {"off": 0.0, "pv": 1.0, "now": 2.0}


@dataclass(frozen=True)
class LoxoneConfig:
    """Write-activation flags (non-empty = wired). Reads use qualified IDs + registry."""

    adapter_id: str
    charge_power_name: str = ""
    discharge_power_name: str = ""
    active_power_name: str = ""
    control_cmd_name: str = ""
    evcs_max_current_name: str = ""
    evcs_mode_name: str = ""
    grid_export_limit_out_name: str = ""
    ess_source_select_name: str = ""
    timeout_sec: float = 10.0


class LoxoneAdapterError(RuntimeError):
    """Raised when required Loxone marker reads fail."""


def _utc_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def loxone_battery_kw_to_ehal_w(battery_kw: float) -> float:
    """Loxone battery Merker (kW, ``+`` = discharge) → EHAL sens_ess_power (W, same sign)."""
    spec = loxone_spec("sens_ess_power")
    if spec is None:
        raise KeyError("no loxone conversion for sens_ess_power")
    converted = apply_loxone_read(battery_kw, spec)
    if converted is None:
        raise ValueError(f"loxone sens_ess_power omitted for raw={battery_kw!r}")
    return converted


class LoxoneAdapter:
    """Push inbox / markers ↔ EHAL (§C wire names); reads are registry-driven."""

    def __init__(self, cfg: LoxoneConfig) -> None:
        self.cfg = cfg
        # A function is only usable when all its fields are mapped (ehal.functions).
        write_map = {
            "set_ess_active_power": cfg.active_power_name,
            "set_ess_charge_power_limit": cfg.charge_power_name,
            "set_ess_discharge_power_limit": cfg.discharge_power_name,
            "set_ess_source_select": cfg.ess_source_select_name,
            "set_evcs_max_current": cfg.evcs_max_current_name,
            "set_grid_export_power_limit": cfg.grid_export_limit_out_name,
        }
        # Write-side still uses non-empty names as wired flags.
        functions = available_functions(write_map)
        self._supports_ess_write = "ess_limits" in functions
        self._supports_ess_active = "ess_active" in functions
        self._supports_evcs_current = "evcs_current" in functions
        self._supports_grid_export_limit = "grid_export_limit" in functions
        self._supports_ess_source_select = "ess_source_select" in functions
        for message in incomplete_function_messages(write_map):
            logger.warning("Loxone mapping adapter_id=%s: %s", cfg.adapter_id, message)
        self._incomplete_fields = incomplete_function_fields(write_map)
        self._last_write_error: EhalWriteError | None = None
        self._last_skipped: list[str] = []
        self._warned_skips: set[str] = set()

    def last_write_error(self) -> EhalWriteError | None:
        return self._last_write_error

    def last_skipped_fields(self) -> list[str]:
        """Setpoint fields of the last write dropped because a function is incomplete."""
        return list(self._last_skipped)

    def _skip(self, field_name: str) -> None:
        # Live trace only for a half-mapped function. Never-configured fields
        # (and unmapped modes) are still not written, but not shown as Übersprungen.
        if field_name in self._incomplete_fields:
            self._last_skipped.append(field_name)
        if field_name not in self._warned_skips:
            self._warned_skips.add(field_name)
            logger.warning(
                "Loxone setpoint %s skipped adapter_id=%s: function not available "
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
        }
        return validate_capabilities(doc)

    def read_telemetry(self) -> EhalTelemetry:
        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
        }
        for field in PLANT_REQUIRED_READ_FIELDS:
            doc[field] = self._require_field(field)
        pv_w = float(doc["sens_pv_production_active"])
        grid_w = float(doc["sens_grid_power_active"])
        ess_w = float(doc["sens_ess_power"])
        doc["sens_power_consumers"] = self._read_or_derive_consumers(pv_w, grid_w, ess_w)
        for field in PLANT_OPTIONAL_READ_FIELDS:
            value = self._read_optional_field(field)
            if value is not None:
                doc[field] = value
        return validate_telemetry(doc)

    def _read_optional_field(self, field: str) -> float | None:
        spec = loxone_spec(field)
        if spec is None:
            return None
        qid = qualified_plant_id(field)
        raw = loxone_client.fetch_loxone_generic_value(qid)
        return apply_loxone_read(raw, spec)

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
        self._last_skipped = []

        flip_ess = self._write_ess_setpoints(doc, failed, messages) or flip_ess
        if "set_ess_mode" in doc and not self.cfg.control_cmd_name:
            self._skip("set_ess_mode")
        elif "set_ess_mode" in doc:
            ok, msg = self._try_marker_write(
                self.cfg.control_cmd_name,
                float(doc["set_ess_mode"]),
                field="set_ess_mode",
            )
            if not ok:
                failed.append("set_ess_mode")
                messages.append(msg)

        if "set_ess_source_select" in doc:
            if not self._supports_ess_source_select:
                self._skip("set_ess_source_select")
            else:
                select_val = 1.0 if float(doc["set_ess_source_select"]) >= 0.5 else 0.0
                ok, msg = self._try_marker_write(
                    self.cfg.ess_source_select_name,
                    select_val,
                    field="set_ess_source_select",
                )
                if not ok:
                    failed.append("set_ess_source_select")
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
        for field_name, supported in (
            ("set_ess_active_power", self._supports_ess_active),
            ("set_ess_charge_power_limit", self._supports_ess_write),
            ("set_ess_discharge_power_limit", self._supports_ess_write),
        ):
            if field_name in doc and not supported:
                self._skip(field_name)
        if "set_ess_active_power" in doc and self._supports_ess_active:
            ok, msg = self._try_marker_write(
                self.cfg.active_power_name,
                require_loxone_write(
                    "set_ess_active_power", doc["set_ess_active_power"]
                ),
                field="set_ess_active_power",
            )
            if not ok:
                failed.append("set_ess_active_power")
                messages.append(msg)
                flip = True
        if "set_ess_charge_power_limit" in doc and self._supports_ess_write:
            ok, msg = self._try_marker_write(
                self.cfg.charge_power_name,
                require_loxone_write(
                    "set_ess_charge_power_limit", doc["set_ess_charge_power_limit"]
                ),
                field="set_ess_charge_power_limit",
            )
            if not ok:
                failed.append("set_ess_charge_power_limit")
                messages.append(msg)
                flip = True
        if "set_ess_discharge_power_limit" in doc and self._supports_ess_write:
            ok, msg = self._try_marker_write(
                self.cfg.discharge_power_name,
                require_loxone_write(
                    "set_ess_discharge_power_limit",
                    doc["set_ess_discharge_power_limit"],
                ),
                field="set_ess_discharge_power_limit",
            )
            if not ok:
                failed.append("set_ess_discharge_power_limit")
                messages.append(msg)
                flip = True
        if "set_grid_export_power_limit" in doc:
            if not self.cfg.grid_export_limit_out_name:
                self._skip("set_grid_export_power_limit")
            else:
                from ehal.qualified_ids import qualified_plant_id

                ok, msg = self._try_marker_write(
                    self.cfg.grid_export_limit_out_name,
                    require_loxone_write(
                        "set_grid_export_power_limit",
                        doc["set_grid_export_power_limit"],
                    ),
                    field=qualified_plant_id("set_grid_export_power_limit"),
                )
                if not ok:
                    failed.append("set_grid_export_power_limit")
                    messages.append(msg)
        return flip

    def _write_evcs_setpoints(
        self, doc: dict[str, Any], failed: list[str], messages: list[str]
    ) -> bool:
        flip = False
        if not self._supports_evcs_current:
            for field_name in ("set_evcs_max_current", "set_evcs_mode"):
                if field_name in doc:
                    self._skip(field_name)
            return flip
        if "set_evcs_max_current" in doc:
            ok, msg = self._try_marker_write(
                self.cfg.evcs_max_current_name,
                float(doc["set_evcs_max_current"]),
                field="set_evcs_max_current",
            )
            if not ok:
                failed.append("set_evcs_max_current")
                messages.append(msg)
                flip = True
        if "set_evcs_mode" in doc and not self.cfg.evcs_mode_name:
            self._skip("set_evcs_mode")
        elif "set_evcs_mode" in doc:
            ok, msg = self._try_evcs_mode_write(str(doc["set_evcs_mode"]))
            if not ok:
                failed.append("set_evcs_mode")
                messages.append(msg)
                flip = True
        return flip

    def _try_evcs_mode_write(self, mode: str) -> tuple[bool, str]:
        """Publish ``set_evcs_mode`` (off=0, pv=1, now=2) via status.json."""
        mode_l = str(mode or "").strip().lower()
        if mode_l not in EVCS_MODE_VALUES:
            return False, f"Unsupported set_evcs_mode: {mode!r}"
        if not self.cfg.evcs_mode_name:
            return False, "No set_evcs_mode marker configured"
        return self._try_marker_write(
            self.cfg.evcs_mode_name,
            EVCS_MODE_VALUES[mode_l],
            field="set_evcs_mode",
        )

    def _read_or_derive_consumers(self, pv_w: float, grid_w: float, ess_w: float) -> float:
        measured = self._read_optional_field("sens_power_consumers")
        if measured is not None:
            return measured
        return max(0.0, pv_w + grid_w + ess_w)

    def _require_field(self, field: str) -> float:
        spec = loxone_spec(field)
        if spec is None:
            raise LoxoneAdapterError(f"Loxone conversion missing for {field}")
        qid = qualified_plant_id(field)
        raw = loxone_client.fetch_loxone_generic_value(qid)
        value = apply_loxone_read(raw, spec)
        if value is None:
            raise LoxoneAdapterError(f"Loxone marker read failed for {field} ({qid})")
        return value

    def _try_marker_write(
        self, marker_name: str, value: float, *, field: str = ""
    ) -> tuple[bool, str]:
        """Publish setpoint via status.json (2.7.q Q5); Merker name is display/activation only."""
        from integrations.loxone_writes import _publish_setpoint_traced

        marker = str(marker_name or "").strip()
        qid = str(field or "").strip()
        if not marker:
            return False, "Loxone write marker name is empty"
        if not qid:
            return False, "EHAL field empty for Loxone publish"
        try:
            rec = _publish_setpoint_traced(qid, float(value), io_name=marker)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "Loxone publish failed adapter_id=%s field=%s: %s",
                self.cfg.adapter_id,
                qid,
                exc,
            )
            return False, str(exc)
        if not rec.success:
            msg = f"Loxone publish failed for {qid}"
            logger.warning(
                "Loxone publish failed adapter_id=%s field=%s",
                self.cfg.adapter_id,
                qid,
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
            self._supports_ess_active = False
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
