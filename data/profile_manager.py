# profile_manager.py
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
from runtime_store.persist_paths import (
    consumption_profiles_file,
    flexible_consumer_profiles_file,
    total_consumption_profiles_file,
)


def _cons_data_to_profile_dataframe(cons_df: pd.DataFrame) -> pd.DataFrame:
    """Wandelt cons_data_hourly in das interne Profil-Format (Total, BaseLoad, Verbraucher-Namen)."""
    df = pd.DataFrame(index=cons_df.index)
    df["Total"] = cons_df["total_kw"]
    df["BaseLoad"] = cons_df["baseload_kw"]
    for consumer in config.get_flexible_consumers():
        col = f"{consumer['id']}_kw"
        df[consumer["name"]] = cons_df[col] if col in cons_df.columns else 0.0
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


def generate_consumption_profile() -> bool:
    """Berechnet Verbrauchsprofile aus cons_data_hourly.csv."""
    try:
        print("⏳ Verarbeite Verbrauchsdaten und isoliere die Haus-Grundlast...")
        df = _load_profile_source_dataframe()
        if df is None or df.empty:
            path = cons_data_store.get_output_path()
            print(
                f"⚠️ Profil-Update abgebrochen: '{path}' fehlt oder ist leer. "
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

        flex_cols = [c["id"] for c in config.get_flexible_consumers()]
        if flex_cols:
            flex_profile = df.groupby(['Month', 'Weekday', 'Hour'])[
                [c["name"] for c in config.get_flexible_consumers()]
            ].mean().reset_index()
            rename_map = {
                consumer["name"]: consumer["id"]
                for consumer in config.get_flexible_consumers()
            }
            flex_profile.rename(columns=rename_map, inplace=True)
            for cid in flex_cols:
                flex_profile[cid] = flex_profile[cid].round(3)
            flex_profile.to_csv(flexible_consumer_profiles_file(), index=False, sep=';')

        print(
            "✅ 'consumption_profiles.csv', 'total_consumption_profiles.csv' "
            "und ggf. 'flexible_consumer_profiles.csv' erfolgreich neu berechnet!"
        )
        return True
    except Exception as e:
        print(f"🚨 Fehler bei der Profilberechnung: {e}")
        return False


def check_and_update_profile_if_new_month() -> None:
    """Überprüft, ob ein neuer Monat begonnen hat, und triggert ggf. das Profil-Update."""
    profile_path = consumption_profiles_file()
    should_update = False
    
    if not os.path.exists(profile_path):
        print("ℹ️ Kein Verbrauchsprofil gefunden. Initialisiere erste Berechnung...")
        should_update = True
    elif not os.path.exists(total_consumption_profiles_file()):
        print("ℹ️ Gesamtverbrauchsprofil fehlt. Initialisiere Profil-Update...")
        should_update = True
    elif not os.path.exists(flexible_consumer_profiles_file()) and config.get_flexible_consumers():
        print("ℹ️ Flexible-Verbraucherprofil fehlt. Initialisiere Profil-Update...")
        should_update = True
    else:
        file_time = os.path.getmtime(profile_path)
        file_date = datetime.fromtimestamp(file_time)
        current_date = datetime.now()
        
        if file_date.month != current_date.month or file_date.year != current_date.year:
            print(f"ℹ️ Neuer Monat erkannt (Letztes Profil von: {file_date.strftime('%d.%m.%Y')}).")
            should_update = True
            
    if should_update:
        generate_consumption_profile()


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
        print(f"🚨 Fehler beim Verarbeiten von '{profile_path}': {e}. Nutze statische Defaults.")
        return [global_hour_defaults[dt.hour] for dt in target_hours]


def _load_consumption_profile(target_hours: List) -> List[float]:
    """Lädt das Grundlast-Profil für die Zielstunden."""
    return _load_hourly_profile(target_hours, consumption_profiles_file())


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
    if target_hours is None or len(target_hours) != 24:
        raise ValueError(
            "_build_optimization_matrix erfordert genau 24 target_hours für das Live-Fenster."
        )

    price_slots = market_prices.resolve_24h_market_slots(market_data, target_hours)
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
    consumers = config.get_flexible_consumers()
    profiles = {consumer["id"]: [] for consumer in consumers}
    profile_path = flexible_consumer_profiles_file()

    if not os.path.exists(profile_path):
        return {cid: [0.0] * len(target_hours) for cid in profiles}

    try:
        df_profiles = pd.read_csv(profile_path, sep=';')
        consumer_ids = [c["id"] for c in consumers if c["id"] in df_profiles.columns]
        lookup = {
            cid: df_profiles.set_index(['Month', 'Weekday', 'Hour'])[cid].to_dict()
            for cid in consumer_ids
        }
        hour_fallback = {
            cid: df_profiles.groupby('Hour')[cid].mean().to_dict()
            for cid in consumer_ids
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
        print(f"🚨 Fehler beim Laden von '{profile_path}': {e}. Nutze Null-Profile.")
        return {cid: [0.0] * len(target_hours) for cid in profiles}

    return profiles


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
            f"⚠️ Keine historischen Daten in cons_data_hourly für das Datum {target_date}."
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


def _brutto_price_cent(epex_cent: float) -> float:
    fix_aufschlag = config.get('FIX_AUFSCHLAG_CENT', cast=float)
    netzverlust = config.get('NETZVERLUST_FAKTOR', cast=float)
    mwst_faktor = config.get('MWST_AUSTRIA_FAKTOR', cast=float)
    return round((epex_cent * netzverlust + fix_aufschlag) * mwst_faktor, 4)


def _get_historical_epex_and_brutto_prices_for_day(target_date: date) -> tuple[list[float], list[float]]:
    """Lädt EPEX- und Brutto-Bezugspreise (Cent/kWh) für 24 Stunden eines Tages."""
    sim_cfg = config.get_file_paths_battery_simulation()
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
    brutto_prices = [_brutto_price_cent(float(p)) for p in epex_prices]
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