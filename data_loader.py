# data_loader.py
import os

import pandas as pd
import requests

ENERGY_CHARTS_PRICE_URL = "https://api.energy-charts.info/price"
DEFAULT_ENERGY_CHARTS_BZN = "DE-LU"


def _ensure_csv_exists(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV-Datei nicht gefunden: {path}")


def _load_and_merge_loxone_data(cons_path, prod_path):
    """
    Lädt die historischen Loxone-Verbrauchs- und Produktionsdaten
    und führt sie über den Zeitstempel zusammen.
    """
    _ensure_csv_exists(cons_path)
    _ensure_csv_exists(prod_path)

    df_cons = pd.read_csv(cons_path, sep=';', decimal=',', parse_dates=['Datum/Uhrzeit'], dayfirst=True)
    df_prod = pd.read_csv(prod_path, sep=';', decimal=',', parse_dates=['Datum/Uhrzeit'], dayfirst=True)

    df_cons.rename(columns={'Leistung Verbrauch [kW]': 'load', 'Datum/Uhrzeit': 'ts'}, inplace=True)
    df_prod.rename(columns={'Leistung Produktion [kW]': 'pv', 'Datum/Uhrzeit': 'ts'}, inplace=True)

    return pd.merge(df_cons, df_prod, on='ts')


def get_loxone_time_bounds(cons_path: str, prod_path: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Gibt den minimalen und maximalen Zeitstempel der Loxone-Logs zurück."""
    df = _load_and_merge_loxone_data(cons_path, prod_path)
    return df['ts'].min(), df['ts'].max()


def resolve_simulation_window(
    range_mode: str,
    cons_path: str,
    prod_path: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Ermittelt das Simulationsfenster.

    - last_12_months: rollierende 12 Monate bis heute
    - loxone_logs: letzte 12 Monate innerhalb des Loxone-Log-Zeitraums
    """
    today = pd.Timestamp.now().normalize()

    if range_mode == "loxone_logs":
        lox_start, lox_end = get_loxone_time_bounds(cons_path, prod_path)
        end = min(lox_end.normalize(), today)
        start = max(lox_start.normalize(), end - pd.DateOffset(months=12))
    else:
        end = today
        start = end - pd.DateOffset(months=12)

    return start, end


def create_averaged_profile(cons_path, prod_path, before: pd.Timestamp):
    """
    Erstellt ein gemitteltes Last- und Erzeugungsprofil aus Loxone-Daten
    vor dem Simulationsfenster, gruppiert nach Monat, Tag, Stunde und Minute.
    """
    df = _load_and_merge_loxone_data(cons_path, prod_path)
    df = df[df['ts'] < before].copy()

    df['month'] = df['ts'].dt.month
    df['day'] = df['ts'].dt.day
    df['hour'] = df['ts'].dt.hour
    df['minute'] = df['ts'].dt.minute

    group_cols = ['month', 'day', 'hour', 'minute']
    return df.groupby(group_cols)[['load', 'pv']].mean().reset_index()


def _prices_to_dataframe(timestamps: pd.Series, prices_eur_mwh: pd.Series) -> pd.DataFrame:
    """Wandelt API-Rohdaten in ein einheitliches Preis-DataFrame um."""
    df_prices = pd.DataFrame({
        'ts_price': timestamps,
        'price_cent_kwh': pd.to_numeric(prices_eur_mwh, errors='coerce') * 0.1,
    }).dropna()

    df_prices['ts_price'] = (
        pd.to_datetime(df_prices['ts_price'], utc=True)
        .dt.tz_convert('Europe/Vienna')
        .dt.tz_localize(None)
    )
    return df_prices.groupby('ts_price')['price_cent_kwh'].mean().dropna().to_frame()


def fetch_awattar_prices(start: pd.Timestamp, end: pd.Timestamp, awattar_url: str, timeout: int = 30) -> pd.DataFrame:
    """Lädt Day-Ahead-Preise (AT) von der aWATTar-API für einen Zeitraum."""
    start_ms = int(start.tz_localize('Europe/Vienna').timestamp() * 1000)
    end_ms = int((end + pd.Timedelta(days=1)).tz_localize('Europe/Vienna').timestamp() * 1000)

    response = requests.get(
        awattar_url,
        params={'start': start_ms, 'end': end_ms},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    if 'data' not in payload or not payload['data']:
        raise ValueError("aWATTar-API lieferte keine Preisdaten für den angefragten Zeitraum.")

    rows = []
    for entry in payload['data']:
        if 'start_timestamp' not in entry or 'marketprice' not in entry:
            continue
        rows.append({
            'ts_price': pd.to_datetime(entry['start_timestamp'], unit='ms', utc=True),
            'price_cent_kwh': entry['marketprice'] / 10.0,
        })

    df_prices = pd.DataFrame(rows)
    df_prices['ts_price'] = df_prices['ts_price'].dt.tz_convert('Europe/Vienna').dt.tz_localize(None)
    return df_prices.groupby('ts_price')['price_cent_kwh'].mean().dropna().to_frame()


def fetch_energy_charts_prices(
    start: pd.Timestamp,
    end: pd.Timestamp,
    bzn: str = DEFAULT_ENERGY_CHARTS_BZN,
    timeout: int = 30,
) -> pd.DataFrame:
    """Lädt Day-Ahead-Preise (DE-LU o.ä.) von der Energy-Charts-API."""
    response = requests.get(
        ENERGY_CHARTS_PRICE_URL,
        params={
            'bzn': bzn,
            'start': start.strftime('%Y-%m-%d'),
            'end': end.strftime('%Y-%m-%d'),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    if 'unix_seconds' not in payload or not payload['unix_seconds']:
        raise ValueError("Energy-Charts-API lieferte keine Preisdaten für den angefragten Zeitraum.")

    timestamps = pd.to_datetime(payload['unix_seconds'], unit='s', utc=True)
    return _prices_to_dataframe(timestamps, pd.Series(payload['price']))


def _prepare_energy_charts_prices(price_csv_path: str) -> pd.DataFrame:
    """Lädt Preise aus einer Energy-Charts-CSV-Datei."""
    _ensure_csv_exists(price_csv_path)

    df_prices = pd.read_csv(price_csv_path, sep=',', skiprows=[1])
    price_col = 'Day Ahead Auktion (DE-LU)'

    df_prices['ts_price'] = pd.to_datetime(df_prices['Datum (MEZ)'], utc=True)
    df_prices['ts_price'] = df_prices['ts_price'].dt.tz_convert('Europe/Vienna').dt.tz_localize(None)
    df_prices['price_cent_kwh'] = pd.to_numeric(df_prices[price_col], errors='coerce') * 0.1

    return df_prices.groupby('ts_price')['price_cent_kwh'].mean().dropna().to_frame()


def load_market_prices(
    start: pd.Timestamp,
    end: pd.Timestamp,
    sim_cfg: dict,
    awattar_url: str,
    timeout: int = 30,
) -> pd.DataFrame:
    """Lädt Marktpreise per API oder aus einer CSV-Datei."""
    source = sim_cfg.get('price_source', 'csv')

    if source == 'api':
        provider = sim_cfg.get('price_provider', 'awattar')
        if provider == 'awattar':
            df_prices = fetch_awattar_prices(start, end, awattar_url, timeout=timeout)
        else:
            bzn = sim_cfg.get('energy_charts_bzn', DEFAULT_ENERGY_CHARTS_BZN)
            df_prices = fetch_energy_charts_prices(start, end, bzn=bzn, timeout=timeout)
    else:
        path_price = sim_cfg.get('path_price')
        if not path_price:
            raise ValueError("price_source='csv' erfordert 'path_price' in der Konfiguration.")
        df_prices = _prepare_energy_charts_prices(path_price)

    mask = (df_prices.index >= start) & (df_prices.index < end + pd.Timedelta(days=1))
    df_prices = df_prices.loc[mask]
    if df_prices.empty:
        raise ValueError(f"Keine Preisdaten für {start.date()} bis {end.date()} gefunden.")
    return df_prices


def generate_simulation_base(
    profile: pd.DataFrame,
    prices: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """
    Projiziert das gemittelte historische Profil auf das Simulationsfenster
    und führt es mit den Marktpreisen zusammen.
    """
    target_end = end.normalize() + pd.Timedelta(hours=23, minutes=50)
    target_range = pd.date_range(start=start.normalize(), end=target_end, freq='10min')
    df = pd.DataFrame(index=target_range)
    df.index.name = 'ts'

    df['month'] = df.index.month
    df['day'] = df.index.day
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute

    df_sim = df.reset_index().merge(profile, on=['month', 'day', 'hour', 'minute'], how='left')
    df_sim.set_index('ts', inplace=True)

    df_sim['load'] = df_sim['load'].interpolate(method='time').fillna(0)
    df_sim['pv'] = df_sim['pv'].interpolate(method='time').fillna(0)

    df_prices_resampled = prices.resample('10min').ffill()
    df_final = df_sim.join(df_prices_resampled, how='left')
    df_final.drop(columns=['month', 'day', 'hour', 'minute'], inplace=True)

    return df_final.dropna(subset=['price_cent_kwh'])
