# simulation_engine.py
import pandas as pd
import config
from optimizer import simulate_horizon, _calculate_step_cost_euro_from_row


def _scenario_to_battery_params(scenario_params: dict) -> dict:
    """Übersetzt JSON-Szenario-Parameter in das Format des Optimizers."""
    return {
        'battery_capacity_kwh': float(scenario_params['battery_capacity_kwh']),
        'min_soc': float(scenario_params['battery_min_soc']),
        'max_soc': float(scenario_params['battery_max_soc']),
        'max_power_kw': float(scenario_params['battery_max_power_kw']),
        'efficiency': float(scenario_params['battery_efficiency']),
    }


def _brutto_price_cent(epex_cent: float, awattar_cfg: dict) -> float:
    """Berechnet den Verbraucherpreis analog zu profile_manager.py."""
    base_price = epex_cent * awattar_cfg.get('netzverlust_faktor', 1.0)
    return (base_price + awattar_cfg['fix_aufschlag_cent']) * awattar_cfg['mwst_austria_faktor']


def _build_hourly_optimization_matrix(df: pd.DataFrame, awattar_cfg: dict) -> list[dict]:
    """Aggregiert 10-Minuten-Daten auf Stunden und baut die Optimizer-Matrix."""
    hourly = df.resample('h').agg({
        'pv': 'mean',
        'load': 'mean',
        'price_cent_kwh': 'mean',
    }).dropna(subset=['price_cent_kwh'])

    matrix = []
    for ts, row in hourly.iterrows():
        matrix.append({
            'hour': ts.hour,
            'k_act': _brutto_price_cent(row['price_cent_kwh'], awattar_cfg),
            'expected_p_pv': row['pv'],
            'expected_p_act': row['load'],
        })

    return matrix, hourly.index


def run_simulation(
    df: pd.DataFrame,
    scenario_params: dict,
    initial_soc: float = 50.0,
    on_progress=None,
) -> pd.DataFrame:
    """Simuliert ein Szenario mit der MILP-Optimierung aus optimizer.py."""
    awattar_cfg = config.CONFIG._raw_config['awattar']
    battery_params = _scenario_to_battery_params(scenario_params)
    k_push = float(scenario_params['k_push_cent'])

    matrix, timestamps = _build_hourly_optimization_matrix(df, awattar_cfg)
    chart_rows = simulate_horizon(
        matrix,
        initial_soc,
        battery_params=battery_params,
        k_push=k_push,
        verbose=False,
        on_progress=on_progress,
    )

    df_res = pd.DataFrame({
        'sim_cost': [_calculate_step_cost_euro_from_row(row, k_push) for row in chart_rows],
        'sim_soc': [row['Simulierter SoC (%)'] for row in chart_rows],
        'batt_action_kw': [row['Geplante Batterie-Aktion (kW)'] for row in chart_rows],
        'steuerbefehl': [row['Steuerbefehl'] for row in chart_rows],
    }, index=timestamps)
    df_res.index.name = 'ts'

    return df_res
