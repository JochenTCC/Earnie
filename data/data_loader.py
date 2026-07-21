# data_loader.py
import logging
import pandas as pd
import requests

logger = logging.getLogger(__name__)

ENERGY_CHARTS_PRICE_URL = "https://api.energy-charts.info/price"
DEFAULT_ENERGY_CHARTS_BZN = "DE-LU"
AWATTAR_DE_URL = "https://api.awattar.de/v1/marketdata"
MARKET_ZONE_AT = "AT"
MARKET_ZONE_DE = "DE-LU"
MARKET_ZONE_CH = "CH"
VALID_MARKET_ZONES = frozenset({MARKET_ZONE_AT, MARKET_ZONE_DE, MARKET_ZONE_CH})


def _monday_of_week(ts: pd.Timestamp) -> pd.Timestamp:
    """Montag der Kalenderwoche, die ts enthält (ISO: Montag = Wochenstart)."""
    return ts.normalize() - pd.Timedelta(days=int(ts.dayofweek))


_SIMULATION_MONTHS = 12


def last_complete_month_end(data_max: pd.Timestamp) -> pd.Timestamp:
    """Last day of the most recent complete calendar month on or before data_max."""
    data_max = pd.Timestamp(data_max).normalize()
    month_end = data_max + pd.offsets.MonthEnd(0)
    if data_max == month_end.normalize():
        return data_max
    return (data_max - pd.offsets.MonthBegin(1) - pd.Timedelta(days=1)).normalize()


def resolve_simulation_window(
    range_mode: str = "last_12_months",
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Overall SE/backtesting span from cons_data bounds (month-aligned).

    End = last day of the most recent complete calendar month in cons_data.
    Start = first day of the month 11 months earlier (12 inclusive months),
    clipped to cons_data min. Day iteration stays chronological (oldest→newest).

    ``range_mode`` is kept for call-site compatibility; bounds always use cons_data
    (``loxone_logs`` is no longer a separate path-pair mode).
    """
    del range_mode  # API compat; bounds are always cons_data month-aligned
    from data.profile_manager import get_cons_data_date_bounds

    data_min, data_max = get_cons_data_date_bounds()
    if data_min is None or data_max is None:
        raise ValueError(
            "Kein Zeitraum für die Simulation: cons_data_hourly.csv fehlt oder ist leer."
        )

    end = last_complete_month_end(pd.Timestamp(data_max))
    start = (end.to_period("M") - (_SIMULATION_MONTHS - 1)).to_timestamp().normalize()
    start = max(start, pd.Timestamp(data_min).normalize())
    if start > end:
        raise ValueError(
            "Kein gültiger Simulationszeitraum: cons_data deckt keinen "
            "vollständigen Kalendermonat ab."
        )
    return start, end


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
    *,
    market_zone: str | None = None,
) -> pd.DataFrame:
    """Lädt Marktpreise per API oder aus einer CSV-Datei."""
    source = sim_cfg.get('price_source', 'csv')
    zone = market_zone or sim_cfg.get('energy_charts_bzn', DEFAULT_ENERGY_CHARTS_BZN)

    if source == 'api':
        if zone == MARKET_ZONE_AT:
            provider = sim_cfg.get('price_provider', 'energy_charts')
            if provider == 'awattar':
                df_prices = fetch_awattar_prices(start, end, awattar_url, timeout=timeout)
            else:
                try:
                    df_prices = fetch_energy_charts_prices(
                        start, end, bzn=MARKET_ZONE_AT, timeout=timeout
                    )
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    logger.warning(
                        "Energy-Charts AT failed (%s); falling back to aWATTar",
                        exc,
                    )
                    df_prices = fetch_awattar_prices(
                        start, end, awattar_url, timeout=timeout
                    )
        elif zone == MARKET_ZONE_DE:
            provider = sim_cfg.get('price_provider', 'energy_charts')
            if provider == 'awattar':
                df_prices = fetch_awattar_prices(
                    start, end, AWATTAR_DE_URL, timeout=timeout
                )
            else:
                df_prices = fetch_energy_charts_prices(
                    start, end, bzn=MARKET_ZONE_DE, timeout=timeout
                )
        elif zone == MARKET_ZONE_CH:
            df_prices = fetch_energy_charts_prices(
                start, end, bzn=MARKET_ZONE_CH, timeout=timeout
            )
        else:
            raise ValueError(
                f"Unbekannte Marktzone '{zone}'. Erlaubt: {', '.join(sorted(VALID_MARKET_ZONES))}."
            )
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


def load_market_prices_for_scenario(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    sim_cfg: dict,
    awattar_url: str,
    timeout: int = 30,
) -> pd.DataFrame:
    """Marktpreise passend zur Import-Tarif-Zone eines Backtesting-Szenarios."""
    zone = scenario_params.get("market_zone", DEFAULT_ENERGY_CHARTS_BZN)
    return load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url,
        timeout=timeout,
        market_zone=str(zone),
    )


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
