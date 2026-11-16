"""Live: efficiency of the heat pump by temperature (HeatControl P5, design § 8.2).

With COP points in the heating system (``heat_source.cop_points``) the Live store plan uses
the curve instead of the JAZ:

- **Source:** ``heatpump.<id>.sens_temperature_source`` held over the horizon where it is
  mapped (the backend reports the source temperature during operation and holds it at
  standstill; Earnie does not filter it), otherwise the outside temperature forecast per slot.
- **Sink:** the store band is split into segments, bottom-up: band minimum to setpoint, above
  it steps of ``SEGMENT_STEP_K``, at most ``MAX_SEGMENTS`` in all. The sink temperature of a
  segment is its upper edge.

Without points the planned efficiency stays the JAZ and nothing changes. The source signal
mapped but without a value in a cycle: a warning, the JAZ for that cycle, and no charge above
the setpoint, because its cost is unknown.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from ehal.heat_fields import KIND_SOURCE_TEMP
from optimizer.heat_pump_cop import CopCurve

logger = logging.getLogger(__name__)

EFFICIENCY_JAZ = "jaz"
EFFICIENCY_SOURCE_SIGNAL = "cop_source_signal"
EFFICIENCY_OUTSIDE_FORECAST = "cop_outside_forecast"
# COP points exist and the source signal is mapped, but it sent no value this cycle.
EFFICIENCY_JAZ_NO_SOURCE_VALUE = "jaz_no_source_value"

SEGMENT_STEP_K = 5.0
MAX_SEGMENTS = 4


@dataclass(frozen=True)
class LiveEfficiency:
    """How the Live store plan converts electricity to heat in this cycle."""

    source: str = EFFICIENCY_JAZ
    curve: CopCurve | None = None
    # Source temperature held over the horizon (signal); None = outside forecast per slot.
    source_temp_c: float | None = None

    @property
    def by_temperature(self) -> bool:
        return self.curve is not None


def _warn_no_source_value_once(cid: str) -> None:
    from optimizer.live_cycle_scope import cycle_memo

    def _log() -> bool:
        logger.warning(
            "Wärmepumpe '%s': %s ist gemappt, liefert aber keinen Wert. Live plant in diesem "
            "Zyklus mit der JAZ und lädt nicht über den Sollwert – Signal im Backend prüfen.",
            cid,
            KIND_SOURCE_TEMP,
        )
        return True

    cycle_memo(("heat_source_temp_no_value", cid), _log)


def resolve_live_efficiency(
    consumer: dict, feedback: dict[str, float | None]
) -> LiveEfficiency:
    """Efficiency of this cycle from the heating system's COP points and the feedback reads.

    ``feedback`` holds the mapped level 3 reads (a mapped kind without a value is ``None``).
    """
    from house_config.heat_source import consumer_heat_source, heat_source_cop_curve

    curve = heat_source_cop_curve(consumer_heat_source(consumer))
    if curve is None:
        return LiveEfficiency()
    if KIND_SOURCE_TEMP not in feedback:
        return LiveEfficiency(source=EFFICIENCY_OUTSIDE_FORECAST, curve=curve)
    value = feedback[KIND_SOURCE_TEMP]
    if value is None:
        _warn_no_source_value_once(str(consumer.get("id") or "?"))
        return LiveEfficiency(source=EFFICIENCY_JAZ_NO_SOURCE_VALUE)
    return LiveEfficiency(
        source=EFFICIENCY_SOURCE_SIGNAL, curve=curve, source_temp_c=float(value)
    )


def segment_edges_c(band_min_c: float, setpoint_c: float, charge_max_c: float) -> list[float]:
    """Temperatures between the segments, bottom-up, from the band minimum to the maximum."""
    edges = [float(band_min_c)]
    if setpoint_c > band_min_c + 1e-9:
        edges.append(float(setpoint_c))
    above = float(charge_max_c) - float(setpoint_c)
    if above > 1e-9:
        count = min(MAX_SEGMENTS - (len(edges) - 1), math.ceil(above / SEGMENT_STEP_K - 1e-9))
        edges.extend(float(setpoint_c) + above * (i + 1) / count for i in range(count))
    if len(edges) < 2:
        raise ValueError(
            f"Speicherband ohne Breite ({band_min_c:g} °C bis {charge_max_c:g} °C): "
            "keine COP-Segmente möglich."
        )
    return edges


def segment_cops(
    efficiency: LiveEfficiency, edges_c: list[float], source_c_by_slot: list[float]
) -> list[list[float]]:
    """COP per segment (bottom-up) and slot; the sink temperature is the segment's upper edge."""
    curve = efficiency.curve
    if curve is None:
        raise ValueError("COP-Segmente ohne Kennlinie angefordert.")
    return [
        [curve.cop_at(source, upper) for source in source_c_by_slot] for upper in edges_c[1:]
    ]


def efficiency_observability(efficiency: LiveEfficiency, jaz: float) -> dict[str, Any]:
    return {
        "source": efficiency.source,
        "jaz": round(float(jaz), 3),
        "source_temp_c": efficiency.source_temp_c,
        "cop_points": 0 if efficiency.curve is None else len(efficiency.curve.points()),
    }
