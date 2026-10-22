"""HA adapter setpoint write paths (push publish only) as a mixin.

Split out of ``integrations.ha_adapter``; ``HaAdapter`` inherits these methods.
Binding P5e: REST service writes and ``ha_ess_force`` Huawei REST are removed;
``plant.ha_ess_force`` is owned by the HA YAML package automations.
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
    _HaWriteOutcome,
    _utc_ts,
    apply_boolean_invert,
    logger,
)


class HaWriteMixin:
    """Setpoint writes via status.json publish (push-only)."""

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
        """ESS power/limits and mode via status.json (YAML may own ha_ess_force)."""
        for field_name in (
            "set_ess_active_power",
            "set_ess_charge_power_limit",
            "set_ess_discharge_power_limit",
        ):
            if field_name not in doc:
                continue
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
            supported="set_grid_export_power_limit" in self.cfg.entities,
        )

    def _write_evcs_setpoints(
        self,
        doc: dict[str, Any],
        outcome: _HaWriteOutcome,
    ) -> None:
        """EVCS current and mode via status.json when activated."""
        for field_name in ("set_evcs_max_current", "set_evcs_mode"):
            if field_name not in doc:
                continue
            if not self._supports_evcs_current or field_name not in self.cfg.entities:
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
        del evcs_voltage_v, evcs_phases
        raw = dict(setpoint)
        try:
            doc = validate_setpoint(raw)
        except EhalValidationError as exc:
            return self._invalid_setpoint_error(raw, exc)

        outcome = _HaWriteOutcome()
        self._write_ess_setpoints(doc, outcome)
        self._write_evcs_setpoints(doc, outcome)
        self._last_skipped = list(outcome.skipped)
        self._last_unconfigured = list(outcome.unconfigured)

        if not outcome.failed:
            self._last_write_error = None
            self._warn_if_hub_reports_unapplied()
            return None

        return self._record_write_error(
            failed_fields=outcome.failed,
            message="; ".join(outcome.messages),
            hub_status=outcome.hub_status,
            retryable=True,
            flip_ess=outcome.flip_ess,
            flip_evcs=outcome.flip_evcs,
        )

    def _warn_if_hub_reports_unapplied(self) -> None:
        """Setpoints are only *published* here; HA reports back when it could not apply them."""
        from runtime_store.ehal_push_inbox import hub_write_failure_age_s

        age = hub_write_failure_age_s()
        if age is not None:
            logger.warning(
                "Home Assistant meldet nicht angewendete Sollwerte (hub_write_failed vor "
                "%.0f s): Ziel-Entity bzw. HA-Log prüfen.",
                age,
            )

    def write_mapped_fields(
        self, fields: dict[str, float | int | str]
    ) -> EhalWriteError | None:
        """Write activated fields by key (no envelope validation)."""
        outcome = _HaWriteOutcome()
        for field_name, value in fields.items():
            key = str(field_name or "").strip()
            if not key or key not in self.cfg.entities:
                outcome.failed.append(key or "unknown")
                outcome.messages.append(f"Missing HA write binding for {key}")
                continue
            ok, status, msg = self._try_setpoint_write(key, value)
            if not ok:
                outcome.failed.append(key)
                outcome.messages.append(msg)
                outcome.hub_status = status or outcome.hub_status
                if "ess" in key or key.startswith("set_ess"):
                    outcome.flip_ess = True
        self._last_skipped = list(outcome.skipped)
        self._last_unconfigured = list(outcome.unconfigured)
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
        return self._publish_setpoint_push(field_name, value)

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
