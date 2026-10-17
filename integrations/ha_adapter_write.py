"""HA adapter setpoint write paths (REST services and push publish) as a mixin.

Split out of ``integrations.ha_adapter``; ``HaAdapter`` inherits these methods.
"""
from __future__ import annotations

from typing import Any

from ehal import (
    EHAL_SCHEMA_VERSION,
    EhalSetpoint,
    EhalWriteError,
    validate_setpoint,
    validate_write_error,
)
from ehal.field_catalog import SETPOINT_FIELDS
from ehal.validate import EhalValidationError
from integrations.ha_adapter_core import (
    BOOLEAN_INVERT_FIELDS,
    WRITE_DOMAINS,
    HaHttpError,
    _HaWriteOutcome,
    _utc_ts,
    apply_boolean_invert,
    entity_domain,
    logger,
)
from integrations.ha_units import UnitMismatchError, field_quantity, from_ehal


class HaWriteMixin:
    """Setpoint writes, Huawei force services and write-error bookkeeping."""

    def _invalid_setpoint_error(
        self,
        raw: dict[str, Any],
        exc: EhalValidationError,
    ) -> EhalWriteError:
        """Write-Error für ein Setpoint-Dokument, das die Validierung nicht besteht."""
        known = [k for k in SETPOINT_FIELDS if k in raw]
        return self._record_write_error(
            failed_fields=known or ["set_ess_charge_power_limit"],
            message=f"Invalid EHAL setpoint: {exc}",
            hub_status=None,
            retryable=False,
            flip_ess=False,
            flip_evcs=False,
        )

    @staticmethod
    def _record_write_failure(
        outcome: _HaWriteOutcome,
        field_name: str,
        status: str | None,
        msg: str,
        *,
        flip_ess: bool = False,
    ) -> None:
        outcome.failed.append(field_name)
        outcome.messages.append(msg)
        outcome.hub_status = status or outcome.hub_status
        if flip_ess:
            outcome.flip_ess = True

    def _write_ess_vendor_force(
        self, doc: dict[str, Any], outcome: _HaWriteOutcome
    ) -> None:
        """Huawei force charge/discharge via vendor services (stop when no active power)."""
        if not self._vendor_ess_active:
            return
        if "set_ess_active_power" in doc:
            ok, status, msg = self._write_huawei_force(float(doc["set_ess_active_power"]))
        else:
            ok, status, msg = self._stop_huawei_force()
        if not ok:
            self._record_write_failure(
                outcome, "set_ess_active_power", status, msg, flip_ess=True
            )

    def _write_optional_setpoint(
        self,
        doc: dict[str, Any],
        outcome: _HaWriteOutcome,
        field_name: str,
        *,
        supported: bool,
    ) -> None:
        """Write ``field_name`` when present in ``doc``; skip when unsupported."""
        if field_name not in doc:
            return
        if not supported:
            self._skip(field_name, outcome)
            return
        ok, status, msg = self._try_setpoint_write(field_name, float(doc[field_name]))
        if not ok:
            self._record_write_failure(outcome, field_name, status, msg)

    def _write_ess_setpoints(
        self,
        doc: dict[str, Any],
        outcome: _HaWriteOutcome,
    ) -> None:
        """ESS-Leistung/Grenzen sowie den Modus schreiben (Modus flippt kein Capability)."""
        self._write_ess_vendor_force(doc, outcome)

        for field_name in (
            "set_ess_active_power",
            "set_ess_charge_power_limit",
            "set_ess_discharge_power_limit",
        ):
            if field_name not in doc:
                continue
            if field_name == "set_ess_active_power" and self._vendor_ess_active:
                continue  # already handled via huawei_solar services
            supported = (
                self._supports_ess_active
                if field_name == "set_ess_active_power"
                else self._supports_ess_write
            )
            if not supported:
                self._skip(field_name, outcome)
                continue
            ok, status, msg = self._try_setpoint_write(field_name, float(doc[field_name]))
            if not ok:
                self._record_write_failure(
                    outcome, field_name, status, msg, flip_ess=True
                )

        if "set_ess_mode" in doc and not self.cfg.entities.get("set_ess_mode"):
            self._skip("set_ess_mode", outcome)
        elif "set_ess_mode" in doc:
            ok, status, msg = self._try_setpoint_write(
                "set_ess_mode", doc["set_ess_mode"]
            )
            if not ok:
                self._record_write_failure(outcome, "set_ess_mode", status, msg)

        self._write_optional_setpoint(
            doc,
            outcome,
            "set_ess_source_select",
            supported=self._supports_ess_source_select,
        )
        self._write_optional_setpoint(
            doc,
            outcome,
            "set_grid_export_power_limit",
            supported=bool(self.cfg.entities.get("set_grid_export_power_limit")),
        )

    def _huawei_force_payload(self, power_w: float) -> dict[str, Any]:
        force = self.cfg.ha_ess_force or {}
        duration = int(force.get("duration_min") or 20)
        return {
            "device_id": str(force.get("device_id") or ""),
            "power": int(round(abs(float(power_w)))),
            "duration": duration,
        }

    def _write_huawei_force(
        self, active_power_w: float
    ) -> tuple[bool, str | None, str]:
        """Call huawei_solar.forcible_charge or forcible_discharge."""
        force = self.cfg.ha_ess_force or {}
        if str(force.get("driver") or "").strip().lower() != "huawei_solar":
            return False, None, "Unsupported ha_ess_force.driver"
        payload = self._huawei_force_payload(active_power_w)
        if not payload["device_id"]:
            return False, None, "Missing ha_ess_force.device_id"
        service = (
            "forcible_discharge" if active_power_w > 0 else "forcible_charge"
        )
        try:
            self.call_service("huawei_solar", service, payload)
            return True, None, ""
        except HaHttpError as exc:
            logger.warning(
                "HA huawei_solar.%s failed adapter_id=%s: %s",
                service,
                self.cfg.adapter_id,
                exc,
            )
            status = str(exc.status_code) if exc.status_code is not None else None
            return False, status, str(exc)

    def _stop_huawei_force(self) -> tuple[bool, str | None, str]:
        force = self.cfg.ha_ess_force or {}
        if str(force.get("driver") or "").strip().lower() != "huawei_solar":
            return True, None, ""
        device_id = str(force.get("device_id") or "").strip()
        if not device_id:
            return False, None, "Missing ha_ess_force.device_id"
        try:
            self.call_service(
                "huawei_solar",
                "stop_forcible_charge",
                {"device_id": device_id},
            )
            return True, None, ""
        except HaHttpError as exc:
            logger.warning(
                "HA huawei_solar.stop_forcible_charge failed adapter_id=%s: %s",
                self.cfg.adapter_id,
                exc,
            )
            status = str(exc.status_code) if exc.status_code is not None else None
            return False, status, str(exc)
    def _write_evcs_setpoints(
        self,
        doc: dict[str, Any],
        outcome: _HaWriteOutcome,
    ) -> None:
        """EVCS-Strom (Ampere) und Modus schreiben, sofern Entities gemappt sind."""
        for field_name in ("set_evcs_max_current", "set_evcs_mode"):
            if field_name not in doc:
                continue
            if not self._supports_evcs_current or not self.cfg.entities.get(field_name):
                self._skip(field_name, outcome)
                continue
            value = doc[field_name]
            numeric = float(value) if field_name != "set_evcs_mode" else value
            ok, status, msg = self._try_setpoint_write(field_name, numeric)
            if not ok:
                outcome.failed.append(field_name)
                outcome.messages.append(msg)
                outcome.hub_status = status or outcome.hub_status
                outcome.flip_evcs = True

    def write_setpoints(
        self,
        setpoint: EhalSetpoint | dict[str, Any],
        *,
        evcs_voltage_v: float = 230.0,
        evcs_phases: int = 1,
    ) -> EhalWriteError | None:
        """Write setpoints; on failure degrade capabilities and return write_error."""
        del evcs_voltage_v, evcs_phases  # HA current entities are already Amps
        raw = dict(setpoint)
        try:
            doc = validate_setpoint(raw)
        except EhalValidationError as exc:
            return self._invalid_setpoint_error(raw, exc)

        outcome = _HaWriteOutcome()
        self._write_ess_setpoints(doc, outcome)
        self._write_evcs_setpoints(doc, outcome)
        self._last_skipped = list(outcome.skipped)

        if not outcome.failed:
            self._last_write_error = None
            return None

        return self._record_write_error(
            failed_fields=outcome.failed,
            message="; ".join(outcome.messages),
            hub_status=outcome.hub_status,
            retryable=True,
            flip_ess=outcome.flip_ess,
            flip_evcs=outcome.flip_evcs,
        )

    def write_mapped_fields(
        self, fields: dict[str, float | int | str]
    ) -> EhalWriteError | None:
        """Write mapped entities by key (flat or Pattern-B), no envelope validation.

        Used for multi-ESS / powerstation Pattern-B setpoints that are not part of
        the plant-flat setpoint schema document.
        """
        outcome = _HaWriteOutcome()
        for field_name, value in fields.items():
            key = str(field_name or "").strip()
            if not key or key not in self.cfg.entities:
                outcome.failed.append(key or "unknown")
                outcome.messages.append(f"Missing HA write entity for {key}")
                continue
            ok, status, msg = self._try_setpoint_write(key, value)
            if not ok:
                outcome.failed.append(key)
                outcome.messages.append(msg)
                outcome.hub_status = status or outcome.hub_status
                if "ess" in key or key.startswith("set_ess"):
                    outcome.flip_ess = True
        self._last_skipped = list(outcome.skipped)
        if not outcome.failed:
            self._last_write_error = None
            return None
        return self._record_write_error(
            failed_fields=outcome.failed,
            message="; ".join(outcome.messages),
            hub_status=outcome.hub_status,
            retryable=True,
            flip_ess=outcome.flip_ess,
            flip_evcs=outcome.flip_evcs,
        )

    def _publish_setpoint_push(
        self, field_name: str, value: float | str
    ) -> tuple[bool, str | None, str]:
        from integrations.ehal_write import write_field
        from integrations.ha_push_read import resolve_setpoint_qid

        qid = resolve_setpoint_qid(field_name, self.cfg.setpoint_qids)
        if not qid:
            return False, None, f"Missing HA push setpoint binding for {field_name}"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False, None, f"Non-numeric setpoint for {field_name}: {value!r}"
        from ehal.ess_fields import ess_field_kind
        from ehal.inverter_fields import inv_field_kind

        kind = ess_field_kind(field_name) or inv_field_kind(field_name) or field_name
        if kind in BOOLEAN_INVERT_FIELDS or field_name in BOOLEAN_INVERT_FIELDS:
            mode = (
                self.cfg.boolean_invert.get(field_name)
                or self.cfg.boolean_invert.get(kind)
            )
            numeric = apply_boolean_invert(numeric, mode)
        pub = write_field(qid, numeric)
        if not pub.published:
            return False, None, f"EHAL publish rejected for {qid}"
        return True, None, ""

    def _try_setpoint_write(
        self, field_name: str, value: float | str
    ) -> tuple[bool, str | None, str]:
        if self._push:
            return self._publish_setpoint_push(field_name, value)
        entity_id = str(self.cfg.entities.get(field_name) or "").strip()
        if not entity_id:
            return False, None, f"Missing HA write entity for {field_name}"
        domain = entity_domain(entity_id)
        if domain not in WRITE_DOMAINS:
            return False, None, f"Unsupported write domain for {entity_id}"
        try:
            if domain == "switch":
                from ehal.ess_fields import ess_field_kind

                kind = ess_field_kind(field_name) or field_name
                if kind not in BOOLEAN_INVERT_FIELDS and field_name not in BOOLEAN_INVERT_FIELDS:
                    return False, None, f"Unsupported write domain for {entity_id}"
                return self._try_switch_write(field_name, entity_id, value)
            if domain != "select" and field_quantity(field_name) is not None:
                value = self._to_entity_unit(field_name, entity_id, float(value))
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
        except UnitMismatchError as exc:
            logger.warning(
                "HA setpoint unit mismatch adapter_id=%s field=%s: %s",
                self.cfg.adapter_id,
                field_name,
                exc,
            )
            return False, None, f"Unit mismatch for {entity_id}: {exc}"
        except HaHttpError as exc:
            logger.warning(
                "HA setpoint write failed adapter_id=%s field=%s: %s",
                self.cfg.adapter_id,
                field_name,
                exc,
            )
            status = str(exc.status_code) if exc.status_code is not None else None
            return False, status, str(exc)

    def _try_switch_write(
        self,
        field_name: str,
        entity_id: str,
        value: float | str,
    ) -> tuple[bool, str | None, str]:
        """Write boolean/enum EHAL fields onto a HA ``switch`` entity."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False, None, f"Non-numeric switch value for {field_name}: {value!r}"
        from ehal.ess_fields import ess_field_kind
        from ehal.inverter_fields import inv_field_kind

        kind = ess_field_kind(field_name) or inv_field_kind(field_name) or field_name
        mode = None
        if kind in BOOLEAN_INVERT_FIELDS or field_name in BOOLEAN_INVERT_FIELDS:
            mode = (
                self.cfg.boolean_invert.get(field_name)
                or self.cfg.boolean_invert.get(kind)
            )
        ha_on = apply_boolean_invert(numeric, mode) >= 0.5
        service = "turn_on" if ha_on else "turn_off"
        try:
            self.call_service("switch", service, {"entity_id": entity_id})
            return True, None, ""
        except HaHttpError as exc:
            logger.warning(
                "HA switch write failed adapter_id=%s field=%s: %s",
                self.cfg.adapter_id,
                field_name,
                exc,
            )
            status = str(exc.status_code) if exc.status_code is not None else None
            return False, status, str(exc)

    def _to_entity_unit(self, field_name: str, entity_id: str, value: float) -> float:
        """EHAL base unit → target entity unit, read fresh from HA on every write."""
        payload = self.read_state(entity_id)
        attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        converted = from_ehal(field_name, value, attrs.get("unit_of_measurement"))
        if field_name == "set_grid_export_power_limit":
            # Unconstrained export = high magnitude; clamp to the number entity's range.
            entity_max = attrs.get("max")
            if isinstance(entity_max, (int, float)):
                converted = min(converted, float(entity_max))
        return round(converted, 6)

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
