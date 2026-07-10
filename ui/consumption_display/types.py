"""Typen für die gemeinsame Verbrauchs-UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConsumptionDisplayMode(str, Enum):
    CSV_VALIDATION = "csv_validation"
    CONS_DATA = "cons_data"
    MODELED_PROFILE = "modeled_profile"


@dataclass(frozen=True)
class ConsumptionSeriesBundle:
    """Stündliche Verbrauchsserien für Charts und Aggregation."""

    timestamps: list[str]
    consumer_series: dict[str, list[float]]
    baseload: list[float]
    pv: list[float] | None = None
    actual_total: list[float] | None = None
    consumer_labels: dict[str, str] = field(default_factory=dict)

    def hour_count(self) -> int:
        return len(self.timestamps)

    def consumer_ids(self) -> list[str]:
        return list(self.consumer_series.keys())
