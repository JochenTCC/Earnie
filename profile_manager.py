# profile_manager.py
import os
import pandas as pd
from datetime import datetime, timedelta, date, time
from typing import List, Tuple, Optional
import loxone_client
import pv_forecast
import config
import data_loader


def _load_and_resample_csv(filepath: str, is_wp: bool = False, wp_power: float = 1.6) -> pd.Series:
    """Lädt eine Loxone-CSV, bereinigt sie und aggregiert sie robust über ein Minutenraster auf 1-Stunden-Mittelwerte."""
    if not filepath or not os.path.exists(filepath):
        return pd.Series(dtype=float)
        
    try:
        # Einlesen mit Berücksichtigung des deutschen Dezimaltrennzeichens (Komma)
        df = pd.read_csv(filepath, sep=';', decimal=',', header=0)
        
        # Falls die Datei keine Kopfzeile hat und 3 Spalten besitzt (alter loxone_client Standard):
        if df.shape[1] == 3 and not any("datum" in str(col).lower() or "uhrzeit" in str(col).lower() for col in df.columns):
            df = pd.read_csv(filepath, sep=';', decimal=',', names=['timestamp', 'label', 'value'], header=None)
        else:
            # Spalten passend umbenennen für eine einheitliche Verarbeitung
            if df.shape[1] == 2:
                df.columns = ['timestamp', 'value']
            elif df.shape[1] == 3:
                df.columns = ['timestamp', 'label', 'value']
                
        # Zeitstempel konvertieren (Loxone Standardformat bevorzugt testen)
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='%d.%m.%Y %H:%M', errors='coerce')
        if df['timestamp'].isna().all():
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            
        df.dropna(subset=['timestamp', 'value'], inplace=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df.dropna(subset=['value'], inplace=True)
        
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        
        # 1-Minuten-Raster zur feingranularen Überbrückung von Event-Lücken (Forward-Fill)
        s_minutely = df['value'].resample('1min').ffill()
        
        # Falls Wärmepumpe: Status (0/1) mit Nennleistung multiplizieren
        if is_wp:
            s_minutely = s_minutely * wp_power
            
        # Zurück auf Stunden-Mittelwerte (Stunden-Verbrauch/Lastäquivalent)
        return s_minutely.resample('1h').mean()
        
    except Exception as e:
        print(f"⚠️ Fehler beim Verarbeiten von {filepath}: {e}")
        return pd.Series(dtype=float)


def _load_consumer_series(consumer: dict) -> pd.Series:
    """Lädt die Zeitreihe eines flexiblen Verbrauchers gemäß signal_type."""
    is_binary = consumer.get("signal_type") == "binary"
    nominal = float(consumer.get("nominal_power_kw", 1.6))
    return _load_and_resample_csv(
        consumer.get("path_log", ""),
        is_wp=is_binary,
        wp_power=nominal,
    )


def _build_flexible_consumer_dataframe(s_total: pd.Series) -> pd.DataFrame:
    """Baut einen DataFrame mit Gesamtlast und allen flexiblen Verbrauchern."""
    df = pd.DataFrame({"Total": s_total})
    for consumer in config.get_flexible_consumers():
        series = _load_consumer_series(consumer)
        df[consumer["name"]] = series if not series.empty else 0.0
        df[consumer["name"]] = df[consumer["name"]].fillna(0.0)
    return df


def _compute_baseload(df: pd.DataFrame) -> pd.DataFrame:
    """Subtrahiert alle flexiblen Verbraucher von der Gesamtlast."""
    flex_cols = [c["name"] for c in config.get_flexible_consumers()]
    if flex_cols:
        df["BaseLoad"] = df["Total"] - df[flex_cols].sum(axis=1)
    else:
        df["BaseLoad"] = df["Total"]
    df["BaseLoad"] = df["BaseLoad"].clip(lower=0.0)
    return df


def generate_consumption_profile() -> bool:
    """Lädt alle Logs, isoliert die nackte Grundlast und berechnet das Profil neu."""
    path_total = config.get('PATH_CONSUMPTION_TOTAL', cast=str) or loxone_client.fetch_loxone_csv_file()

    if not path_total or not os.path.exists(path_total):
        print("⚠️ Profil-Update abgebrochen: Haupt-Logdatei für Gesamtverbrauch fehlt.")
        return False

    try:
        print("⏳ Verarbeite Verbrauchsdaten und isoliere die Haus-Grundlast...")
        
        s_total = _load_and_resample_csv(path_total)
        if s_total.empty:
            print("⚠️ Gesamtverbrauch-Zeitreihe konnte nicht geladen werden oder ist leer.")
            return False

        df = _build_flexible_consumer_dataframe(s_total)
        df = _compute_baseload(df)
        df['Month'] = df.index.month
        df['Weekday'] = df.index.weekday
        df['Hour'] = df.index.hour

        profile = df.groupby(['Month', 'Weekday', 'Hour'])['BaseLoad'].mean().reset_index()
        profile.rename(columns={'BaseLoad': 'Consumption'}, inplace=True)
        profile['Consumption'] = profile['Consumption'].round(3)
        profile.to_csv('consumption_profiles.csv', index=False, sep=';')

        total_profile = df.groupby(['Month', 'Weekday', 'Hour'])['Total'].mean().reset_index()
        total_profile.rename(columns={'Total': 'Consumption'}, inplace=True)
        total_profile['Consumption'] = total_profile['Consumption'].round(3)
        total_profile.to_csv('total_consumption_profiles.csv', index=False, sep=';')

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
            flex_profile.to_csv('flexible_consumer_profiles.csv', index=False, sep=';')

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
    profile_path = 'consumption_profiles.csv'
    should_update = False
    
    if not os.path.exists(profile_path):
        print("ℹ️ Kein Verbrauchsprofil gefunden. Initialisiere erste Berechnung...")
        should_update = True
    elif not os.path.exists('total_consumption_profiles.csv'):
        print("ℹ️ Gesamtverbrauchsprofil fehlt. Initialisiere Profil-Update...")
        should_update = True
    elif not os.path.exists('flexible_consumer_profiles.csv') and config.get_flexible_consumers():
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
    return _load_hourly_profile(target_hours, 'consumption_profiles.csv')


def _load_total_consumption_profile(target_hours: List) -> List[float]:
    """Lädt das Gesamtverbrauchs-Profil (Grundlast + flexible Verbraucher) für die Zielstunden."""
    return _load_hourly_profile(target_hours, 'total_consumption_profiles.csv')


def _build_optimization_matrix(
    market_data: list,
    forecast_consumption: list,
    forecast_pv: list,
    forecast_total_consumption: list | None = None,
    target_hours: list | None = None,
) -> list:
    """Erstellt die Optimierungs-Matrix mit Preis-, Verbrauchs- und PV-Daten."""
    optimization_matrix = []
    
    fix_aufschlag = config.get('FIX_AUFSCHLAG_CENT', cast=float)
    netzverlust = config.get('NETZVERLUST_FAKTOR', cast=float)
    mwst_faktor = config.get('MWST_AUSTRIA_FAKTOR', cast=float)

    for i, item in enumerate(market_data[:24]):    
        hour = item['hour']
        
        try:
            epex_price_cent = float(item['price_buy'])
            brutto_price_cent = (epex_price_cent * netzverlust + fix_aufschlag) * mwst_faktor
            brutto_price_cent = round(brutto_price_cent, 4)
        except (TypeError, ValueError) as e:
            print(f"🚨 Fehler bei Brutto-Berechnung für Stunde {hour}: {e}. Nutze Rohwert.")
            brutto_price_cent = item['price_buy']

        row = {
            "hour": hour,
            "date": target_hours[i].date() if target_hours else None,
            "slot_datetime": target_hours[i] if target_hours else None,
            "k_act": brutto_price_cent,
            "expected_p_act": forecast_consumption[i],
            "expected_p_pv": forecast_pv[i],
            "consumption_mode": "forecast",
        }
        if forecast_total_consumption is not None:
            row["expected_p_total"] = forecast_total_consumption[i]
        optimization_matrix.append(row)
    
    return optimization_matrix[:24]


def _load_flexible_consumer_hourly_profiles(target_hours: List) -> dict[str, List[float]]:
    """Lädt stündliche Profilwerte je flexiblem Verbraucher für die Zielstunden."""
    consumers = config.get_flexible_consumers()
    profiles = {consumer["id"]: [] for consumer in consumers}
    profile_path = 'flexible_consumer_profiles.csv'

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


def get_forecast_consumer_daily_targets(matrix: list) -> dict:
    """Legacy-Alias – nutzt resolve_consumer_daily_targets."""
    return resolve_consumer_daily_targets(matrix=matrix)


def _historical_totals_for_date(target_date: date, cache: dict) -> dict[str, float]:
    if target_date not in cache:
        _, totals, _ = get_historical_day_data(target_date)
        cache[target_date] = totals
    return cache[target_date]


def _resolve_single_consumer_daily_target_kwh(
    consumer: dict,
    target_date: date,
    matrix: list | None = None,
    historical_cache: dict | None = None,
) -> float:
    """
    Ermittelt das Tagesziel (kWh) für einen Verbraucher.
    Quelle: config | historical (Logs/Profile) | loxone (Live-IO, nur heute).
    """
    source = consumer.get("daily_target_source", "config")
    cid = consumer["id"]
    fallback = float(consumer["daily_target_kwh"])
    cache = historical_cache if historical_cache is not None else {}

    if source == "config":
        if consumer.get("charging_schedule", {}).get("enabled"):
            computed = config.Config.target_kwh_from_day_schedule(
                consumer, datetime.combine(target_date, time(12, 0))
            )
            if computed is not None:
                return computed
        return fallback

    if source == "historical":
        if matrix:
            day_rows = [row for row in matrix if row.get("date") == target_date]
            if day_rows and any(row.get("expected_flex_kw") for row in day_rows):
                return sum(
                    float((row.get("expected_flex_kw") or {}).get(cid, 0.0))
                    for row in day_rows
                )
        totals = _historical_totals_for_date(target_date, cache)
        if cid in totals:
            return float(totals[cid])
        return fallback

    if source == "loxone":
        loxone_name = consumer.get("loxone_target_kwh_name", "")
        today = datetime.now().date()
        if loxone_name and target_date == today:
            value = loxone_client.fetch_loxone_generic_value(loxone_name)
            if value is not None and value >= 0:
                return float(value)
        totals = _historical_totals_for_date(target_date, cache)
        if cid in totals:
            return float(totals[cid])
        return fallback

    return fallback


def resolve_historical_consumer_daily_targets(target_date: date) -> dict[str, float]:
    """Geloggte Tagesenergie je Verbraucher – nur für historische Simulation."""
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    _, totals, _ = get_historical_day_data(target_date)
    consumers = config.get_flexible_consumers(optimizer_only=True)
    return {c["id"]: float(totals.get(c["id"], 0.0)) for c in consumers}


def resolve_horizon_flex_targets_kwh(matrix: list) -> dict[str, float]:
    """
    Summiert expected_flex_kw über den gesamten Simulationshorizont (typ. 24h).
    Gleiche Basis wie die Baseline in der Echtzeit-Optimierung (flexible_consumer_profiles.csv).
    """
    consumers = config.get_flexible_consumers(optimizer_only=True)
    totals = {c["id"]: 0.0 for c in consumers}
    for row in matrix[:24]:
        flex = row.get("expected_flex_kw") or {}
        for consumer in consumers:
            cid = consumer["id"]
            totals[cid] += float(flex.get(cid, 0.0) or 0.0)
    return {cid: round(kwh, 3) for cid, kwh in totals.items()}


def resolve_consumer_daily_targets(
    matrix: list | None = None,
    target_date: date | None = None,
    prefer_logged_totals: bool = False,
) -> dict:
    """
    Liefert Tagesziele pro Verbraucher gemäß daily_target_source in config.json.
    Bei prefer_logged_totals=True (Historischer Tag): ausschließlich geloggte Tages-Summen.
    Bei mehrtägigem Horizont: {date: {consumer_id: kwh}}, sonst {consumer_id: kwh}.
    """
    if prefer_logged_totals:
        day = target_date
        if matrix and not day:
            dates = {row["date"] for row in matrix if row.get("date") is not None}
            if len(dates) == 1:
                day = next(iter(dates))
        if day is None:
            raise ValueError("Historische Tagesziele benötigen ein gültiges Datum.")
        return resolve_historical_consumer_daily_targets(day)

    consumers = config.get_flexible_consumers(optimizer_only=True)
    historical_cache: dict = {}

    if matrix:
        dates = sorted({row["date"] for row in matrix if row.get("date") is not None})
        if len(dates) > 1:
            return {
                day: {
                    c["id"]: _resolve_single_consumer_daily_target_kwh(
                        c, day, matrix, historical_cache
                    )
                    for c in consumers
                }
                for day in dates
            }
        day = dates[0] if dates else (target_date or datetime.now().date())
        return {
            c["id"]: _resolve_single_consumer_daily_target_kwh(
                c, day, matrix, historical_cache
            )
            for c in consumers
        }

    day = target_date or datetime.now().date()
    return {
        c["id"]: _resolve_single_consumer_daily_target_kwh(
            c, day, None, historical_cache
        )
        for c in consumers
    }


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
        
    path_total = config.get('PATH_CONSUMPTION_TOTAL', cast=str) or loxone_client.fetch_loxone_csv_file()
    s_total = _load_and_resample_csv(path_total)

    if s_total.empty:
        print(f"⚠️ Keine historischen Daten vorhanden für das Datum {target_date}.")
        empty_totals = {c["id"]: 0.0 for c in config.get_flexible_consumers()}
        return [0.5] * 24, empty_totals, [0.5] * 24

    df = _build_flexible_consumer_dataframe(s_total)
    df = _compute_baseload(df)

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


def get_loxone_date_bounds() -> Tuple[Optional[date], Optional[date]]:
    """Gibt das früheste und späteste Datum aus den Loxone-Verbrauchslogs zurück."""
    path_total = config.get('PATH_CONSUMPTION_TOTAL', cast=str)
    if not path_total or not os.path.exists(path_total):
        return None, None

    s_total = _load_and_resample_csv(path_total)
    if s_total.empty:
        return None, None

    return s_total.index.min().date(), s_total.index.max().date()


def get_historical_date_picker_bounds(months_back: int = 12) -> Tuple[date, date]:
    """Ermittelt den wählbaren Datumsbereich: Schnittmenge aus Loxone-Logs und den letzten N Monaten."""
    today = datetime.now().date()
    rolling_min = today - timedelta(days=months_back * 30)

    lox_min, lox_max = get_loxone_date_bounds()
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
    """Liest den realen PV-Ertrag eines Tages aus den Loxone-Produktionslogs."""
    path_prod = config.get('PATH_PRODUCTION', cast=str)
    s_pv = _load_and_resample_csv(path_prod)
    return _reindex_hourly_series(s_pv, target_date)


def _brutto_price_cent(epex_cent: float) -> float:
    fix_aufschlag = config.get('FIX_AUFSCHLAG_CENT', cast=float)
    netzverlust = config.get('NETZVERLUST_FAKTOR', cast=float)
    mwst_faktor = config.get('MWST_AUSTRIA_FAKTOR', cast=float)
    return round((epex_cent * netzverlust + fix_aufschlag) * mwst_faktor, 4)


def _get_historical_brutto_prices_for_day(target_date: date) -> List[float]:
    """Lädt die historischen Börsenpreise für einen Tag und rechnet sie in Brutto-Cent/kWh um."""
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
    hourly_prices = df_prices['price_cent_kwh'].resample('h').mean()
    hourly_prices = hourly_prices.reindex(full_day_range).ffill().bfill().fillna(0.0)
    return [_brutto_price_cent(float(p)) for p in hourly_prices.tolist()]


def build_historical_optimization_matrix(target_date) -> Tuple[List[dict], dict]:
    """
    Baut eine 24-Stunden-Optimierungsmatrix aus realen Loxone-Daten und historischen Preisen.
    """
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    baseload, historical_totals, total_load = get_historical_day_data(target_date)
    pv_profile = _get_historical_pv_for_day(target_date)
    brutto_prices = _get_historical_brutto_prices_for_day(target_date)

    matrix = []
    for hour in range(24):
        slot_dt = datetime.combine(target_date, time(hour=hour))
        matrix.append({
            "hour": hour,
            "date": target_date,
            "slot_datetime": slot_dt,
            "k_act": brutto_prices[hour],
            "expected_p_act": baseload[hour],
            "expected_p_total": total_load[hour],
            "expected_p_pv": pv_profile[hour],
            "consumption_mode": "logged_day",
        })

    meta = {
        'target_date': target_date,
        'historical_totals': historical_totals,
        'baseload_kwh': round(sum(baseload), 3),
        'total_kwh': round(sum(total_load), 3),
        'pv_kwh': round(sum(pv_profile), 3),
    }
    meta['consumer_daily_targets_kwh'] = resolve_historical_consumer_daily_targets(target_date)
    return matrix, meta