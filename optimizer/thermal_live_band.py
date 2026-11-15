"""Live heat-store band: the backend owns it where it reports it (HeatControl P1).

With both ``get_temperature_heat_storage_setpoint`` and
``get_temperature_heat_storage_tolerance`` mapped on the ``thermal_annual`` consumer
(function ``heat_storage_band`` in ``ehal.functions``), Live plans with these values and
not with ``heat_storage.setpoint_c`` / ``tolerance_c``. The values are read once per cycle
and held over the horizon. Not mapped, or only one of the two: the configured band, as
before. Mapped but without a value in this cycle (e.g. activated while the backend does not
send it yet): the configured band with a warning per cycle, recorded as
``BAND_SOURCE_CONFIG_NO_VALUE``. A negative tolerance is an error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ehal.functions import FunctionState, function_statuses
from ehal.heat_fields import (
    HEAT_STORE_BAND_KINDS,
    KIND_STORE_SETPOINT,
    KIND_STORE_TOLERANCE,
)
from optimizer.thermal_model import ThermalBand

logger = logging.getLogger(__name__)

BAND_FUNCTION_ID = "heat_storage_band"
BAND_SOURCE_BACKEND = "backend"
BAND_SOURCE_CONFIG = "config"
# Both mapped, but at least one sent no value this cycle: configured band, with a warning.
BAND_SOURCE_CONFIG_NO_VALUE = "config_no_value"


@dataclass(frozen=True)
class LiveStoreBand:
    band: ThermalBand
    source: str  # BAND_SOURCE_*


def heat_storage_band_state(consumer: dict) -> tuple[FunctionState, tuple[str, ...]]:
    """Mapping state of the band function on one consumer and its missing kinds."""
    from settings.ehal_marker_resolve import marker_thermal_annual_read

    mapped = [k for k in HEAT_STORE_BAND_KINDS if marker_thermal_annual_read(consumer, k)]
    for status in function_statuses(mapped, fields=HEAT_STORE_BAND_KINDS):
        if status.function.id == BAND_FUNCTION_ID:
            return status.state, status.missing
    raise RuntimeError(f"EHAL function '{BAND_FUNCTION_ID}' is not defined")


def _warn_incomplete_once(consumer: dict, missing: tuple[str, ...]) -> None:
    from optimizer.live_cycle_scope import cycle_memo

    cid = str(consumer.get("id") or "?")

    def _log() -> bool:
        logger.warning(
            "Wärmespeicher '%s': Speicherband des Backends unvollständig gemappt, es fehlt: "
            "%s. Live plant mit dem konfigurierten Band.",
            cid,
            ", ".join(missing),
        )
        return True

    cycle_memo(("heat_storage_band_incomplete", cid), _log)


def _warn_no_value_once(consumer: dict, unread: list[str]) -> None:
    from optimizer.live_cycle_scope import cycle_memo

    cid = str(consumer.get("id") or "?")

    def _log() -> bool:
        logger.warning(
            "Wärmespeicher '%s': %s ist gemappt, liefert aber keinen Wert. Live plant in "
            "diesem Zyklus mit dem konfigurierten Band – Signal im Backend prüfen.",
            cid,
            ", ".join(unread),
        )
        return True

    cycle_memo(("heat_storage_band_no_value", cid), _log)


def resolve_live_store_band(consumer: dict, configured: ThermalBand) -> LiveStoreBand:
    """Band Live plans with: the backend's when both signals are mapped, else ``configured``."""
    state, missing = heat_storage_band_state(consumer)
    if state != "available":
        if state == "incomplete":
            _warn_incomplete_once(consumer, missing)
        return LiveStoreBand(configured, BAND_SOURCE_CONFIG)
    from integrations.ehal_live import fetch_heat_feedback

    values = fetch_heat_feedback(consumer, kinds=HEAT_STORE_BAND_KINDS)
    cid = str(consumer.get("id") or "?")
    unread = [kind for kind in HEAT_STORE_BAND_KINDS if values.get(kind) is None]
    if unread:
        _warn_no_value_once(consumer, unread)
        return LiveStoreBand(configured, BAND_SOURCE_CONFIG_NO_VALUE)
    tolerance = float(values[KIND_STORE_TOLERANCE])
    if tolerance < 0.0:
        raise ValueError(
            f"Wärmespeicher '{cid}': {KIND_STORE_TOLERANCE} = {tolerance} K ist negativ."
        )
    return LiveStoreBand(
        ThermalBand(float(values[KIND_STORE_SETPOINT]), tolerance), BAND_SOURCE_BACKEND
    )
