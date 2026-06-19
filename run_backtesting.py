# run_backtesting.py
import os

# Backtesting braucht keine Loxone-Zugangsdaten aus der .env
os.environ["ENERGY_OPTIMIZER_OFFLINE"] = "1"

import pandas as pd
import config
from data_loader import (
    create_averaged_profile,
    generate_simulation_base,
    load_market_prices,
    resolve_simulation_window,
)
from simulation_engine import run_simulation


def print_monthly_report(results):
    """Erstellt den monatlichen tabellarischen Vergleich im Terminal."""
    report_df = pd.DataFrame()

    for name, df in results.items():
        report_df[name] = df['sim_cost'].resample('ME').sum()

    report_df['Einsparung (EUR)'] = report_df['runtime_settings'] - report_df['scenario_settings']

    print("\n=== MONATLICHER SIMULATIONS-VERGLEICH ===")
    print(report_df.to_string(formatters={
        'runtime_settings': '{:,.2f} €'.format,
        'scenario_settings': '{:,.2f} €'.format,
        'Einsparung (EUR)': '{:,.2f} €'.format
    }))
    print("=======================================================")


def main():
    sim_cfg = config.CONFIG._raw_config["file_paths_battery_simulation"]
    range_mode = sim_cfg.get("price_range", "last_12_months")
    price_source = sim_cfg.get("price_source", "csv")

    start, end = resolve_simulation_window(
        range_mode,
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
    )

    print("Starte Profil-Generierung aus historischen Daten...")
    profile = create_averaged_profile(
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
        before=start,
    )

    if price_source == "api":
        provider = sim_cfg.get("price_provider", "awattar")
        print(f"Lade Börsenpreise per API ({provider}) für {start.date()} bis {end.date()}...")
    else:
        print(f"Lade Börsenpreise aus CSV für {start.date()} bis {end.date()}...")

    prices = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.CONFIG._raw_config["awattar"]["url"],
        timeout=config.CONFIG.get_global_timeout(default=30),
    )

    print("Erstelle Simulationsbasis...")
    df_sim_base = generate_simulation_base(profile, prices, start, end)

    covered_months = sorted(df_sim_base.index.month.unique())
    span_days = (df_sim_base.index.max() - df_sim_base.index.min()).days
    print(
        f"Simulationszeitraum: {df_sim_base.index.min().date()} bis {df_sim_base.index.max().date()} "
        f"({span_days} Tage, Monate: {covered_months})"
    )

    scenarios = {
        "runtime_settings": config.CONFIG._raw_config["runtime_settings"],
        "scenario_settings": config.CONFIG._raw_config["scenario_settings"],
    }

    sim_results = {}
    for name, params in scenarios.items():
        print(f"Simuliere Szenario: '{name}'...")
        sim_results[name] = run_simulation(df_sim_base, params)

    print_monthly_report(sim_results)


if __name__ == "__main__":
    main()
