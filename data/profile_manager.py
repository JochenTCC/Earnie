# profile_manager.py
import logging
import os
import pandas as pd
from datetime import datetime, timedelta, date, time
from typing import List, Tuple, Optional
from . import pv_forecast
import config
from . import data_loader
from . import market_prices
from . import feed_in_prices
from . import cons_data_store
from data.price_forecast_live import is_extrapolated_source, resolve_market_slots_kwargs
from runtime_store.persist_paths import (
    consumption_profiles_file,
    flexible_consumer_profiles_file,
    total_consumption_profiles_file,
)

logger = logging.getLogger(__name__)


def _cons_data_to_profile_dataframe(cons_df: pd.DataFrame) -> pd.DataFrame:
    """Wandelt cons_data_hourly in das interne Profil-Format (Total, BaseLoad, Verbraucher-Namen)."""
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
    """Lädt cons_data_hourly.csv als Profil-DataFrame; None wenn leer/fehlend."""
    cons_df = cons_data_store.load_cons_data()
    if cons_df.empty:
        return None
    return _cons_data_to_profile_dataframe(cons_df)


def load_cons_data_pv_series() -> pd.Series:
    """PV-Zeitreihe (kW) aus cons_data_hourly."""
    cons_df = cons_data_store.load_cons_data()
    if cons_df.empty:
        return pd.Series(dtype=float)
    return cons_df["pv_kw"]


def _load_profile_source_dataframe() -> pd.DataFrame | None:
    """Datenquelle für Profile und Historie: ausschließlich cons_data_hourly.csv."""
    return load_cons_data_profile_dataframe()


def _flex_profile_export_spec(df: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    """
    Spalten aus dem cons_data-Profil-DF für flexible_consumer_profiles.csv.

    Nutzt cons_data-Labels (nicht config.name) und schreibt runtime CSV-Spalten
    (legacy_id wenn gesetzt). Verbraucher ohne cons_data-Spalte werden übersprungen.
    """
    from data.cons_data_house_profile import (
        consumer_labels_for_ids,
        expected_cons_data_consumer_ids,
    )
    from settings.flexible_consumers import profile_column_id, runtime_consumer_id

    cons_ids = set(expected_cons_data_consumer_ids())
    label_cols: list[str] = []
    rename_to_csv: dict[str, str] = {}
    for consumer in config.get_flexible_consumers():
        runtime_id = runtime_consumer_id(consumer)
        canonical_id = str(consumer["id"])
        if runtime_id not in cons_ids and canonical_id not in cons_ids:
            continue
        lookup_id = runtime_id if runtime_id in cons_ids else canonical_id
        label = consumer_labels_for_ids([lookup_id]).get(lookup_id)
        if not label or label not in df.columns:
            continue
        label_cols.append(label)
        rename_to_csv[label] = profile_column_id(consumer)
    return label_cols, rename_to_csv


def generate_consumption_profile() -> bool:
    """Berechnet Verbrauchsprofile aus cons_data_hourly.csv."""
    try:
        print("[cache] Verarbeite Verbrauchsdaten und isoliere die Haus-Grundlast...")
        df = _load_profile_source_dataframe()
        if df is None or df.empty:
            path = cons_data_store.get_output_path()
            print(
                f"[WARN] Profil-Update abgebrochen: '{path}' fehlt oder ist leer. "
                "Bitte scripts/generate_cons_data.py ausführen."
            )
            return False
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

        print(
            "[OK] 'consumption_profiles.csv', 'total_consumption_profiles.csv' "
            "und ggf. 'flexible_consumer_profiles.csv' erfolgreich neu berechnet!"
        )
        return True
    except Exception as e:
        print(f"[FEHLER] Fehler bei der Profilberechnung: {e}")
        return False


def _flex_profile_needs_regeneration() -> bool:
    """True wenn flexible_consumer_profiles.csv fehlt oder keine Verbraucher-Spalten hat."""
    flex_path = flexible_consumer_profiles_file()
    if not config.get_flexible_consumers():
        return False
    if not os.path.exists(flex_path):
        return True
    try:
        header = pd.read_csv(flex_path, sep=";", nrows=0).columns.tolist()
    except Exception:
        return True
    data_cols = {col for col in header if col not in {"Month", "Weekday", "Hour"}}
    if not data_cols or data_cols == {"Consumption"}:
        return True
    from settings.flexible_consumers import profile_column_id

    expected = {
        profile_column_id(consumer)
        for consumer in config.get_flexible_consumers()
    }
    expected.update(str(consumer["id"]) for consumer in config.get_flexible_consumers())
    return not data_cols.intersection(expected)


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
    elif not os.path.exists(flexible_consumer_profiles_file()) and config.get_flexible_consumers():
        update_reason = "flexible_consumer_profiles.csv fehlt"
        should_update = True
    elif _flex_profile_needs_regeneration():
        update_reason = "flexible_consumer_profiles.csv unvollständig oder veraltet"
        should_update = True
    else:
        file_time = os.path.getmtime(profile_path)
        file_date = datetime.fromtimestamp(file_time)
        current_date = datetime.now()
        
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


def _load_hourly_profile(target_hours: List, profile_path: str, column: str = "Consumption") -> List[float]:
    """Lädt stündliche Profilwerte (Month/Weekday/Hour) für die Zielstunden."""
    global_hour_defaults = {h: 0.5 for h in range(24)}

    if not os.path.exists(profile_path):
        return [global_hour_defaults.get(dt.hour, 0.5) for dt in target_hours]

    try:
        df_profiles = pd.read_csv(profile_path, sep=';')
        lookup = df_profiles.set_index(['Month', 'Weekday', 'Hour'])[column].to_dict()
        hour_fallback = df_profiles.groupby('Hour')[column].mean().to_dict()
        values = []
        for dt in target_hours:
            key = (dt.month, dt.weekday(), dt.hour)
            if key in lookup:
                values.append(float(lookup[key]))
            elif dt.hour in hour_fallback:
                values.append(float(hour_fallback[dt.hour]))
            else:
                values.append(global_hour_defaults.get(dt.hour, 0.5))
        return values
    except Exception as e:
        print(f"[FEHLER] Fehler beim Verarbeiten von '{profile_path}': {e}. Nutze statische Defaults.")
        return [global_hour_defaults[dt.hour] for dt in target_hours]


def _load_consumption_profile(target_hours: List) -> List[float]:
    """Lädt das Grundlast-Profil für die Zielstunden."""
    base = _load_hourly_profile(target_hours, consumption_profiles_file())
    return _apply_house_profile_baseload_overlay(target_hours, base)


def _apply_house_profile_baseload_overlay(
    target_hours: List,
    baseload: List[float],
) -> List[float]:
    """Generic-Verbraucher mit earnie_role=known aus Hausprofil auf Grundlast."""
    profile = config.get_resolved_runtime_settings().get("_house_profile")
    if not profile:
        return baseload
    from house_config.planning_flex_bridge import (
        fixed_generic_hourly_overlay,
        house_profile_baseload_overlay,
    )

    if config.CONFIG._raw_config.get("flexible_consumers"):
        overlay = fixed_generic_hourly_overlay(profile, target_hours)
    else:
        overlay = house_profile_baseload_overlay(profile, target_hours)
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

    price_slots = market_prices.resolve_market_slots(
        market_data,
        target_hours,
        **resolve_market_slots_kwargs(target_hours),
    )
    from data.backtesting_prices import (
        enrich_slots_import_prices,
        pricing_kwargs_from_resolved,
    )

    enrich_slots_import_prices(
        price_slots,
        target_hours,
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
        if price_slot.get("mirrored_from") is not None:
            row["mirrored_from"] = price_slot["mirrored_from"]
        if forecast_total_consumption is not None:
            row["expected_p_total"] = forecast_total_consumption[i]
        optimization_matrix.append(row)

    feed_in_prices.enrich_matrix_feed_in_prices(
        optimization_matrix,
        config.get_feed_in_settings(),
    )
    return optimization_matrix


def _load_flexible_consumer_hourly_profiles(target_hours: List) -> dict[str, List[float]]:
    """Lädt stündliche Profilwerte je flexiblem Verbraucher für die Zielstunden."""
    from settings.flexible_consumers import profile_column_id

    consumers = config.get_flexible_consumers()
    profiles = {consumer["id"]: [] for consumer in consumers}
    profile_path = flexible_consumer_profiles_file()

    if not os.path.exists(profile_path):
        return {cid: [0.0] * len(target_hours) for cid in profiles}

    try:
        df_profiles = pd.read_csv(profile_path, sep=';')
        csv_columns = set(df_profiles.columns)
        column_by_consumer: dict[str, str] = {}
        for consumer in consumers:
            cid = str(consumer["id"])
            runtime_col = profile_column_id(consumer)
            if runtime_col in csv_columns:
                column_by_consumer[cid] = runtime_col
            elif cid in csv_columns:
                column_by_consumer[cid] = cid
        lookup = {
            cid: df_profiles.set_index(['Month', 'Weekday', 'Hour'])[col].to_dict()
            for cid, col in column_by_consumer.items()
        }
        hour_fallback = {
            cid: df_profiles.groupby('Hour')[col].mean().to_dict()
            for cid, col in column_by_consumer.items()
        }
        for dt in target_hours:
            key = (dt.month, dt.weekday(), dt.hour)
            for consumer in consumers:
                cid = consumer["id"]
                if cid not in lookup:
                    profiles[cid].append(0.0)
                    continue
                if key in lookup[cid]:
                    profiles[cid].append(float(lookup[cid][key]))
                elif dt.hour in hour_fallback[cid]:
                    profiles[cid].append(float(hour_fallback[cid][dt.hour]))
                else:
                    profiles[cid].append(0.0)
    except Exception as e:
        print(f"[FEHLER] Fehler beim Laden von '{profile_path}': {e}. Nutze Null-Profile.")
        return {cid: [0.0] * len(target_hours) for cid in profiles}

    return profiles


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
        now = datetime.now(tz)
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
    check_and_update_profile_if_new_month()
    target_hours = list(window.slot_datetimes)
    slot_count = len(target_hours)
    logger.info(
        "Matrix-Aufbau: %d Slots (%s → %s)",
        slot_count,
        target_hours[0].strftime("%Y-%m-%d %H:%M"),
        target_hours[-1].strftime("%Y-%m-%d %H:%M"),
    )

    logger.info("Matrix-Aufbau: Grundlast-Profil laden …")
    forecast_consumption = _load_consumption_profile(target_hours)
    logger.info("Matrix-Aufbau: Gesamtverbrauchs-Profil laden …")
    forecast_total = _load_total_consumption_profile(target_hours)
    logger.info("Matrix-Aufbau: Flexible Verbraucher-Profile laden …")
    flex_profiles = _load_flexible_consumer_hourly_profiles(target_hours)
    logger.info("Matrix-Aufbau: PV-Prognose laden …")
    forecast_pv = pv_forecast.get_hourly_pv_forecast_for_hours(target_hours)
    logger.info("Matrix-Aufbau: Optimierungsmatrix zusammenstellen …")
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

    flex_horizon_sums = {
        cid: round(sum(values), 2)
        for cid, values in flex_profiles.items()
        if round(sum(values), 2) > 0.0
    }
    if flex_horizon_sums:
        logger.info(
            "Flex-Profile im Planungshorizont (kWh): %s",
            ", ".join(f"{cid}={kwh}" for cid, kwh in sorted(flex_horizon_sums.items())),
        )
    else:
        logger.warning(
            "Flex-Profile im Planungshorizont sind leer — SoC BL Ziel kann zu hoch sein."
        )

    mirrored_share = market_prices.mirrored_price_share(
        [
            {
                "price_source": row.get("price_source"),
            }
            for row in optimization_matrix
        ]
    )
    extrapolated_share = sum(
        1 for row in optimization_matrix if is_extrapolated_source(row.get("price_source"))
    ) / len(optimization_matrix)
    if extrapolated_share > 0.2:
        print(
            f"[WARN] Preis-Extrapolation: {extrapolated_share:.0%} der {len(optimization_matrix)} "
            "Planungs-Slots ohne Day-Ahead-Preis "
            f"(gespiegelt: {mirrored_share:.0%})."
        )

    return optimization_matrix


def get_forecast_vectors(market_data) -> Tuple[List[float], List[float], List[dict]]:
    """
    Lädt das passende historische Verbrauchsprofil und die PV-Prognose 
    für die NÄCHSTEN 24 STUNDEN (rollierender Horizont ab der aktuellen Stunde).
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
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
def get_historical_day_data(target_date) -> Tuple[List[float], dict, List[float]]:
    """
    Extrahiert für ein bestimmtes Datum die 24-stündige Grundlast, die Tages-Summen
    der steuerbaren Verbraucher sowie den geloggten Gesamtverbrauch (kW pro Stunde).
    """
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()
        
    df = _load_profile_source_dataframe()
    if df is None or df.empty:
        print(
            f"[WARN] Keine historischen Daten in cons_data_hourly für das Datum {target_date}."
        )
        empty_totals = {c["id"]: 0.0 for c in config.get_flexible_consumers()}
        return [0.5] * 24, empty_totals, [0.5] * 24

    df_day = df[df.index.date == target_date]
    full_day_range = pd.date_range(
        start=f"{target_date} 00:00:00",
        end=f"{target_date} 23:00:00",
        freq='1h',
    )
    df_day = df_day.reindex(full_day_range, fill_value=0.0)

    historical_totals = {
        consumer["id"]: round(float(df_day[consumer["name"]].sum()), 3)
        if consumer["name"] in df_day.columns
        else 0.0
        for consumer in config.get_flexible_consumers()
    }
    actual_baseload = df_day['BaseLoad'].round(3).tolist()
    actual_total = df_day['Total'].round(3).tolist()

    return actual_baseload, historical_totals, actual_total


def get_cons_data_date_bounds() -> Tuple[Optional[date], Optional[date]]:
    """Frühestes und spätestes Datum in cons_data_hourly.csv."""
    ts_min, ts_max = cons_data_store.get_date_bounds()
    if ts_min is None or ts_max is None:
        return None, None
    return ts_min.date(), ts_max.date()


def get_historical_date_picker_bounds(months_back: int = 12) -> Tuple[date, date]:
    """Wählbarer Datumsbereich: Schnittmenge aus cons_data_hourly und den letzten N Monaten."""
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


def _reindex_hourly_series(series: pd.Series, target_date: date) -> List[float]:
    """Filtert eine stündliche Serie auf einen Tag und liefert exakt 24 Werte (00–23 Uhr)."""
    full_day_range = pd.date_range(
        start=f"{target_date} 00:00:00",
        end=f"{target_date} 23:00:00",
        freq='1h',
    )
    if series.empty:
        return [0.0] * 24

    day_series = series[series.index.date == target_date]
    day_series = day_series.reindex(full_day_range, fill_value=0.0)
    return day_series.round(3).tolist()


def _get_historical_pv_for_day(target_date: date) -> List[float]:
    """Liest den PV-Ertrag eines Tages aus cons_data_hourly.csv."""
    return _reindex_hourly_series(load_cons_data_pv_series(), target_date)


def _import_pricing_kwargs() -> dict:
    from data.backtesting_prices import pricing_kwargs_from_resolved

    return pricing_kwargs_from_resolved(
        config.get_resolved_runtime_settings(),
    )


def _get_historical_epex_and_brutto_prices_for_day(target_date: date) -> tuple[list[float], list[float]]:
    """Lädt EPEX- und Brutto-Bezugspreise (Cent/kWh) für 24 Stunden eines Tages."""
    sim_cfg = config.get_scenario_explorer_conf()
    start = pd.Timestamp(target_date)
    end = start

    df_prices = data_loader.load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get('AWATTAR_URL'),
        timeout=config.get_global_timeout(),
    )

    full_day_range = pd.date_range(
        start=f"{target_date} 00:00:00",
        end=f"{target_date} 23:00:00",
        freq='1h',
    )
    slot_datetimes = [ts.to_pydatetime() for ts in full_day_range]
    epex_prices = market_prices.epex_prices_for_slots(df_prices, slot_datetimes)
    from data.backtesting_prices import import_brutto_cent_for_slots

    brutto_prices = import_brutto_cent_for_slots(
        [float(p) for p in epex_prices],
        slot_datetimes,
        **_import_pricing_kwargs(),
    )
    return epex_prices, brutto_prices


def _get_historical_brutto_prices_for_day(target_date: date) -> List[float]:
    """Lädt die historischen Börsenpreise für einen Tag und rechnet sie in Brutto-Cent/kWh um."""
    _, brutto_prices = _get_historical_epex_and_brutto_prices_for_day(target_date)
    return brutto_prices


def build_historical_optimization_matrix(target_date) -> Tuple[List[dict], dict]:
    """
    Baut eine 24-Stunden-Optimierungsmatrix aus cons_data_hourly und historischen Preisen.
    """
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    baseload, historical_totals, total_load = get_historical_day_data(target_date)
    pv_profile = _get_historical_pv_for_day(target_date)
    epex_prices, brutto_prices = _get_historical_epex_and_brutto_prices_for_day(target_date)

    matrix = []
    for hour in range(24):
        slot_dt = datetime.combine(target_date, time(hour=hour))
        matrix.append({
            "hour": hour,
            "date": target_date,
            "slot_datetime": slot_dt,
            "k_act": brutto_prices[hour],
            "price_buy": epex_prices[hour],
            "expected_p_act": baseload[hour],
            "expected_p_total": total_load[hour],
            "expected_p_pv": pv_profile[hour],
            "consumption_mode": "logged_day",
        })

    feed_in_prices.enrich_matrix_feed_in_prices(matrix, config.get_feed_in_settings())

    meta = {
        'target_date': target_date,
        'historical_totals': historical_totals,
        'baseload_kwh': round(sum(baseload), 3),
        'total_kwh': round(sum(total_load), 3),
        'pv_kwh': round(sum(pv_profile), 3),
    }
    from . import consumer_targets

    meta['consumer_daily_targets_kwh'] = consumer_targets.resolve_historical_consumer_daily_targets(
        target_date
    )
    return matrix, meta