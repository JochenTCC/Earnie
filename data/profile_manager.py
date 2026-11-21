# profile_manager.py
import logging
import os
import pandas as pd
from datetime import datetime, timedelta, date
from typing import List, Tuple, Optional
from . import pv_forecast
import config
from . import market_prices
from . import feed_in_prices
from . import cons_data_store
from data.price_forecast_live import is_extrapolated_source, resolve_market_slots_kwargs
from runtime_store.persist_paths import (
    consumption_profiles_file,
    flexible_consumer_profiles_file,
    total_consumption_profiles_file,
)
from runtime_store.planning_clock import planning_now

logger = logging.getLogger(__name__)

_REMEDY_GENERATE_CONS_DATA = (
    "Abhilfe: im Szenario-Explorer „Verbrauchsdaten generieren (synthetisch)“ ausführen "
    "oder gemessene Verbrauchsdaten abwarten; Earnie berechnet die Profile im nächsten "
    "Zyklus neu."
)


class ConsumptionProfileUnavailableError(RuntimeError):
    """A consumption profile the plan needs is missing, unreadable or incomplete (cycle aborts)."""


class MissingConsumptionDataError(ValueError):
    """cons_data.csv has no rows, or not every hour, for a day a logged-day run needs."""


def _remedy_delete_profile(profile_path: str) -> str:
    return (
        f"Abhilfe: '{profile_path}' löschen; Earnie berechnet die Datei im nächsten Zyklus "
        "aus cons_data.csv neu."
    )


def _cons_data_to_profile_dataframe(cons_df: pd.DataFrame) -> pd.DataFrame:
    """Wandelt cons_data in das interne Profil-Format (Total, BaseLoad, Verbraucher-Namen)."""
    from data.cons_data_house_profile import (
        consumer_labels_for_ids,
        expected_cons_data_consumer_ids,
    )

    df = pd.DataFrame(index=cons_df.index)
    df["Total"] = cons_df["total_kw"]
    df["BaseLoad"] = cons_df["baseload_kw"]
    consumer_ids = expected_cons_data_consumer_ids()
    labels = consumer_labels_for_ids(consumer_ids)
    for consumer_id in consumer_ids:
        col = f"{consumer_id}_kw"
        name = labels.get(consumer_id, consumer_id)
        df[name] = cons_df[col] if col in cons_df.columns else 0.0
    return df


def load_cons_data_profile_dataframe() -> pd.DataFrame | None:
    """Lädt cons_data.csv als Profil-DataFrame; None wenn leer/fehlend."""
    cons_df = cons_data_store.load_cons_data()
    if cons_df.empty:
        return None
    return _cons_data_to_profile_dataframe(cons_df)


def load_cons_data_pv_series() -> pd.Series:
    """PV-Zeitreihe (kW) aus cons_data."""
    cons_df = cons_data_store.load_cons_data()
    if cons_df.empty:
        return pd.Series(dtype=float)
    return cons_df["pv_kw"]


def _load_profile_source_dataframe() -> pd.DataFrame | None:
    """Datenquelle für Profile und Historie: ausschließlich cons_data.csv."""
    return load_cons_data_profile_dataframe()


def _flex_profile_export_spec(df: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    """
    Spalten aus dem cons_data-Profil-DF für flexible_consumer_profiles.csv.

    Nutzt cons_data-Labels (nicht config.name) und schreibt kanonische CSV-Spalten.
    Verbraucher ohne cons_data-Spalte werden übersprungen.
    """
    from data.cons_data_house_profile import (
        consumer_labels_for_ids,
        expected_cons_data_consumer_ids,
    )
    from settings.flexible_consumers import profile_column_id

    cons_ids = set(expected_cons_data_consumer_ids())
    label_cols: list[str] = []
    rename_to_csv: dict[str, str] = {}
    for consumer in config.get_flexible_consumers():
        lookup_id = str(consumer["id"])
        if lookup_id not in cons_ids:
            continue
        label = consumer_labels_for_ids([lookup_id]).get(lookup_id)
        if not label or label not in df.columns:
            continue
        label_cols.append(label)
        rename_to_csv[label] = profile_column_id(consumer)
    return label_cols, rename_to_csv


def generate_consumption_profile() -> None:
    """Berechnet Verbrauchsprofile aus cons_data.csv.

    Raises :class:`ConsumptionProfileUnavailableError` when cons_data.csv is missing or
    empty, or when the profiles cannot be computed or written.
    """
    print("[cache] Verarbeite Verbrauchsdaten und isoliere die Haus-Grundlast...")
    try:
        df = _load_profile_source_dataframe()
    except Exception as exc:
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofile nicht berechenbar: cons_data.csv nicht lesbar ({exc}). "
            f"{_REMEDY_GENERATE_CONS_DATA}"
        ) from exc
    if df is None or df.empty:
        path = cons_data_store.get_output_path()
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofile nicht berechenbar: '{path}' fehlt oder ist leer. "
            f"{_REMEDY_GENERATE_CONS_DATA}"
        )
    try:
        df['Month'] = df.index.month
        df['Weekday'] = df.index.weekday
        df['Hour'] = df.index.hour

        profile = df.groupby(['Month', 'Weekday', 'Hour'])['BaseLoad'].mean().reset_index()
        profile.rename(columns={'BaseLoad': 'Consumption'}, inplace=True)
        profile['Consumption'] = profile['Consumption'].round(3)
        profile.to_csv(consumption_profiles_file(), index=False, sep=';')

        total_profile = df.groupby(['Month', 'Weekday', 'Hour'])['Total'].mean().reset_index()
        total_profile.rename(columns={'Total': 'Consumption'}, inplace=True)
        total_profile['Consumption'] = total_profile['Consumption'].round(3)
        total_profile.to_csv(total_consumption_profiles_file(), index=False, sep=';')

        label_cols, rename_to_csv = _flex_profile_export_spec(df)
        if label_cols:
            flex_profile = df.groupby(["Month", "Weekday", "Hour"])[
                label_cols
            ].mean().reset_index()
            flex_profile.rename(columns=rename_to_csv, inplace=True)
            for csv_col in rename_to_csv.values():
                flex_profile[csv_col] = flex_profile[csv_col].round(3)
            flex_profile.to_csv(flexible_consumer_profiles_file(), index=False, sep=";")
    except Exception as exc:
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofile nicht berechenbar: {exc}. {_REMEDY_GENERATE_CONS_DATA}"
        ) from exc
    print(
        "[OK] 'consumption_profiles.csv', 'total_consumption_profiles.csv' "
        "und ggf. 'flexible_consumer_profiles.csv' erfolgreich neu berechnet!"
    )


def _flex_profile_needs_regeneration() -> bool:
    """True wenn flexible_consumer_profiles.csv fehlt, nicht lesbar ist oder einem
    gemessenen flexiblen Verbraucher (cons_data-Spalte) seine Profilspalte fehlt."""
    from data.cons_data_house_profile import expected_cons_data_consumer_ids
    from settings.flexible_consumers import profile_column_id

    profiled_ids = set(expected_cons_data_consumer_ids())
    expected = {
        profile_column_id(consumer)
        for consumer in config.get_flexible_consumers()
        if str(consumer["id"]) in profiled_ids
    }
    if not expected:
        return False
    flex_path = flexible_consumer_profiles_file()
    if not os.path.exists(flex_path):
        return True
    try:
        header = pd.read_csv(flex_path, sep=";", nrows=0).columns.tolist()
    except Exception:
        return True
    return not expected.issubset(header)


def _flex_profile_status_message() -> str:
    """Kurzstatus für Logs: Spalten in flexible_consumer_profiles.csv."""
    flex_path = flexible_consumer_profiles_file()
    if not os.path.exists(flex_path):
        return "flexible_consumer_profiles.csv fehlt"
    try:
        header = pd.read_csv(flex_path, sep=";", nrows=0).columns.tolist()
    except Exception as exc:
        return f"flexible_consumer_profiles.csv nicht lesbar ({exc})"
    data_cols = sorted(
        col for col in header if col not in {"Month", "Weekday", "Hour", "Consumption"}
    )
    if not data_cols:
        return "flexible_consumer_profiles.csv ohne Verbraucher-Spalten"
    return f"flexible_consumer_profiles.csv OK ({len(data_cols)} Spalten: {', '.join(data_cols[:6])}{'…' if len(data_cols) > 6 else ''})"


def check_and_update_profile_if_new_month() -> None:
    """Überprüft, ob ein neuer Monat begonnen hat, und triggert ggf. das Profil-Update."""
    profile_path = consumption_profiles_file()
    should_update = False
    update_reason = ""
    
    if not os.path.exists(profile_path):
        update_reason = "consumption_profiles.csv fehlt"
        should_update = True
    elif not os.path.exists(total_consumption_profiles_file()):
        update_reason = "total_consumption_profiles.csv fehlt"
        should_update = True
    elif _flex_profile_needs_regeneration():
        update_reason = "flexible_consumer_profiles.csv fehlt, unvollständig oder veraltet"
        should_update = True
    else:
        file_time = os.path.getmtime(profile_path)
        file_date = datetime.fromtimestamp(file_time)
        current_date = planning_now()
        
        if file_date.month != current_date.month or file_date.year != current_date.year:
            update_reason = (
                f"neuer Monat (letztes Profil {file_date.strftime('%d.%m.%Y')})"
            )
            should_update = True
            
    if should_update:
        print(f"[info] Profil-Update: {update_reason}.")
        logger.info("Profil-Update: %s", update_reason)
        generate_consumption_profile()
    else:
        status = _flex_profile_status_message()
        logger.info("Profil-Check: %s — kein Update nötig.", status)


def _read_profile_csv(profile_path: str, columns: list[str]) -> pd.DataFrame:
    """Profil-CSV mit Month/Weekday/Hour und ``columns``; sonst ConsumptionProfileUnavailableError."""
    if not os.path.exists(profile_path):
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofil '{profile_path}' fehlt. {_REMEDY_GENERATE_CONS_DATA}"
        )
    try:
        df_profiles = pd.read_csv(profile_path, sep=';')
    except Exception as exc:
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofil '{profile_path}' nicht lesbar ({exc}). "
            f"{_remedy_delete_profile(profile_path)}"
        ) from exc
    missing = [col for col in ["Month", "Weekday", "Hour", *columns] if col not in df_profiles.columns]
    if missing:
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofil '{profile_path}' ohne Spalte(n) {', '.join(missing)}. "
            f"{_remedy_delete_profile(profile_path)}"
        )
    return df_profiles


def _profile_values(
    df_profiles: pd.DataFrame, column: str, target_hours: List, profile_path: str
) -> List[float]:
    """Werte je Zielstunde: exakter Month/Weekday/Hour-Eintrag, sonst Mittel der Stunde in der Datei."""
    try:
        lookup = df_profiles.set_index(['Month', 'Weekday', 'Hour'])[column].to_dict()
        hour_mean = df_profiles.groupby('Hour')[column].mean().to_dict()
    except Exception as exc:
        raise ConsumptionProfileUnavailableError(
            f"Verbrauchsprofil '{profile_path}' nicht auswertbar ({exc}). "
            f"{_remedy_delete_profile(profile_path)}"
        ) from exc
    values = []
    for dt in target_hours:
        key = (dt.month, dt.weekday(), dt.hour)
        if key in lookup:
            values.append(float(lookup[key]))
        elif dt.hour in hour_mean:
            values.append(float(hour_mean[dt.hour]))
        else:
            raise ConsumptionProfileUnavailableError(
                f"Verbrauchsprofil '{profile_path}' hat keine Werte für {dt.hour:02d} Uhr "
                f"(Spalte {column}). {_REMEDY_GENERATE_CONS_DATA}"
            )
    return values


def _load_hourly_profile(target_hours: List, profile_path: str, column: str = "Consumption") -> List[float]:
    """Lädt stündliche Profilwerte (Month/Weekday/Hour) für die Zielstunden.

    Raises :class:`ConsumptionProfileUnavailableError` when the file is missing, unreadable
    or has no value for an hour of the day; no invented load.
    """
    df_profiles = _read_profile_csv(profile_path, [column])
    return _profile_values(df_profiles, column, target_hours, profile_path)


def _load_consumption_profile(target_hours: List) -> List[float]:
    """Lädt das Grundlast-Profil für die Zielstunden."""
    base = _load_hourly_profile(target_hours, consumption_profiles_file())
    return _apply_house_profile_baseload_overlay(target_hours, base)


def _apply_house_profile_baseload_overlay(
    target_hours: List,
    baseload: List[float],
) -> List[float]:
    """Bekannt-Verbraucher aus Hausprofil auf Live-Grundlast (CSV wenn aktiv).

    Manuelles Gerät is not overlaid here — only user day-plans via
    appliance_schedules. Live always uses path-A style overlay (not meter residual).

    ``thermal_annual`` consumers that are MILP flex (Haus Wärme) are skipped in the
    thermal overlay — same as SE ``milp_flex_thermal_ids`` — so their power is not
    double-counted into Verbrauch-Prognose / Chart-1 Grundlast.
    """
    profile = config.get_resolved_runtime_settings().get("_house_profile")
    if not profile:
        return baseload
    from house_config.planning_flex_bridge import (
        fixed_generic_hourly_overlay,
        milp_flex_thermal_annual_ids,
        thermal_hourly_overlay,
    )

    resolved_flex = config.get_flexible_consumers()
    thermal_milp_ids = milp_flex_thermal_annual_ids(resolved_flex)
    from optimizer.absent_mode import resolve_live_absent_skip_ids

    absent_skip_ids = resolve_live_absent_skip_ids(profile)
    generic = fixed_generic_hourly_overlay(
        profile,
        target_hours,
        skip_ids=absent_skip_ids,
        meter_residual_mode=False,
    )
    thermal = thermal_hourly_overlay(
        profile,
        target_hours,
        milp_flex_thermal_ids=thermal_milp_ids,
    )
    overlay = [round(g + t, 6) for g, t in zip(generic, thermal)]
    return [round(base + extra, 3) for base, extra in zip(baseload, overlay)]


def _load_total_consumption_profile(target_hours: List) -> List[float]:
    """Lädt das Gesamtverbrauchs-Profil (Grundlast + flexible Verbraucher) für die Zielstunden."""
    return _load_hourly_profile(target_hours, total_consumption_profiles_file())


def _build_optimization_matrix(
    market_data: list,
    forecast_consumption: list,
    forecast_pv: list,
    forecast_total_consumption: list | None = None,
    target_hours: list | None = None,
) -> list:
    """Erstellt die Optimierungs-Matrix mit Preis-, Verbrauchs- und PV-Daten."""
    if target_hours is None or len(target_hours) < 1:
        raise ValueError(
            "_build_optimization_matrix erfordert mindestens eine Zielstunde."
        )
    if not (
        len(forecast_consumption) == len(target_hours) == len(forecast_pv)
    ):
        raise ValueError(
            "forecast_consumption, forecast_pv und target_hours müssen gleiche Länge haben."
        )

    slot_kwargs = resolve_market_slots_kwargs(target_hours)
    price_slots = market_prices.resolve_market_slots(
        market_data,
        target_hours,
        **slot_kwargs,
    )
    from data.backtesting_prices import (
        enrich_slots_import_prices,
        pricing_kwargs_from_resolved,
    )

    def _market_for(slots: list) -> list[float]:
        # Quarter-hours outside the horizon that an hourly settled tariff needs (D1):
        # same source as the horizon (day-ahead, else mirror / forecast).
        resolved = market_prices.resolve_market_slots(market_data, slots, **slot_kwargs)
        return [float(row["price_buy"]) for row in resolved]

    enrich_slots_import_prices(
        price_slots,
        target_hours,
        market_for=_market_for,
        **pricing_kwargs_from_resolved(
            config.get_resolved_runtime_settings(),
        ),
    )
    optimization_matrix = []

    for i, price_slot in enumerate(price_slots):
        row = {
            "hour": price_slot["hour"],
            "date": target_hours[i].date(),
            "slot_datetime": target_hours[i],
            "k_act": price_slot["k_act"],
            "price_buy": price_slot["price_buy"],
            "price_source": price_slot["price_source"],
            "expected_p_act": forecast_consumption[i],
            "expected_p_pv": forecast_pv[i],
            "consumption_mode": "forecast",
        }
        if forecast_total_consumption is not None:
            row["expected_p_total"] = forecast_total_consumption[i]
        optimization_matrix.append(row)

    feed_in_prices.enrich_matrix_feed_in_prices(
        optimization_matrix,
        config.get_feed_in_settings(),
        market_for=_market_for,
    )
    return optimization_matrix


def _load_flexible_consumer_hourly_profiles(target_hours: List) -> dict[str, List[float]]:
    """Lädt stündliche Profilwerte je flexiblem Verbraucher für die Zielstunden.

    Consumers without a cons_data column (``expected_cons_data_consumer_ids``) get a zero
    profile: they are not measured. For every other consumer the column must be in
    flexible_consumer_profiles.csv, else :class:`ConsumptionProfileUnavailableError`.
    """
    from settings.flexible_consumers import profile_column_id

    from data.cons_data_house_profile import expected_cons_data_consumer_ids

    consumers = config.get_flexible_consumers()
    if not consumers:
        return {}
    profiled_ids = set(expected_cons_data_consumer_ids())
    column_by_consumer = {
        str(consumer["id"]): profile_column_id(consumer)
        for consumer in consumers
        if str(consumer["id"]) in profiled_ids
    }
    profiles: dict[str, List[float]] = {
        consumer["id"]: [0.0] * len(target_hours)
        for consumer in consumers
        if str(consumer["id"]) not in column_by_consumer
    }
    if not column_by_consumer:
        return profiles
    profile_path = flexible_consumer_profiles_file()
    df_profiles = _read_profile_csv(profile_path, list(column_by_consumer.values()))
    for consumer in consumers:
        col = column_by_consumer.get(str(consumer["id"]))
        if col is not None:
            profiles[consumer["id"]] = _profile_values(df_profiles, col, target_hours, profile_path)
    return {consumer["id"]: profiles[consumer["id"]] for consumer in consumers}


def compute_live_planning_window(now: datetime | None = None):
    """
    Berechnet das Sunset-Planungsfenster für den Live-Betrieb.

    now muss timezone-aware sein oder wird aus config.get_planning_timezone() abgeleitet.
    """
    from zoneinfo import ZoneInfo

    from .planning_window import compute_planning_window

    tz_name = config.get_planning_timezone()
    tz = ZoneInfo(tz_name)
    if now is None:
        now = planning_now(tz)
    elif now.tzinfo is None:
        raise ValueError(
            "compute_live_planning_window: now muss timezone-aware sein "
            f"(z. B. ZoneInfo('{tz_name}'))."
        )
    else:
        now = now.astimezone(tz)

    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    return compute_planning_window(now, lat, lon, tz_name)


def build_live_planning_matrix(market_data: list, window) -> list:
    """Baut die Live-Optimierungsmatrix für ein Sunset-Planungsfenster."""
    from data.live_planning_matrix import (
        assemble_live_planning_rows,
        log_live_flex_horizon,
        warn_live_matrix_price_extrapolation,
    )

    check_and_update_profile_if_new_month()
    target_hours = list(window.slot_datetimes)
    slot_count = len(target_hours)
    logger.info(
        "Matrix-Aufbau: %d Slots (%s → %s)",
        slot_count,
        target_hours[0].strftime("%Y-%m-%d %H:%M"),
        target_hours[-1].strftime("%Y-%m-%d %H:%M"),
    )
    optimization_matrix, flex_profiles = assemble_live_planning_rows(
        market_data, target_hours
    )
    log_live_flex_horizon(flex_profiles)
    warn_live_matrix_price_extrapolation(optimization_matrix)
    return optimization_matrix


def get_forecast_vectors(market_data) -> Tuple[List[float], List[float], List[dict]]:
    """
    Lädt das passende historische Verbrauchsprofil und die PV-Prognose 
    für die NÄCHSTEN 24 STUNDEN (rollierender Horizont ab der aktuellen Stunde).
    """
    now = planning_now().replace(minute=0, second=0, microsecond=0)
    check_and_update_profile_if_new_month()
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    
    forecast_consumption = _load_consumption_profile(target_hours)
    forecast_total = _load_total_consumption_profile(target_hours)
    flex_profiles = _load_flexible_consumer_hourly_profiles(target_hours)
    forecast_pv = pv_forecast.get_hourly_pv_forecast()
    optimization_matrix = _build_optimization_matrix(
        market_data,
        forecast_consumption,
        forecast_pv,
        forecast_total_consumption=forecast_total,
        target_hours=target_hours,
    )
    for i, row in enumerate(optimization_matrix):
        row["expected_flex_kw"] = {
            cid: flex_profiles[cid][i]
            for cid in flex_profiles
        }

    return forecast_consumption[:24], forecast_pv[:24], optimization_matrix[:24]


# ==============================================================================
# NEU: EXTRAKTION DER GRUNDLAST UND TAGESSUMMEN FÜR DEN OPTIMIZER (SIMULATION)
# ==============================================================================
def _local_hours_of_day(day: date) -> list[int]:
    """Clock hours that exist on ``day`` in the planning timezone (spring DST day: 23)."""
    from datetime import time, timezone
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(config.get_planning_timezone())
    hours = []
    for hour in range(24):
        naive = datetime.combine(day, time(hour))
        round_trip = naive.replace(tzinfo=tz).astimezone(timezone.utc).astimezone(tz)
        if round_trip.replace(tzinfo=None) == naive:
            hours.append(hour)
    return hours


def get_historical_day_data(
    target_date, *, require_complete: bool = False
) -> Tuple[List[float], dict, List[float]]:
    """
    Extrahiert für ein bestimmtes Datum die 24-stündige Grundlast, die Tages-Summen
    der steuerbaren Verbraucher sowie den geloggten Gesamtverbrauch (kW pro Stunde).

    A day without rows in cons_data returns ``([], {}, [])``: no totals, the caller decides
    (Live: configured ``daily_target_kwh``). Hours missing inside a day count as 0 kW with a
    warning. ``require_complete=True`` (Szenario-Explorer / Backtesting, logged day) raises
    :class:`MissingConsumptionDataError` for a day without rows or with missing hours.
    """
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    df = _load_profile_source_dataframe()
    df_day = df[df.index.date == target_date] if df is not None and not df.empty else None
    expected_hours = _local_hours_of_day(target_date)
    present_hours = set() if df_day is None else set(df_day.index.hour)
    missing_hours = [hour for hour in expected_hours if hour not in present_hours]
    if missing_hours and require_complete:
        what = (
            "keine Daten"
            if len(missing_hours) == len(expected_hours)
            else f"{len(missing_hours)} von {len(expected_hours)} Stunden fehlen "
            f"({', '.join(f'{hour:02d}' for hour in missing_hours)} Uhr)"
        )
        raise MissingConsumptionDataError(
            f"cons_data.csv: für den {target_date:%d.%m.%Y} {what}. Den Zeitraum auf Tage mit "
            "vollständigen Verbrauchsdaten einschränken oder die Verbrauchsdaten neu erzeugen."
        )
    if df_day is None or df_day.empty:
        logger.warning("cons_data.csv: keine Daten für %s.", target_date)
        return [], {}, []
    if missing_hours:
        logger.warning(
            "cons_data.csv: für %s fehlen %d Stunden (%s Uhr); sie zählen mit 0 kW.",
            target_date,
            len(missing_hours),
            ", ".join(f"{hour:02d}" for hour in missing_hours),
        )

    full_day_range = pd.date_range(
        start=f"{target_date} 00:00:00",
        end=f"{target_date} 23:00:00",
        freq='1h',
    )
    df_day = df_day.reindex(full_day_range, fill_value=0.0)

    from data.cons_data_house_profile import consumer_labels_for_ids

    flexible = config.get_flexible_consumers()
    labels = consumer_labels_for_ids([str(consumer["id"]) for consumer in flexible])
    historical_totals = {
        consumer["id"]: round(float(df_day[labels[str(consumer["id"])]].sum()), 3)
        if labels[str(consumer["id"])] in df_day.columns
        else 0.0
        for consumer in flexible
    }
    actual_baseload = df_day['BaseLoad'].round(3).tolist()
    actual_total = df_day['Total'].round(3).tolist()

    return actual_baseload, historical_totals, actual_total


def get_cons_data_date_bounds() -> Tuple[Optional[date], Optional[date]]:
    """Frühestes und spätestes Datum in cons_data.csv."""
    ts_min, ts_max = cons_data_store.get_date_bounds()
    if ts_min is None or ts_max is None:
        return None, None
    return ts_min.date(), ts_max.date()


def get_historical_date_picker_bounds(months_back: int = 12) -> Tuple[date, date]:
    """Wählbarer Datumsbereich: Schnittmenge aus cons_data und den letzten N Monaten."""
    today = datetime.now().date()
    rolling_min = today - timedelta(days=months_back * 30)

    lox_min, lox_max = get_cons_data_date_bounds()
    if lox_min is None or lox_max is None:
        return rolling_min, today - timedelta(days=1)

    min_date = max(lox_min, rolling_min)
    max_date = min(lox_max, today - timedelta(days=1))
    if min_date > max_date:
        max_date = lox_max
    return min_date, max_date
