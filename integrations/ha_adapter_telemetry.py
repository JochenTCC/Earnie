"""HA adapter telemetry read paths (REST pull and push transport) as a mixin.

Split out of ``integrations.ha_adapter``; ``HaAdapter`` inherits these methods.
"""
from __future__ import annotations

from typing import Any

from ehal import EHAL_SCHEMA_VERSION, EhalTelemetry, validate_telemetry
from ehal.field_catalog import TELEMETRY_OPTIONAL_HA as TELEMETRY_OPTIONAL
from ehal.field_catalog import TELEMETRY_REQUIRED
from integrations.ha_adapter_core import (
    _NONNEG_TELEMETRY,
    HaHttpError,
    _utc_ts,
    apply_sign,
    logger,
    parse_ha_field_value,
)
from integrations.ha_units import UnitMismatchError


class HaTelemetryMixin:
    """Telemetry reads, push-read fences and Topology P2 balance for ``HaAdapter``."""

    def read_telemetry(self) -> EhalTelemetry:
        if self._push:
            return self._read_telemetry_push()
        from integrations.pv_attribution import (
            load_components_for_attribution,
            load_house_for_attribution,
            plant_pv_may_be_derived,
        )

        house = load_house_for_attribution()
        components = load_components_for_attribution()
        derive_pv = plant_pv_may_be_derived(house, components)
        required = tuple(
            name
            for name in TELEMETRY_REQUIRED
            if not (derive_pv and name == "sens_pv_production_active")
        )
        missing = [
            name for name in required if not self._entity_key_for_kind(name)
        ]
        if missing:
            raise HaHttpError(
                "HA telemetry mapping incomplete: " + ", ".join(missing)
            )

        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
        }
        for field_name in required:
            doc[field_name] = self._read_mapped_numeric(field_name)
        for field_name in TELEMETRY_OPTIONAL:
            # sens_ess_power / load derive handled in Topology P2 balance step.
            if field_name in ("sens_ess_power", "sens_power_consumers"):
                if field_name == "sens_power_consumers" and self._entity_key_for_kind(
                    field_name
                ):
                    try:
                        value = self._read_mapped_numeric(field_name)
                    except (HaHttpError, ValueError):
                        continue
                    doc[field_name] = max(0.0, value)
                continue
            if not self._entity_key_for_kind(field_name):
                continue
            try:
                value = self._read_mapped_numeric(field_name)
            except (HaHttpError, ValueError):
                continue
            if field_name in _NONNEG_TELEMETRY:
                value = max(0.0, value)
            doc[field_name] = value

        doc = self._apply_topology_p2_balance(doc, house=house, components=components)
        plant_doc = {
            k: v
            for k, v in doc.items()
            if not (str(k).startswith("inv.") or str(k).startswith("pv."))
        }
        return validate_telemetry(plant_doc)

    def _entity_key_for_kind(self, kind: str) -> str | None:
        from integrations.ha_push_read import adapter_key_for_kind

        return adapter_key_for_kind(self.cfg.entities, kind)

    def _push_qid_for_kind(self, kind: str) -> tuple[str, str] | None:
        """Return ``(adapter_field_key, qualified_id)`` when push-read is activated."""
        key = self._entity_key_for_kind(kind)
        if not key:
            return None
        qid = self.cfg.push_read_qids.get(key)
        if not qid:
            return None
        return key, qid

    def _read_telemetry_push(self) -> EhalTelemetry:
        from integrations.ha_push_read import PushReadError, read_push_ehal_value
        from integrations.pv_attribution import (
            load_components_for_attribution,
            load_house_for_attribution,
            plant_pv_may_be_derived,
        )

        house = load_house_for_attribution()
        components = load_components_for_attribution()
        derive_pv = plant_pv_may_be_derived(house, components)
        required = tuple(
            name
            for name in TELEMETRY_REQUIRED
            if not (derive_pv and name == "sens_pv_production_active")
        )
        missing = [
            name for name in required if self._push_qid_for_kind(name) is None
        ]
        if missing:
            raise HaHttpError(
                "HA push read not activated for: " + ", ".join(missing)
            )

        doc: dict[str, Any] = {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": _utc_ts(),
            "adapter_id": self.cfg.adapter_id,
        }
        for field_name in required:
            adapter_key, qid = self._push_qid_for_kind(field_name)  # type: ignore[misc]
            try:
                doc[field_name] = read_push_ehal_value(
                    qid,
                    sign=self.cfg.sign,
                    adapter_field=adapter_key,
                )
            except PushReadError as exc:
                raise HaHttpError(str(exc)) from exc
        self._read_push_optional_fields(doc)

        doc = self._apply_topology_p2_balance(doc, house=house, components=components)
        plant_doc = {
            k: v
            for k, v in doc.items()
            if not (str(k).startswith("inv.") or str(k).startswith("pv."))
        }
        return validate_telemetry(plant_doc)

    def _read_push_optional_fields(self, doc: dict[str, Any]) -> None:
        """Add optional push-read telemetry fields to ``doc`` (skip unreadable)."""
        from integrations.ha_push_read import PushReadError, read_push_ehal_value

        for field_name in TELEMETRY_OPTIONAL:
            if field_name in ("sens_ess_power", "sens_power_consumers"):
                if field_name == "sens_power_consumers":
                    resolved = self._push_qid_for_kind(field_name)
                    if resolved is not None:
                        adapter_key, qid = resolved
                        try:
                            value = read_push_ehal_value(
                                qid,
                                sign=self.cfg.sign,
                                adapter_field=adapter_key,
                            )
                        except PushReadError:
                            continue
                        doc[field_name] = max(0.0, value)
                continue
            resolved = self._push_qid_for_kind(field_name)
            if resolved is None:
                continue
            adapter_key, qid = resolved
            try:
                value = read_push_ehal_value(
                    qid,
                    sign=self.cfg.sign,
                    adapter_field=adapter_key,
                )
            except PushReadError:
                continue
            if field_name in _NONNEG_TELEMETRY:
                value = max(0.0, value)
            doc[field_name] = value

    def _scoped_pv_live(self, components: dict) -> dict:
        """Entity-scoped PV live values read through HA (REST or push transport)."""
        from integrations.pv_attribution import (
            collect_scoped_pv_live_from_bindings,
            read_scoped_pv_ha,
        )

        def _read_field(field: str) -> float | None:
            return read_scoped_pv_ha(field, adapter=self)

        if not self._push:
            return collect_scoped_pv_live_from_bindings(
                components, read_value=_read_field
            )
        from integrations.ha_push_read import PushReadError, read_push_ehal_value

        def _read_push_scoped(field: str) -> float | None:
            qid = self.cfg.push_read_qids.get(field)
            if not qid:
                return None
            try:
                return max(
                    0.0,
                    float(
                        read_push_ehal_value(
                            qid,
                            sign=self.cfg.sign,
                            adapter_field=field,
                        )
                    ),
                )
            except PushReadError:
                return None

        return collect_scoped_pv_live_from_bindings(
            components, read_value=_read_push_scoped
        )

    def _apply_ess_sum_and_load(
        self,
        out: dict[str, Any],
        *,
        batteries: list[dict],
        inverters: list[dict],
        plant: dict,
    ) -> None:
        """Σ grid-tied ESS power; derive ``sens_power_consumers`` when not measured."""
        from integrations.plant_balance import (
            balance_tolerances_from_plant,
            derive_sens_power_consumers_w,
            grid_tied_house_batteries,
            sum_grid_tied_house_ess_power_w,
        )

        eligible = grid_tied_house_batteries(batteries, inverters)
        bat_by_id = {
            str(b.get("id") or "").strip(): b
            for b in batteries
            if str(b.get("id") or "").strip()
        }

        def _read_ess(bid: str) -> float | None:
            return self._read_ess_power_w_for_battery(
                bat_by_id.get(bid) or {},
                eligible_count=len(eligible),
            )

        try:
            out["sens_ess_power"] = sum_grid_tied_house_ess_power_w(
                batteries=batteries,
                inverters=inverters,
                read_power_w=_read_ess,
            )
        except ValueError as exc:
            raise HaHttpError(str(exc)) from exc

        if out.get("sens_power_consumers") is None:
            pct, watts = balance_tolerances_from_plant(plant)
            try:
                out["sens_power_consumers"] = derive_sens_power_consumers_w(
                    out, tolerance_pct=pct, tolerance_w=watts
                )
            except ValueError as exc:
                raise HaHttpError(str(exc)) from exc

    def _apply_topology_p2_balance(
        self,
        doc: dict[str, Any],
        *,
        house: dict,
        components: dict,
    ) -> dict[str, Any]:
        """PV coverage, Σ ESS power, derived load with tolerance (Topology P2)."""
        from integrations.plant_balance import pv_covers_all_inverters_from_plant
        from integrations.pv_attribution import with_attributed_plant_pv

        plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
        batteries = [
            b for b in (components.get("batteries") or []) if isinstance(b, dict)
        ]
        inverters = [
            inv
            for inv in (components.get("inverters") or [])
            if isinstance(inv, dict)
        ]
        pv_systems = [
            pv
            for pv in (components.get("pv_systems") or [])
            if isinstance(pv, dict)
        ]
        scoped = self._scoped_pv_live(components)
        try:
            out = with_attributed_plant_pv(
                doc,
                scoped_live=scoped,
                inverters=inverters,
                pv_systems=pv_systems,
                pv_covers_all_inverters=pv_covers_all_inverters_from_plant(
                    plant
                ),
            )
        except ValueError as exc:
            raise HaHttpError(str(exc)) from exc
        if "sens_pv_production_active" in out:
            out["sens_pv_production_active"] = max(
                0.0, float(out["sens_pv_production_active"])
            )
        self._apply_ess_sum_and_load(
            out, batteries=batteries, inverters=inverters, plant=plant
        )
        return out


    def _read_ess_power_w_for_battery(
        self,
        battery: dict,
        *,
        eligible_count: int,
    ) -> float | None:
        """Read ``ess.{id}.sens_ess_power``; legacy plant-flat only for single ESS."""
        from ehal.ess_fields import ess_field

        bid = str(battery.get("id") or "").strip()
        if not bid:
            return None
        field = ess_field(bid, "sens_ess_power")
        try:
            if self._push:
                resolved = self._push_qid_for_kind(field)
                if resolved is not None:
                    return float(self._read_mapped_numeric(field))
            elif field in self.cfg.entities or self._entity_key_for_kind(field):
                return float(self._read_mapped_numeric(field))
        except (HaHttpError, ValueError):
            return None
        # Single grid-tied house battery may still use plant-flat sens_ess_power.
        if eligible_count == 1 and self._entity_key_for_kind("sens_ess_power"):
            try:
                return float(self._read_mapped_numeric("sens_ess_power"))
            except (HaHttpError, ValueError):
                return None
        return None

    def _fence_rest_field(self, field_name: str) -> None:
        if not self._push:
            return
        key = self._entity_key_for_kind(field_name) or field_name
        if key in self.cfg.push_read_qids:
            raise HaHttpError(
                f"HA push: REST read blocked for push-activated field {field_name!r} "
                f"(use push inbox, qualified id {self.cfg.push_read_qids[key]!r})"
            )

    def _fence_rest_entity(self, entity_id: str) -> None:
        if not self._push:
            return
        eid = str(entity_id or "").strip()
        if not eid:
            return
        for field, mapped in self.cfg.entities.items():
            if mapped == eid and field in self.cfg.push_read_qids:
                raise HaHttpError(
                    f"HA push: REST read blocked for push-activated entity {eid!r} "
                    f"(field {field!r})"
                )

    def _read_mapped_numeric(self, field_name: str) -> float:
        if self._push:
            from integrations.ha_push_read import PushReadError, read_push_ehal_value

            resolved = self._push_qid_for_kind(field_name)
            if resolved is None:
                key = self._entity_key_for_kind(field_name)
                if key and key in self.cfg.entities:
                    raise HaHttpError(
                        f"HA push: field {field_name!r} is not push-activated"
                    )
                raise HaHttpError(f"HA telemetry mapping incomplete: {field_name}")
            adapter_key, qid = resolved
            try:
                return read_push_ehal_value(
                    qid,
                    sign=self.cfg.sign,
                    adapter_field=adapter_key,
                )
            except PushReadError as exc:
                raise HaHttpError(str(exc)) from exc
        key = self._entity_key_for_kind(field_name) or field_name
        entity_id = self.cfg.entities.get(key)
        if not entity_id:
            raise HaHttpError(f"HA telemetry mapping incomplete: {field_name}")
        self._fence_rest_field(field_name)
        payload = self.read_state(entity_id)
        attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        unit = attrs.get("unit_of_measurement")
        try:
            raw = parse_ha_field_value(field_name, str(payload.get("state")), unit=unit)
        except UnitMismatchError as exc:
            logger.warning(
                "HA unit mismatch adapter_id=%s field=%s entity=%s: %s",
                self.cfg.adapter_id,
                field_name,
                entity_id,
                exc,
            )
            raise
        from ehal.ess_fields import ess_field_kind
        from ehal.inverter_fields import inv_field_kind

        kind = ess_field_kind(field_name) or inv_field_kind(field_name) or field_name
        if kind == "sens_ess_soc" or field_name == "sens_ess_soc":
            return float(raw)
        # Per-battery entity-scoped sign override, else flat kind / field inherit (2.7.m).
        mode = self.cfg.sign.get(field_name) or self.cfg.sign.get(kind)
        return apply_sign(raw, mode)
