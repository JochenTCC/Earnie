"""Synthetische Verbrauchsprofile aus Hausprofilen für Backtesting."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

MODELED_PROFILE_REF_START = datetime(2023, 1, 1)
MODELED_PROFILE_HOURS_PER_YEAR = 8760

from data.heating_need import (
    daily_electric_kwh,
    heating_params_from_thermal,
    hourly_profile_for_year,
    thermal_daily_pwm_hourly_profile,
    weekly_electric_kwh,
)
from house_config.baseload import consumer_annual_kwh
from house_config.consumption_csv import consumer_uses_profile_csv, load_hourly_profile_csv
from house_config.ev_profile import ev_hourly_kw_for_day

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext


def build_hourly_kw_profile(profile: dict, *, hours: int = 8760) -> list[float]:
    """
    Erzeugt stündliches kW-Profil: Grundlast + Verbraucher-Anteile gleichmäßig verteilt.
    Bei total_profile_csv wird diese Datei bevorzugt.
    """
    csv_path = profile.get("total_profile_csv", "")
    if csv_path:
        series = load_hourly_profile_csv(csv_path)
        values = [kw for _, kw in series]
        if len(values) >= hours:
            return values[:hours]
        pad = values[-1] if values else 0.0
        return values + [pad] * (hours - len(values))

    return build_modeled_hourly_kw_profile(profile, hours=hours)


def _consumer_id(consumer: dict, fallback_index: int) -> str:
    cid = consumer.get("id") or consumer.get("label")
    if cid:
        return str(cid)
    return f"consumer_{fallback_index}"


def _modeled_hour_index(slot_dt: datetime) -> int:
    naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
    return (
        int((naive - MODELED_PROFILE_REF_START).total_seconds() // 3600)
        % MODELED_PROFILE_HOURS_PER_YEAR
    )


def _parse_profile_timestamp(ts_raw: str) -> datetime:
    return datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])


def _timestamp_hour_key(slot_dt: datetime) -> str:
    naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
    naive = naive.replace(minute=0, second=0, microsecond=0)
    return naive.strftime("%Y-%m-%d %H:%M:%S")


@lru_cache(maxsize=32)
def _csv_kw_lookup(path: str) -> dict[str, float]:
    return {ts: float(kw) for ts, kw in load_hourly_profile_csv(path)}


def csv_kw_at_datetime(path: str, slot_dt: datetime) -> float:
    """kW from a historical CSV at the calendar hour (0 if missing)."""
    return float(_csv_kw_lookup(path).get(_timestamp_hour_key(slot_dt), 0.0))


def modeled_consumer_kw_at_datetime(
    consumer: dict,
    slot_dt: datetime,
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """kW für einen Verbraucher zum Kalenderzeitpunkt (wie Backtesting-Overlay)."""
    if climate is not None and consumer.get("type") == "thermal_annual":
        return climate.thermal_consumer_kw_at(consumer, slot_dt)
    if climate is not None and consumer.get("type") == "thermal_rc":
        return climate.thermal_rc_consumer_kw_at(consumer, slot_dt)
    if consumer_uses_profile_csv(consumer):
        return csv_kw_at_datetime(consumer["profile_csv"], slot_dt)
    if consumer.get("type") == "ev":
        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        day_hourly = ev_hourly_kw_for_day(consumer, naive.date())
        return float(day_hourly[naive.hour])
    if consumer.get("type") == "thermal_annual":
        profile = _modeled_consumer_hourly_kw(
            consumer,
            hours=MODELED_PROFILE_HOURS_PER_YEAR,
        )
        return float(profile[_modeled_hour_index(slot_dt)])
    if consumer.get("type") == "thermal_rc":
        profile = _modeled_consumer_hourly_kw(
            consumer,
            hours=MODELED_PROFILE_HOURS_PER_YEAR,
        )
        hour_index = _modeled_hour_index(slot_dt)
        return float(profile[hour_index]) if hour_index < len(profile) else 0.0
    if consumer.get("type") == "generic" and consumer.get("schedule"):
        from house_config.generic_schedule import generic_hourly_kw_for_day

        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        day_hourly = generic_hourly_kw_for_day(consumer, naive.date())
        return float(day_hourly[naive.hour])
    consumer_kwh = consumer_annual_kwh(consumer)
    return consumer_kwh / MODELED_PROFILE_HOURS_PER_YEAR


def _modeled_consumer_hourly_kw(consumer: dict, *, hours: int) -> list[float]:
    hourly = [0.0] * hours
    if consumer_uses_profile_csv(consumer):
        path = consumer["profile_csv"]
        return [
            csv_kw_at_datetime(path, MODELED_PROFILE_REF_START + timedelta(hours=i))
            for i in range(hours)
        ]
    if consumer.get("type") == "ev":
        start_day = date(2023, 1, 1)
        for hour_index in range(hours):
            day = start_day + timedelta(days=hour_index // 24)
            day_hourly = ev_hourly_kw_for_day(consumer, day)
            hourly[hour_index] = day_hourly[hour_index % 24]
        return hourly
    if consumer.get("type") == "thermal_annual":
        thermal = consumer.get("thermal") or consumer
        daily = daily_electric_kwh(**heating_params_from_thermal(thermal))
        nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
        if nominal > 0.0:
            return thermal_daily_pwm_hourly_profile(
                daily,
                nominal_power_kw=nominal,
                hours_per_year=hours,
            )
        weekly = weekly_electric_kwh(**heating_params_from_thermal(thermal))
        return hourly_profile_for_year(weekly, hours_per_year=hours)
    if consumer.get("type") == "thermal_rc":
        from house_config.thermal_rc_profile import thermal_rc_hourly_kw_from_ambient

        rc = consumer.get("thermal_rc") or consumer
        lat = rc.get("latitude")
        lon = rc.get("longitude")
        if lat is not None and lon is not None:
            import config as _cfg

            if getattr(_cfg, "CONFIG", None) is not None:
                from data.open_meteo_solar_archive import (
                    build_open_meteo_climate_bundle_for_year,
                    last_full_archive_year,
                )

                year = last_full_archive_year()
                bundle = build_open_meteo_climate_bundle_for_year(
                    year,
                    lat=float(lat),
                    lon=float(lon),
                    timezone=str(rc.get("timezone_name") or _cfg.get_planning_timezone()),
                    surfaces=[],
                )
                profile = thermal_rc_hourly_kw_from_ambient(
                    consumer,
                    bundle.temperature_c,
                )
                if len(profile) >= hours:
                    return profile[:hours]
                pad = profile[-1] if profile else 0.0
                return profile + [pad] * (hours - len(profile))
        consumer_kwh = consumer_annual_kwh(consumer)
        add_kw = consumer_kwh / max(1, hours)
        return [add_kw] * hours
    if consumer.get("type") == "generic" and consumer.get("schedule"):
        from house_config.generic_schedule import generic_hourly_kw_for_day

        start_day = date(2023, 1, 1)
        for hour_index in range(hours):
            day = start_day + timedelta(days=hour_index // 24)
            day_hourly = generic_hourly_kw_for_day(consumer, day)
            hourly[hour_index] = day_hourly[hour_index % 24]
        return hourly
    consumer_kwh = consumer_annual_kwh(consumer)
    add_kw = consumer_kwh / max(1, hours)
    return [add_kw] * hours


def build_modeled_hourly_kw_by_consumer(
    profile: dict,
    *,
    hours: int = 8760,
) -> dict[str, list[float]]:
    """Stündliche kW je Verbraucher; Key ``baseload`` für Grundlast."""
    csv_path = str(profile.get("total_profile_csv", "") or "").strip()
    if csv_path:
        return _by_consumer_aligned_to_total_csv(profile, csv_path, hours=hours)
    result: dict[str, list[float]] = {}
    for index, consumer in enumerate(profile.get("consumers", [])):
        result[_consumer_id(consumer, index)] = _modeled_consumer_hourly_kw(
            consumer,
            hours=hours,
        )
    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / max(1, hours)
    result["baseload"] = [baseload_kw] * hours
    return result


def build_modeled_kw_for_timestamps(
    profile: dict,
    timestamps: list[str],
) -> dict[str, list[float]]:
    """Independent model on calendar hours — ignores ``total_profile_csv``.

    Uses metric ``baseload_kwh`` as constant kW (÷ 8760), not meter residual.
    """
    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / MODELED_PROFILE_HOURS_PER_YEAR
    result: dict[str, list[float]] = {}
    for index, consumer in enumerate(profile.get("consumers", [])):
        cid = _consumer_id(consumer, index)
        result[cid] = [
            modeled_consumer_kw_at_datetime(consumer, _parse_profile_timestamp(ts))
            for ts in timestamps
        ]
    result["baseload"] = [baseload_kw] * len(timestamps)
    return result


def _by_consumer_aligned_to_total_csv(
    profile: dict,
    csv_path: str,
    *,
    hours: int,
) -> dict[str, list[float]]:
    """Consumer + residual baseload on the total_profile_csv timeline."""
    series = load_hourly_profile_csv(csv_path)
    rows = list(series[:hours])
    if len(rows) < hours:
        pad_ts, pad_kw = rows[-1] if rows else ("1970-01-01 00:00:00", 0.0)
        start = _parse_profile_timestamp(pad_ts)
        while len(rows) < hours:
            start = start + timedelta(hours=1)
            rows.append((start.strftime("%Y-%m-%d %H:%M:%S"), float(pad_kw)))
    timestamps = [ts for ts, _ in rows]
    total = [float(kw) for _, kw in rows]
    result: dict[str, list[float]] = {}
    for index, consumer in enumerate(profile.get("consumers", [])):
        cid = _consumer_id(consumer, index)
        if consumer_uses_profile_csv(consumer):
            lookup = _csv_kw_lookup(consumer["profile_csv"])
            result[cid] = [float(lookup.get(ts, 0.0)) for ts in timestamps]
        else:
            result[cid] = [
                modeled_consumer_kw_at_datetime(
                    consumer, _parse_profile_timestamp(ts)
                )
                for ts in timestamps
            ]
    result["baseload"] = _residual_baseload_from_aligned(
        csv_path,
        profile,
        result,
        total=total,
    )
    return result


def _residual_baseload_from_aligned(
    csv_path: str,
    profile: dict,
    consumer_series: dict[str, list[float]],
    *,
    total: list[float],
) -> list[float]:
    """total − Σ(all stacked consumers); clip at 0 with warning count.

    Subtract every consumer series shown alongside baseload (CSV-instrumented
    and synthetic). Otherwise residual still contains non-CSV loads that are
    also stacked separately → double-counted energy / inflated Basislast.
    """
    import logging

    hours = len(total)
    subtract_ids = {
        cid
        for cid in consumer_series
        if cid != "baseload"
    }
    baseload: list[float] = []
    clipped = 0
    for hour in range(hours):
        flex_sum = sum(
            float(consumer_series[cid][hour])
            for cid in subtract_ids
            if cid in consumer_series and hour < len(consumer_series[cid])
        )
        residual = float(total[hour]) - flex_sum
        if residual < 0.0:
            clipped += 1
            residual = 0.0
        baseload.append(residual)
    if clipped:
        logging.getLogger(__name__).warning(
            "total_profile_csv residual clipped to 0 in %s of %s hours (%s).",
            clipped,
            hours,
            csv_path,
        )
    return baseload


def build_modeled_hourly_kw_profile(profile: dict, *, hours: int = 8760) -> list[float]:
    """Modelliertes Profil aus Verbrauchern — ignoriert total_profile_csv."""
    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    hourly = [0.0] * hours
    for series in by_consumer.values():
        hourly = [a + b for a, b in zip(hourly, series)]
    return hourly
