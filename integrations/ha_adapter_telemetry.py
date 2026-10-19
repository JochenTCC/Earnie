"""HA adapter telemetry read paths (push transport only) as a mixin.

Split out of ``integrations.ha_adapter``; ``HaAdapter`` inherits these methods.
Binding P5e removed the REST pull branch.
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
)


class HaTelemetryMixin:
    """Telemetry reads and Topology P2 balance for ``HaAdapter`` (push-only)."""

    def read_telemetry(self) -> EhalTelemetry:
        return self._read_telemetry_push()

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
        )

        house = load_house_for_attribution()
        components = load_components_for_attribution()
        required = tuple(TELEMETRY_REQUIRED)
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
            if not (
                str(k).startswith("inv.")
                or str(k).startswith("pv.")
                or str(k).startswith("_")
            )
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
        """Entity-scoped PV live values via push inbox."""
        from integrations.ha_push_read import PushReadError, read_push_ehal_value
        from integrations.pv_attribution import collect_scoped_pv_live_from_bindings

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
            plant_pv_w = float(out.pop("_plant_pv_ac_w", 0.0))
            try:
                out["sens_power_consumers"] = derive_sens_power_consumers_w(
                    out,
                    plant_pv_w=plant_pv_w,
                    tolerance_pct=pct,
                    tolerance_w=watts,
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
        from integrations.pv_attribution import (
            derive_plant_pv_ac_w,
            scoped_pv_live_from_telemetry,
            with_attributed_plant_pv,
        )

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
            )
            merged = dict(scoped)
            merged.update(scoped_pv_live_from_telemetry(out))
            out["_plant_pv_ac_w"] = derive_plant_pv_ac_w(
                merged, inverters, pv_systems
            )
        except ValueError as exc:
            raise HaHttpError(str(exc)) from exc
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
        """Read ``ess.{id}.sens_ess_power`` via push; legacy plant-flat for single ESS."""
        from ehal.ess_fields import ess_field

        bid = str(battery.get("id") or "").strip()
        if not bid:
            return None
        field = ess_field(bid, "sens_ess_power")
        try:
            resolved = self._push_qid_for_kind(field)
            if resolved is not None:
                return float(self._read_mapped_numeric(field))
        except (HaHttpError, ValueError):
            return None
        if eligible_count == 1 and self._push_qid_for_kind("sens_ess_power"):
            try:
                return float(self._read_mapped_numeric("sens_ess_power"))
            except (HaHttpError, ValueError):
                return None
        return None

    def _read_mapped_numeric(self, field_name: str) -> float:
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
