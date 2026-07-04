# PV & Batterie (`runtime_settings`)

Diese Parameter beschreiben die physische Anlage und fließen in die MILP-Optimierung ein (Live und Simulation).

| Parameter | Einheit | Bedeutung |
|-----------|---------|-----------|
| `pv_kwp` | kWp | Installierte PV-Leistung |
| `pv_tilt` | ° | Dachneigung |
| `pv_azimuth` | ° | Ausrichtung: `0` = Süd, `-90` = Ost, `90` = West |
| `latitude`, `longitude` | ° | Standort für PV-Prognose (Forecast.Solar) |
| `k_push_cent` | Cent/kWh | **Einspeisevergütung** (Erlös bei Einspeisung ins Netz) |
| `battery_capacity_kwh` | kWh | Nutzbare Speicherkapazität |
| `battery_max_power_kw` | kW | Max. Lade- und Entladeleistung |
| `battery_efficiency` | 0–1 | Roundtrip-Wirkungsgrad (Laden/Entladen) |
| `battery_min_soc` | % | Untere SOC-Grenze (Schutz) |
| `battery_max_soc` | % | Obere SOC-Grenze |
| `threshold_power` | Anteil | Relativ zu `battery_max_power_kw` (z. B. `0.2` = 20 %). Schwellwert für Modus-Erkennung und Entscheidung Zwangsentladen vs. Automatik |
| `timezone_name` | — | IANA-Zeitzone für astronomische Sonnenzeiten (z. B. `Europe/Vienna`); siehe `planning_horizon` |

## End-SOC (MILP)

Es gibt **keinen** Config-Parameter mehr für die End-SOC-Randbedingung (früher `battery_end_soc_equals_start`, entfernt 2026-07-04). Das Verhalten hängt vom Betriebsmodus ab:

| Kontext | End-SOC-Regel |
|---------|----------------|
| **Live** (`planning_horizon.mode: sunset_window`) | Hart **SOC_min am nächsten Sonnenaufgang** innerhalb des MILP-Horizonts |
| **Backtesting** (`--horizon-mode fixed_24h`) | End-SOC = **Anker-SOC** des Schritts (`initial_soc`; intern `terminal_soc_percent`) |
| **Backtesting** (`--horizon-mode sunset_window`) | Wie Live: SOC_min am Sonnenaufgang |

Zusätzlich kann **`battery_wear`** niedrigere End-SOCs wirtschaftlich bestrafen (weicher Anreiz, unabhängig vom Modus).

Block `planning_horizon` in `config.json`:

```json
"planning_horizon": {
  "mode": "sunset_window"
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

## Sidebar vs. `config.json`

In der App-Sidebar sind dieselben Werte editierbar (Leistungsschwelle dort in **Prozent** der max. Batterieleistung). Nach „Alle Änderungen übernehmen“ landen sie in `runtime_settings`.

## Adaptives PV-Tuning (Sidebar, nur Echtzeit)

Die App kann einen **Korrekturfaktor** aus dem Vergleich Forecast.Solar vs. realem PV-Zähler (`pv_counter_name`) der letzten 14 Tage anzeigen. Logdatei: `loxone_blocks.pv_tuning_log_file`. Das automatische Schreiben des Vergleichslogs ist derzeit in `main.py` nicht angebunden — der Faktor bleibt praktisch bei 1,0, bis das Logging wieder aktiv ist.

## Szenarien

Zum Vergleich größerer Speicher ohne Produktiv-Änderung: `scenarios[]` in `config/backtesting_scenarios.json` (siehe [Überblick](ueberblick.md)).
