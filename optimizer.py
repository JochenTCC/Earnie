# optimizer.py
from typing import List, Dict, Any, Tuple
import pulp
import config  # Lokaler Import der Konfiguration


def _clamp_power(value: float, max_power: float) -> float:
    return max(-max_power, min(value, max_power))


def _apply_soc_change(old_soc: float, batt_action: float, battery_capacity_kwh: float, efficiency: float, min_soc_limit: float, max_soc_limit: float) -> tuple[float, float]:
    if batt_action >= 0:
        energy_change = batt_action * efficiency
    else:
        energy_change = batt_action / efficiency

    soc_change = (energy_change / battery_capacity_kwh) * 100
    new_soc = old_soc + soc_change

    if new_soc > max_soc_limit:
        new_soc = max_soc_limit
        actual_energy = ((max_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = actual_energy / efficiency if actual_energy >= 0 else actual_energy * efficiency
    elif new_soc < min_soc_limit:
        new_soc = min_soc_limit
        actual_energy = ((min_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = actual_energy * efficiency if actual_energy < 0 else actual_energy / efficiency

    return new_soc, batt_action


def heuristic_optimizer(
    matrix: List[Dict[str, Any]],
    current_hour: int,
    current_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
) -> Tuple[int, float, float]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Nutzt mathematische lineare Optimierung (MILP) über das PuLP-Framework.
    
    Modi (Ernie_Mode):
        0 = Automatik (Normalbetrieb / Batterieladung und -entladung freigegeben)
        1 = Zwangsladen (Laden aus dem Netz mit Ziel-Leistung)
        2 = Entladesperre (Batterieentladung blockiert, um Kapazität für teure Stunden zu sparen)
    """
    if not matrix:
        print("🚨 Optimizer-Fehler: Matrix ist leer.")
        return 0, 0.0, 99.0

    # 1. Parameter laden (Szenario-Override oder globale Config)
    battery_params = battery_params or config.get_battery_params()
    battery_capacity = battery_params['battery_capacity_kwh']
    min_soc = battery_params['min_soc']
    max_soc = battery_params['max_soc']
    max_power = battery_params['max_power_kw']
    efficiency = battery_params['efficiency']
    k_push = k_push if k_push is not None else config.get_push_price_cent()

    # Planungshorizont bestimmen (maximal 24 Stunden)
    N = min(24, len(matrix))

    # SoC-Grenzen von Prozent in absolute kWh umrechnen
    e_min = (min_soc / 100.0) * battery_capacity
    e_max = (max_soc / 100.0) * battery_capacity
    e_init = (current_soc / 100.0) * battery_capacity

    # 2. Lineares Optimierungsproblem erstellen
    prob = pulp.LpProblem("Energy_Cost_Minimization", pulp.LpMinimize)

    # 3. Entscheidungsvariablen definieren
    p_grid_buy = [pulp.LpVariable(f"p_grid_buy_{t}", lowBound=0) for t in range(N)]
    p_grid_sell = [pulp.LpVariable(f"p_grid_sell_{t}", lowBound=0) for t in range(N)]
    p_charge = [pulp.LpVariable(f"p_charge_{t}", lowBound=0, upBound=max_power) for t in range(N)]
    p_discharge = [pulp.LpVariable(f"p_discharge_{t}", lowBound=0, upBound=max_power) for t in range(N)]
    e_batt = [pulp.LpVariable(f"e_batt_{t}", lowBound=e_min, upBound=e_max) for t in range(N)]
    
    # Binäre Hilfsvariable: 1 = Akku lädt, 0 = Akku entlädt (verhindert Gleichzeitigkeit)
    delta_charge = [pulp.LpVariable(f"delta_charge_{t}", cat=pulp.LpBinary) for t in range(N)]

    # 4. Zielfunktion: Gesamtkosten über den Horizont minimieren
    prob += pulp.lpSum([
        p_grid_buy[t] * matrix[t]['k_act'] - p_grid_sell[t] * k_push
        for t in range(N)
    ])

    # 5. Mathematische Nebenbedingungen (Constraints) definieren
    for t in range(N):
        p_pv = matrix[t]['expected_p_pv']
        p_con = matrix[t]['expected_p_act']

        # KNOTENGLEICHUNG: Energieerhaltung des Hauses
        prob += (p_pv + p_grid_buy[t] + p_discharge[t] == p_con + p_grid_sell[t] + p_charge[t])

        # LEISTUNGSGRENZEN: Gekoppelt an die binäre Variable
        prob += (p_charge[t] <= max_power * delta_charge[t])
        prob += (p_discharge[t] <= max_power * (1 - delta_charge[t]))

        # BATTERIE-DYNAMIK: Energieinhalt der aktuellen Stunde unter Berücksichtigung des Wirkungsgrads
        if t == 0:
            prob += (e_batt[t] == e_init + p_charge[t] * efficiency - p_discharge[t] / efficiency)
        else:
            prob += (e_batt[t] == e_batt[t-1] + p_charge[t] * efficiency - p_discharge[t] / efficiency)

    # 6. Problem mathematisch lösen
    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[prob.status] != "Optimal":
        if verbose:
            print(f"⚠️ MILP-Solver konnte keine optimale Lösung finden Status: {pulp.LpStatus[prob.status]}. Fallback auf Automatik.")
        return 0, 0.0, 99.0

    # 7. Ergebnisse für die aktuelle Stunde (t=0) extrahieren
    opt_charge = p_charge[0].varValue if p_charge[0].varValue is not None else 0.0
    opt_discharge = p_discharge[0].varValue if p_discharge[0].varValue is not None else 0.0
    opt_grid_buy = p_grid_buy[0].varValue if p_grid_buy[0].varValue is not None else 0.0
    
    p_pv_0 = matrix[0]['expected_p_pv']
    p_con_0 = matrix[0]['expected_p_act']
    net_pv_surplus = p_pv_0 - p_con_0

    # 8. Übersetzung der kontinuierlichen Solver-Ergebnisse in Loxone-Modi
    mode = 0
    target_power = 0.0
    target_soc = 99.0

    if opt_charge > 0.05 and opt_grid_buy > 0.05:
        mode = 1
        target_power = round(opt_charge, 2)
        opt_end_soc = (e_batt[0].varValue / battery_capacity) * 100.0
        target_soc = round(max(current_soc, opt_end_soc), 1)
    elif net_pv_surplus < -0.05 and opt_discharge < 0.05 and current_soc > (min_soc + 2.0):
        mode = 2
        target_power = 0.0
        target_soc = 100.0
    else:
        mode = 0
        target_power = 0.0
        target_soc = 99.0

    if verbose:
        print(f"\n--- 🧮 MILP Optimierungs-Entscheidung für {current_hour}:00 Uhr ---")
        print(f"Aktueller Brutto-Preis: {matrix[0]['k_act']:.2f} Cent/kWh")
        print(f"Aktueller Akku-SoC    : {current_soc:.1f}%")
        print(f"Optimierter Fahrplan  : Ladung={opt_charge:.2f} kW | Entladung={opt_discharge:.2f} kW | Netzbezug={opt_grid_buy:.2f} kW")
        
        modi_text = {0: "AUTOMATIK", 1: "ZWANGSLADEN", 2: "ENTLADESPERRE"}
        print(f"-> Steuerbefehl Loxone: {modi_text[mode]} (Leistung: {target_power} kW, Ziel-SoC: {target_soc}%)")

    return mode, target_power, target_soc


def simulate_horizon(
    optimization_matrix: list,
    initial_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    on_progress=None,
) -> list:
    """
    Simuliert einen rollierenden Optimierungshorizont über die gesamte Matrix.
    """
    chart_rows = []
    sim_soc = initial_soc
    battery_params = battery_params or config.get_battery_params()
    total_steps = len(optimization_matrix)

    for i, row in enumerate(optimization_matrix):
        sim_soc, chart_row = _simulate_single_hour_optimizer(
            optimization_matrix[i:],
            row,
            sim_soc,
            battery_params,
            k_push=k_push,
            verbose=verbose,
        )
        chart_rows.append(chart_row)
        if on_progress is not None:
            on_progress(i + 1, total_steps)

    return chart_rows


def simulate_24h_horizon(optimization_matrix: list, initial_soc: float) -> list:
    """
    Simuliert den 24-Stunden-Verlauf des SoC unter exakter Berücksichtigung
    des neuen mathematischen Wirkungsgrads und der Leistungsbegrenzungen.
    """
    return simulate_horizon(optimization_matrix[:24], initial_soc)


def _simulate_single_hour_optimizer(
    remaining_matrix: list,
    row: dict,
    sim_soc: float,
    battery_params: dict,
    k_push: float | None = None,
    verbose: bool = True,
) -> Tuple[float, dict]:
    """Hilfsfunktion: Simuliert eine einzelne Stunde im optimierten Pfad (< 30 Zeilen)."""
    h = row['hour']
    mode, target_power, target_soc = heuristic_optimizer(
        remaining_matrix,
        h,
        sim_soc,
        battery_params=battery_params,
        k_push=k_push,
        verbose=verbose,
    )
    
    pv = row['expected_p_pv']
    con = row['expected_p_act']
    net_pv_surplus = pv - con
    
    # BEHOBEN: Kein künstliches Aufaddieren von Überschüssen beim Zwangsladen.
    # target_power entspricht bereits der mathematisch exakt gewollten Brutto-Ladeleistung.
    if mode == 1:
        batt_action = target_power
        action_text = f"Zwangsladen ({target_power} kW)"
    elif mode == 2:
        batt_action = max(0.0, net_pv_surplus)
        action_text = "Entladesperre aktiv"
    else:
        batt_action = net_pv_surplus
        action_text = "Automatikbetrieb"
        
    old_soc = sim_soc
    batt_action = _clamp_power(batt_action, battery_params['max_power_kw'])
    sim_soc, batt_action = _apply_soc_change(
        old_soc,
        batt_action,
        battery_params['battery_capacity_kwh'],
        battery_params['efficiency'],
        battery_params['min_soc'],
        battery_params['max_soc'],
    )
    
    chart_row = {
        "Uhrzeit": f"{h:02d}:00",
        "Strompreis (Cent/kWh)": row['k_act'],
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": action_text
    }
    return sim_soc, chart_row


def _calculate_step_cost_euro_from_row(row: dict, sell_price_cent: float) -> float:
    """Berechnet die Stromkosten einer einzelnen Simulationsstunde in Euro."""
    p_pv = row['PV-Prognose (kW)']
    p_con = row['Verbrauch-Prognose (kW)']
    batt_action = row['Geplante Batterie-Aktion (kW)']
    price_cent = row['Strompreis (Cent/kWh)']

    p_grid = p_con - p_pv + batt_action
    if p_grid >= 0:
        step_cents = p_grid * price_cent
    else:
        step_cents = p_grid * sell_price_cent

    return step_cents / 100.0


def _calculate_cost_euro_from_rows(rows: list, sell_price_cent: float) -> float:
    """Berechnet die Kosten in Euro für eine Stundenreihe aus einem Simulations-Output."""
    return sum(_calculate_step_cost_euro_from_row(row, sell_price_cent) for row in rows)


def simulate_baseline_horizon(optimization_matrix: list, initial_soc: float) -> list:
    """Simuliert den 24h-Verlauf ohne Optimierung: Batterie folgt nur dem aktuellen PV-Überschuss."""
    chart_rows = []
    sim_soc = initial_soc
    battery_params = config.get_battery_params()

    for row in optimization_matrix[:24]:
        sim_soc, chart_row = _simulate_single_hour_baseline(row, sim_soc, battery_params)
        chart_rows.append(chart_row)

    return chart_rows


def _simulate_single_hour_baseline(row: dict, sim_soc: float, battery_params: dict) -> Tuple[float, dict]:
    """Hilfsfunktion: Simuliert eine einzelne Stunde im Baseline-Pfad (< 30 Zeilen)."""
    h = row['hour']
    pv = row['expected_p_pv']
    con = row['expected_p_act']
    net_pv_surplus = pv - con

    batt_action = _clamp_power(net_pv_surplus, battery_params['max_power_kw'])
    old_soc = sim_soc
    sim_soc, batt_action = _apply_soc_change(
        old_soc,
        batt_action,
        battery_params['battery_capacity_kwh'],
        battery_params['efficiency'],
        battery_params['min_soc'],
        battery_params['max_soc'],
    )

    chart_row = {
        "Uhrzeit": f"{h:02d}:00",
        "Strompreis (Cent/kWh)": row['k_act'],
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": "Baseline"
    }
    return sim_soc, chart_row


def calculate_optimization_savings(optimization_matrix: list, initial_soc: float) -> dict:
    """Berechnet die Einsparung in Euro gegenüber einer nicht-optimierten Baseline-Simulation."""
    optimized_rows = simulate_24h_horizon(optimization_matrix, initial_soc)
    baseline_rows = simulate_baseline_horizon(optimization_matrix, initial_soc)
    sell_price_cent = config.get_push_price_cent()

    optimized_cost = _calculate_cost_euro_from_rows(optimized_rows, sell_price_cent)
    baseline_cost = _calculate_cost_euro_from_rows(baseline_rows, sell_price_cent)
    savings = baseline_cost - optimized_cost

    return {
        'baseline_cost_euro': round(baseline_cost, 4),
        'optimized_cost_euro': round(optimized_cost, 4),
        'savings_euro': round(savings, 4),
        'optimized_rows': optimized_rows,
        'baseline_rows': baseline_rows
    }