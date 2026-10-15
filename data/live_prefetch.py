"""Prefetch slow Live inputs for the next tick (EarlyStart follow-up, spec §8).

Runs in the daemon right after a cycle has committed, in the idle time before
the next start. It computes the next cycle's inputs *for the next tick*
(``planning_anchor``) so the in-process caches hold exactly the keys that
cycle will look up, and refreshes entries that would expire before it reads
them (``cache_valid_until``). The next cycle then plans on warm caches.

Covered (network, slow): day-ahead prices (around the auction), EU weather and
power for the price forecast (incl. the bias lookback), outdoor temperature and
collector irradiance from Open-Meteo. Not covered: forecast.solar — its
15-min API guard and rate limit stay with the cycle.

A failed step is logged and skipped; the cycle then fetches that input itself,
as it always did.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Skip the prefetch when the next start is closer than this.
MIN_IDLE_SEC = 120.0
# Caches must stay valid this long after the next start (the cycle reads them
# within its first seconds; the margin covers slow starts).
READ_MARGIN_SEC = 120.0


@dataclass(frozen=True)
class PrefetchResult:
    tick: datetime
    duration_sec: float
    events: tuple[str, ...]
    errors: tuple[str, ...]


def _step(name: str, errors: list[str], fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — prefetch never breaks the daemon
        errors.append(f"{name}: {type(exc).__name__}: {exc}")
        logger.warning("Prefetch %s fehlgeschlagen (%s) — Zyklus lädt selbst.", name, exc)


def _prefetch_prices(window) -> None:
    from data import market_prices
    from data.live_market_prices import fetch_live_day_ahead_prices
    from data.price_forecast_live import resolve_market_slots_kwargs

    market_data = fetch_live_day_ahead_prices(planning_end=window.end)
    if not market_data:
        raise ValueError("keine Day-Ahead-Preise")
    target_hours = list(window.slot_datetimes)
    # Same call as the matrix build: EU features for missing slots + bias lookback.
    market_prices.resolve_market_slots(
        market_data, target_hours, **resolve_market_slots_kwargs(target_hours)
    )


def _prefetch_thermal_weather(window) -> None:
    import config
    from data.outdoor_forecast import get_hourly_outdoor_forecast_c
    from house_config.planning_flex_bridge import _house_thermal_consumers
    from optimizer.thermal_live_store import resolve_live_collector_solar_kw
    from optimizer.thermal_targets import thermal_horizon_hours_from_slots

    horizon_h = thermal_horizon_hours_from_slots(len(window.slot_datetimes))
    get_hourly_outdoor_forecast_c(horizon=horizon_h)
    profile = config.get_resolved_runtime_settings().get("_house_profile") or {}
    for item in _house_thermal_consumers(profile):
        thermal = item.get("thermal") or item
        if float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0) > 0.0:
            resolve_live_collector_solar_kw(thermal, profile, horizon_h)


def prefetch_live_inputs(tick: datetime, start_at: datetime) -> PrefetchResult:
    """Warm the caches for the cycle that starts at ``start_at`` and plans for ``tick``."""
    from data import profile_manager
    from runtime_store.cycle_duration_stats import collect_events
    from runtime_store.planning_clock import cache_valid_until, planning_anchor

    t0 = time.perf_counter()
    errors: list[str] = []
    valid_until = start_at + timedelta(seconds=READ_MARGIN_SEC)
    with planning_anchor(tick), cache_valid_until(valid_until), collect_events() as events:
        window = profile_manager.compute_live_planning_window()
        _step("Preise", errors, lambda: _prefetch_prices(window))
        _step("Wetter", errors, lambda: _prefetch_thermal_weather(window))
    result = PrefetchResult(
        tick=tick,
        duration_sec=round(time.perf_counter() - t0, 1),
        events=tuple(events),
        errors=tuple(errors),
    )
    logger.info(
        "Prefetch für %s: %s in %.1f s%s",
        tick.strftime("%H:%M"),
        ", ".join(result.events) if result.events else "alles aus dem Cache",
        result.duration_sec,
        f" ({len(result.errors)} Fehler)" if result.errors else "",
    )
    return result
