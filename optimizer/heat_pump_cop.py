"""COP of a heat pump by source and sink temperature (HeatControl P5, shared with SUSI P7).

Design: docs/dev/heat-control-sg-ready.md § 8.2. The heating system stores COP points
(``heat_source.cop_points``: source °C, sink °C, COP). They form a grid: every source
temperature with every sink temperature. ``CopCurve.cop_at`` interpolates linearly in both
directions and holds the edge value outside the grid, so a curve never extrapolates. A grid
with one source temperature has no source dependence.

The values are absolute (what the pump delivers at that point); nothing here scales them to
the JAZ.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

_KEYS = ("source_c", "sink_c", "cop")


@dataclass(frozen=True)
class CopCurve:
    """COP grid: ``cop[i][j]`` at ``source_c[i]`` and ``sink_c[j]`` (both ascending)."""

    source_c: tuple[float, ...]
    sink_c: tuple[float, ...]
    cop: tuple[tuple[float, ...], ...]

    def cop_at(self, source_c: float, sink_c: float) -> float:
        """COP at the given temperatures; held at the grid's edge outside it."""
        i0, i1, wi = _bracket(self.source_c, float(source_c))
        j0, j1, wj = _bracket(self.sink_c, float(sink_c))
        low = self.cop[i0][j0] + (self.cop[i0][j1] - self.cop[i0][j0]) * wj
        high = self.cop[i1][j0] + (self.cop[i1][j1] - self.cop[i1][j0]) * wj
        return low + (high - low) * wi

    def points(self) -> list[dict[str, float]]:
        """The stored shape, sorted by source and sink temperature."""
        return [
            {"source_c": source, "sink_c": sink, "cop": self.cop[i][j]}
            for i, source in enumerate(self.source_c)
            for j, sink in enumerate(self.sink_c)
        ]


def _bracket(axis: tuple[float, ...], value: float) -> tuple[int, int, float]:
    """Indices of the grid values around ``value`` and its weight between them."""
    if value <= axis[0]:
        return 0, 0, 0.0
    if value >= axis[-1]:
        last = len(axis) - 1
        return last, last, 0.0
    upper = bisect_right(axis, value)
    lower = upper - 1
    return lower, upper, (value - axis[lower]) / (axis[upper] - axis[lower])


def _number(point: dict, key: str, where: str) -> float:
    raw = point.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{where}: {key} fehlt oder ist keine Zahl.")
    return float(raw)


def cop_curve_from_points(raw: Any, *, label: str) -> CopCurve:
    """Validated curve from ``cop_points``; every inconsistency fails loud.

    Rejected: an empty list, unknown keys, a COP ≤ 0, a point given twice, a grid with gaps,
    a COP that rises with the sink temperature or falls with the source temperature.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label}: cop_points muss eine nicht leere Liste sein.")
    values: dict[tuple[float, float], float] = {}
    for index, point in enumerate(raw):
        where = f"{label}: cop_points[{index}]"
        if not isinstance(point, dict):
            raise ValueError(f"{where} muss ein Objekt mit source_c, sink_c und cop sein.")
        extra = sorted(set(point) - set(_KEYS))
        if extra:
            raise ValueError(f"{where}: unbekannte Felder {', '.join(extra)}.")
        source, sink, cop = (_number(point, key, where) for key in _KEYS)
        if cop <= 0.0:
            raise ValueError(f"{where}: cop muss > 0 sein (ist {cop:g}).")
        if (source, sink) in values:
            raise ValueError(
                f"{where}: Punkt Quelle {source:g} °C / Senke {sink:g} °C ist doppelt."
            )
        values[(source, sink)] = cop
    sources = tuple(sorted({source for source, _sink in values}))
    sinks = tuple(sorted({sink for _source, sink in values}))
    missing = [(s, k) for s in sources for k in sinks if (s, k) not in values]
    if missing:
        text = ", ".join(f"Quelle {s:g} °C / Senke {k:g} °C" for s, k in missing)
        raise ValueError(
            f"{label}: cop_points bilden kein Raster (jede Quellentemperatur mit jeder "
            f"Senkentemperatur); es fehlt: {text}."
        )
    grid = tuple(tuple(values[(s, k)] for k in sinks) for s in sources)
    for i, source in enumerate(sources):
        for j in range(1, len(sinks)):
            if grid[i][j] > grid[i][j - 1]:
                raise ValueError(
                    f"{label}: cop_points bei Quelle {source:g} °C: der COP steigt von Senke "
                    f"{sinks[j - 1]:g} °C auf {sinks[j]:g} °C ({grid[i][j - 1]:g} → "
                    f"{grid[i][j]:g}); er muss mit der Senkentemperatur fallen."
                )
    for j, sink in enumerate(sinks):
        for i in range(1, len(sources)):
            if grid[i][j] < grid[i - 1][j]:
                raise ValueError(
                    f"{label}: cop_points bei Senke {sink:g} °C: der COP fällt von Quelle "
                    f"{sources[i - 1]:g} °C auf {sources[i]:g} °C ({grid[i - 1][j]:g} → "
                    f"{grid[i][j]:g}); er darf mit der Quellentemperatur nicht fallen."
                )
    return CopCurve(source_c=sources, sink_c=sinks, cop=grid)
