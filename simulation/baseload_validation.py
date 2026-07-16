"""Konsistente Grundlast aus historischen Verbrauchsdaten (Total vs. Flex)."""
from __future__ import annotations


def derive_historical_baseload_kwh(
    total_load_kwh: float,
    flex_totals_kwh: dict[str, float],
) -> float:
    """Grundlast-Summe: Gesamtverbrauch minus geloggte Flex-Summen."""
    flex_sum = sum(float(v) for v in flex_totals_kwh.values())
    return round(float(total_load_kwh) - flex_sum, 3)


def resolve_hourly_baseload_kw(
    total_load: list[float],
    hourly_flex_kw: list[float],
) -> tuple[list[float], float]:
    """
    Stündliche Grundlast (kW), sodass Summe Grundlast + Summe Flex == Summe Total.

    Pro Stunde: max(0, Total − Flex). Liegt Flex in einer Stunde über Total,
    wird die Differenz über die übrigen Stunden verteilt (Skalierung).
    """
    if len(total_load) != len(hourly_flex_kw):
        raise ValueError(
            "total_load und hourly_flex_kw müssen gleich lang sein "
            f"({len(total_load)} vs. {len(hourly_flex_kw)})."
        )
    if not total_load:
        return [], 0.0

    target_baseload = sum(float(t) for t in total_load) - sum(
        float(f) for f in hourly_flex_kw
    )
    raw = [
        max(0.0, float(total) - float(flex))
        for total, flex in zip(total_load, hourly_flex_kw)
    ]
    raw_sum = sum(raw)
    if abs(target_baseload) < 1e-9:
        return [0.0] * len(total_load), 0.0
    if raw_sum < 1e-9:
        per_hour = target_baseload / len(total_load)
        return [round(per_hour, 3) for _ in total_load], round(target_baseload, 3)

    scale = target_baseload / raw_sum
    scaled = [round(value * scale, 3) for value in raw]
    residual = round(target_baseload - sum(scaled), 3)
    if abs(residual) > 1e-9:
        scaled[-1] = round(scaled[-1] + residual, 3)
    return scaled, round(target_baseload, 3)


_CHART_RESERVED_KW_COLUMNS = frozenset(
    {
        "PV-Prognose (kW)",
        "PV-Ist (kW)",
        "Verbrauch-Prognose (kW)",
        "Geplante Batterie-Aktion (kW)",
        "Netzbezug (kW)",
    }
)


def _flex_chart_column_names(flexible_consumers: list | None) -> set[str]:
    if not flexible_consumers:
        return set()
    from optimizer.targets import consumer_column_name

    return {consumer_column_name(consumer) for consumer in flexible_consumers}


def baseload_kwh_from_chart_rows(
    rows: list[dict],
    *,
    flexible_consumers: list | None = None,
) -> float:
    """
    Summiert Grundlast über Simulationszeilen.

    Mit ``flexible_consumers`` werden known-Generic-Spalten nach Chart-1-Peel
    mitgezählt (alles außer reservierten und Flex-Spalten).
    """
    if not rows:
        return 0.0
    if flexible_consumers is None:
        return round(
            sum(float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0) for row in rows),
            3,
        )

    flex_cols = _flex_chart_column_names(flexible_consumers)
    total = 0.0
    for row in rows:
        total += float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        for key, value in row.items():
            if not key.endswith(" (kW)"):
                continue
            if key in _CHART_RESERVED_KW_COLUMNS or key in flex_cols:
                continue
            total += float(value or 0.0)
    return round(total, 3)
