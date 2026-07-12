# PV & Batterie (Live-Szenario)

Diese Parameter beschreiben die physische Anlage und fließen in die MILP-Optimierung ein (Live und Simulation). Konfiguration über Entitäts-Referenzen im **Live-Szenario** (`backtesting_scenarios.json`, gewählt via `live_scenario_id` in `config.json`); technische Werte liegen in `batteries[]` und `pv_systems[]`.

| Parameter | Einheit | Quelle | Bedeutung |
|-----------|---------|--------|-----------|
| `kwp` | kWp | `pv_systems[]` | Installierte PV-Leistung (aufgelöst als `pv_kwp`) |
| `pv_tilt` | ° | `pv_systems[]` | Dachneigung |
| `pv_azimuth` | ° | `pv_systems[]` | Ausrichtung: `0` = Süd, `-90` = Ost, `90` = West |
| `latitude`, `longitude` | ° | `house_profiles.json` (via Szenario) | Standort für PV-Prognose (Forecast.Solar) |
| `k_push_cent` | Cent/kWh | `tariffs.json` (Export-Tarif) | **Einspeisevergütung** |
| `battery_capacity_kwh` | kWh | `batteries[]` | Nutzbare Speicherkapazität |
| `battery_max_power_kw` | kW | `batteries[]` | Max. Lade- und Entladeleistung |
| `battery_efficiency` | 0–1 | `batteries[]` | Roundtrip-Wirkungsgrad (Laden/Entladen) |
| `battery_min_soc` | % | `batteries[]` | Untere SOC-Grenze (Schutz) |
| `battery_max_soc` | % | `batteries[]` | Obere SOC-Grenze |
| `threshold_power` | Anteil | `batteries[]` | Relativ zu `battery_max_power_kw` (z. B. `0.2` = 20 %). Schwellwert für Modus-Erkennung und Entscheidung Zwangsentladen vs. Automatik |
| `timezone_name` | — | `house_profiles.json` | IANA-Zeitzone für astronomische Sonnenzeiten (z. B. `Europe/Vienna`); siehe `planning_horizon` |

## End-SOC (MILP)

Es gibt **keinen** Config-Parameter mehr für die End-SOC-Randbedingung (früher `battery_end_soc_equals_start`, entfernt 2026-07-04). Das Verhalten hängt vom Betriebsmodus ab:

| Kontext | End-SOC-Regel |
|---------|----------------|
| **Live** (`planning_horizon.mode: sunrise_window`) | Hart **SOC_min am nächsten Sonnenaufgang** innerhalb des MILP-Horizonts |
| **Backtesting** (`--horizon-mode fixed_24h`) | End-SOC = **Anker-SOC** des Schritts (`initial_soc`; intern `terminal_soc_percent`) |
| **Backtesting** (`--horizon-mode sunrise_window`) | Wie Live: SOC_min am Sonnenaufgang |

Zusätzlich kann **`battery_wear`** niedrigere End-SOCs wirtschaftlich bestrafen (weicher Anreiz, unabhängig vom Modus). Der Block liegt am **`batteries[]`-Eintrag**, nicht mehr global in `config.json`.

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

| Parameter | Bedeutung |
|-----------|-----------|
| `enabled` | `false` = kein Verschleiß-Term (explizit aus); `true` = Parameter unten Pflicht |
| `replacement_cost_euro` | Ersatzkosten der Batterie |
| `expected_cycles` | Angenommene Vollzyklen bis Ersatz |
| `cycle_cost_fraction` | Anteil der Kosten durch Zyklen (Rest: Kalenderalterung) |

## Live-Konfiguration vs. `config.json`

In der App (Seite **Live-Konfiguration**, Abschnitt Echtzeit-Umgebung) werden Entitäts-Referenzen per Dropdown gewählt; die Leistungsschwelle erscheint dort in **Prozent** der max. Batterieleistung. Gespeichert wird in das Live-Szenario in `backtesting_scenarios.json`. PV- und Batterie-Entitäten selbst pflegt man im **Hauskonfigurator**.

## Adaptives PV-Tuning (entfallen)

Adaptives PV-Tuning in der Sidebar wurde mit dem UI-Modus **Sunset-2-Sunset** entfernt (neuer Adaptions-Ansatz im Backlog). Config-Felder wie `loxone_blocks.pv_tuning_log_file` bleiben in der Schema-Vorlage, haben aber derzeit keine UI-Wirkung.

## Szenarien

Zum Vergleich größerer Speicher ohne Produktiv-Änderung: weitere Einträge in `backtesting_scenarios.json` (siehe [Überblick](ueberblick.md)).
