# PV & Batterie (Live-Szenario)

Diese Parameter beschreiben die physische Anlage und fließen in die MILP-Optimierung ein (Live und Simulation). Konfiguration über Entitäts-Referenzen im **Live-Szenario** (`backtesting_scenarios.json`, gewählt via `live_scenario_id` in `config.json`); technische Werte liegen in `earnie_env/config/components.json` (`batteries[]`, `pv_systems[]`).

Ein Szenario kann **mehrere PV-Anlagen** referenzieren (`pv_system_ids`). Die Prognose und die Optimierung nutzen die **Summe** aller Anlagen.

Im **Szenario-Explorer** (Verbrauchsdaten / cons_data) gilt für die PV-Linien:

- **Monatschart:** eine Serie pro **eindeutiger PV-Konfiguration** über alle Szenarien (Summe der Anlagen in dieser Konfiguration). Legende = mit „ + “ verbundene Bezeichnungen, z. B. „Dach Süd“ oder „Dach Nord + Dach Süd“.
- **Wochenchart:** eine Serie pro **eindeutiger PV-Anlage** plus zusätzlich die Mehrfach-Konfigurations-Summen wie im Monatschart (Einzelanlagen-Konfigurationen werden nicht doppelt gezeichnet).
- Farbe der PV-Linien: gelbliche Palette. Die historische Summe aus `cons_data` („PV Ist“) wird in diesen Charts **nicht** angezeigt.


| Parameter               | Einheit  | Quelle                               | Bedeutung                                                                                                                             |
| ----------------------- | -------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `pv_system_ids`         | —        | Szenario → `components.json`         | Eine oder mehrere Referenzen auf `pv_systems[].id`                                                                                    |
| `kwp`                   | kWp      | `components.json` → `pv_systems[]`   | Installierte PV-Leistung je Anlage; aufgelöst als Summe `pv_kwp`                                                                      |
| `pv_tilt`               | °        | `components.json` → `pv_systems[]`   | Dachneigung **je Anlage** (bei mehreren Anlagen keine einzelne Globalneigung)                                                         |
| `pv_azimuth`            | °        | `components.json` → `pv_systems[]`   | Ausrichtung je Anlage: `0` = Süd, `-90` = Ost, `90` = West                                                                            |
| `latitude`, `longitude` | °        | `house_profiles.json` (via Szenario) | Standort für PV-Prognose (Forecast.Solar / Open-Meteo)                                                                                |
| `k_push_cent`           | Cent/kWh | `tariffs.json` (Export-Tarif)        | **Einspeisevergütung**                                                                                                                |
| `battery_capacity_kwh`  | kWh      | `components.json` → `batteries[]`    | Nutzbare Speicherkapazität                                                                                                            |
| `battery_max_power_kw`  | kW       | `components.json` → `batteries[]`    | Max. Lade- und Entladeleistung                                                                                                        |
| `battery_efficiency`    | 0–1      | `components.json` → `batteries[]`    | Roundtrip-Wirkungsgrad (Laden/Entladen)                                                                                               |
| `battery_min_soc`       | %        | `components.json` → `batteries[]`    | Untere SOC-Grenze (Schutz)                                                                                                            |
| `battery_max_soc`       | %        | `components.json` → `batteries[]`    | Obere SOC-Grenze                                                                                                                      |
| `threshold_power`       | Anteil   | `components.json` → `batteries[]`    | Relativ zu `battery_max_power_kw` (z. B. `0.2` = 20 %). Schwellwert für Modus-Erkennung und Entscheidung Zwangsentladen vs. Automatik |
| `timezone_name`         | —        | `house_profiles.json`                | IANA-Zeitzone für astronomische Sonnenzeiten (z. B. `Europe/Vienna`); siehe `planning_horizon`                                        |


Loxone liefert die erzeugte Energie weiterhin als **Summe** aller Anlagen (`pv_counter_name` / `pv_power_name`).


## SOC-Verhalten

Der Parameter `battery_wear` kann niedrigere End-SOCs wirtschaftlich bestrafen (weicher Anreiz, unabhängig vom Modus). Der Block liegt am `components.json` **→** `batteries[]`**-Eintrag**, nicht mehr global in `config.json`.

Block `planning_horizon` in `config.json`:

```json
"planning_horizon": {
  "mode": "sunrise_window"
}
```

Details: [Spezifikation Sunset-Planungshorizont](../spec/planning-horizon-sunset.md).

## Batterieverschleiß (`battery_wear`)

Lineares Amortisationsmodell in der MILP-Zielfunktion. Pro kWh Durchsatz (Laden **oder** Entladen) wird ein Verschleiß-Anteil addiert:

`ct/kWh = cycle_cost_fraction × replacement_cost_euro / expected_cycles / battery_capacity_kwh × 100`

Beispiel (5 kWh, 1500 €, 6000 Zyklen, 50 % zyklenbedingt): **2,5 ct/kWh**.


| Parameter               | Bedeutung                                                                       |
| ----------------------- | ------------------------------------------------------------------------------- |
| `enabled`               | `false` = kein Verschleiß-Term (explizit aus); `true` = Parameter unten Pflicht |
| `replacement_cost_euro` | Ersatzkosten der Batterie                                                       |
| `expected_cycles`       | Angenommene Vollzyklen bis Ersatz                                               |
| `cycle_cost_fraction`   | Anteil der Kosten durch Zyklen (Rest: Kalenderalterung)                         |




## Live-Szenario vs. `config.json`

In der App (Seite **Szenarieneditor**) werden Entitäts-Referenzen für das Live-Szenario gewählt (PV als Mehrfachauswahl). Gespeichert wird das Live-Szenario in `backtesting_scenarios.json` (`live_scenario_id` in `config.json`, Standard: `live`). PV- und Batterie-Entitäten selbst pflegt man im **Hauskonfigurator**. Die Bezeichnung des Live-Szenarios ist fest.

## Szenarien

Zum Vergleich von Varianten zum Live-Szenario (größerer Speicher, mehrere PV-Anlagen, anderer Strom-Tarif, ...) ohne Produktiv-Änderung: weitere Einträge in `backtesting_scenarios.json` (siehe [Überblick](ueberblick.md)).
