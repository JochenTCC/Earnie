"""DataUpdateCoordinator that ticks house_sim.core on the wall clock."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ARCHETYPE,
    CONF_PV_KWP,
    CONF_PV_SOURCE,
    CONF_UPDATE_INTERVAL,
    CONF_WEATHER_ENTITY,
    DEFAULT_PV_KWP,
    DEFAULT_UPDATE_INTERVAL_S,
    DOMAIN,
    PV_SOURCE_SYNTHETIC,
    PV_SOURCE_WEATHER,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .entity_map import ha_entity_id

from ._core.archetype import ArchetypePackage, load_archetype
from ._core.physics import (
    EssSetpoints,
    PhysicsState,
    ScenarioOverlay,
    initial_physics,
    step_physics,
)
from ._core.weather_pv import pv_kw_from_weather

_LOGGER = logging.getLogger(__name__)


class HouseSimCoordinator(DataUpdateCoordinator[PhysicsState]):
    """Wall-clock stepper with scenario overlays and fault injection."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval_s = int(
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_S)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(1, interval_s)),
        )
        self.entry = entry
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        self.package: ArchetypePackage = load_archetype(
            str(entry.data[CONF_ARCHETYPE]),
            fixtures_dir=fixtures_dir,
        )
        self.overlay = ScenarioOverlay()
        self.setpoints: dict[str, float] = {}
        self.switch_states: dict[str, bool] = {}
        self.unavailable_until: dict[str, float] = {}
        self.reject_writes = False
        self.setpoint_lag_s = 0.0
        self._pending_setpoints: dict[str, tuple[float, float]] = {}
        self.unit_flip = False
        self._last_tick_monotonic: float | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        self.physics = initial_physics(self.package)
        self._seed_setpoints_from_fixture()

    def _seed_setpoints_from_fixture(self) -> None:
        for item in self.package.entities:
            eid = str(item.get("entity_id") or "")
            domain = eid.split(".", 1)[0]
            if domain not in ("number", "input_number"):
                if domain == "switch":
                    self.switch_states[ha_entity_id(eid)] = (
                        str(item.get("state") or "").lower() in ("on", "true", "1")
                    )
                continue
            try:
                value = float(str(item.get("state") or "0").replace(",", "."))
            except ValueError:
                value = 0.0
            self.setpoints[ha_entity_id(eid)] = value

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if not isinstance(raw, dict):
            self._last_tick_monotonic = None
            return
        self.physics = replace(
            self.physics,
            soc_pct=float(raw.get("soc_pct", self.physics.soc_pct)),
            pv_energy_kwh=float(
                raw.get("pv_energy_kwh", self.physics.pv_energy_kwh)
            ),
            grid_import_energy_kwh=float(
                raw.get("grid_import_energy_kwh", self.physics.grid_import_energy_kwh)
            ),
            grid_export_energy_kwh=float(
                raw.get("grid_export_energy_kwh", self.physics.grid_export_energy_kwh)
            ),
            temp_c=(
                float(raw["temp_c"])
                if raw.get("temp_c") is not None
                else self.physics.temp_c
            ),
            evcs_power_w=float(raw.get("evcs_power_w", self.physics.evcs_power_w)),
        )
        saved_setpoints = raw.get("setpoints")
        if isinstance(saved_setpoints, dict):
            for key, value in saved_setpoints.items():
                try:
                    self.setpoints[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
        # Do not integrate downtime as one jump after restart.
        self._last_tick_monotonic = None

    async def async_persist(self) -> None:
        await self._store.async_save(
            {
                "soc_pct": self.physics.soc_pct,
                "pv_energy_kwh": self.physics.pv_energy_kwh,
                "grid_import_energy_kwh": self.physics.grid_import_energy_kwh,
                "grid_export_energy_kwh": self.physics.grid_export_energy_kwh,
                "temp_c": self.physics.temp_c,
                "evcs_power_w": self.physics.evcs_power_w,
                "setpoints": dict(self.setpoints),
            }
        )

    def _ess_setpoints(self) -> EssSetpoints:
        entities = self.package.ehal_entities

        def _num(field: str) -> float | None:
            fixture_id = entities.get(field)
            if not fixture_id:
                return None
            return self.setpoints.get(ha_entity_id(fixture_id))

        active = _num("set_ess_active_power")
        return EssSetpoints(
            active_power_w=float(active or 0.0),
            charge_limit_w=_num("set_ess_charge_power_limit"),
            discharge_limit_w=_num("set_ess_discharge_power_limit"),
        )

    def _apply_pending_setpoints(self, now_mono: float) -> None:
        ready = [
            eid
            for eid, (value, ready_at) in self._pending_setpoints.items()
            if ready_at <= now_mono
        ]
        for eid in ready:
            value, _ = self._pending_setpoints.pop(eid)
            self.setpoints[eid] = value

    def _pv_kw(self) -> float | None:
        source = str(self.entry.data.get(CONF_PV_SOURCE, PV_SOURCE_SYNTHETIC))
        if source != PV_SOURCE_WEATHER:
            return None
        weather_id = str(self.entry.data.get(CONF_WEATHER_ENTITY) or "").strip()
        if not weather_id:
            raise UpdateFailed("Weather PV selected but weather_entity_id is empty")
        weather = self.hass.states.get(weather_id)
        if weather is None:
            raise UpdateFailed(f"Weather entity missing: {weather_id}")
        cloud = weather.attributes.get("cloud_coverage")
        if cloud is None:
            raise UpdateFailed(
                f"Weather entity {weather_id} has no cloud_coverage attribute"
            )
        sun = self.hass.states.get("sun.sun")
        elevation = 0.0
        if sun is not None and sun.attributes.get("elevation") is not None:
            elevation = float(sun.attributes["elevation"])
        pv_kwp = float(self.entry.data.get(CONF_PV_KWP, DEFAULT_PV_KWP))
        return pv_kw_from_weather(pv_kwp, float(cloud), elevation)

    def entity_state_value(self, fixture_entity_id: str) -> Any:
        """Current native value for a fixture entity (after projection)."""
        ha_id = ha_entity_id(fixture_entity_id)
        if ha_id in self.unavailable_until:
            if dt_util.utcnow().timestamp() < self.unavailable_until[ha_id]:
                return None
            del self.unavailable_until[ha_id]

        physics = self.physics
        pairs = (
            ("sens_pv_production_active", physics.pv_kw),
            ("sens_ess_soc", physics.soc_pct),
            ("sens_ess_power", physics.ess_power_w),
            ("sens_grid_power_active", physics.grid_power_w),
            ("sens_evcs_active_power", physics.evcs_power_w),
            ("sens_pv_energy", physics.pv_energy_kwh),
            ("sens_grid_energy_import", physics.grid_import_energy_kwh),
            ("sens_grid_energy_export", physics.grid_export_energy_kwh),
        )
        for field_name, value in pairs:
            mapped = self.package.ehal_entities.get(field_name)
            if mapped != fixture_entity_id:
                continue
            if self.unit_flip and field_name == "sens_pv_production_active":
                return float(value) * 1000.0
            return value

        thermal_id = str(self.package.house_params.get("thermal_entity_id") or "")
        if fixture_entity_id == thermal_id and physics.temp_c is not None:
            return physics.temp_c

        if ha_id in self.setpoints:
            return self.setpoints[ha_id]
        if ha_id in self.switch_states:
            return self.switch_states[ha_id]
        return None

    def queue_setpoint(self, ha_entity_id_str: str, value: float) -> None:
        if self.reject_writes:
            raise HomeAssistantError("earnie_house_sim reject_writes active")
        now = self.hass.loop.time()
        if self.setpoint_lag_s > 0:
            self._pending_setpoints[ha_entity_id_str] = (
                float(value),
                now + float(self.setpoint_lag_s),
            )
            return
        self.setpoints[ha_entity_id_str] = float(value)

    def set_switch(self, ha_entity_id_str: str, is_on: bool) -> None:
        if self.reject_writes:
            raise HomeAssistantError("earnie_house_sim reject_writes active")
        self.switch_states[ha_entity_id_str] = bool(is_on)

    async def _async_update_data(self) -> PhysicsState:
        now_mono = self.hass.loop.time()
        self._apply_pending_setpoints(now_mono)
        if self._last_tick_monotonic is None:
            self._last_tick_monotonic = now_mono
            await self.async_persist()
            return self.physics

        dt_h = (now_mono - self._last_tick_monotonic) / 3600.0
        if dt_h <= 0:
            return self.physics
        # Cap a single tick so a stalled loop cannot skip hours of energy.
        dt_h = min(dt_h, 0.25)
        try:
            pv_override = self._pv_kw()
        except UpdateFailed:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UpdateFailed(str(exc)) from exc

        self.physics = step_physics(
            self.physics,
            package=self.package,
            setpoints=self._ess_setpoints(),
            dt_h=dt_h,
            overlay=self.overlay,
            pv_kw_override=pv_override,
        )
        self._last_tick_monotonic = now_mono
        await self.async_persist()
        return self.physics
