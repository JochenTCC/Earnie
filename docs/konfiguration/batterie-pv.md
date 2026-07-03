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
| `battery_end_soc_equals_start` | bool | SOC am Ende des 24h-Horizonts = Start-SOC (verhindert künstliches „Ausverkaufen“ am Planungsende) |
| `threshold_power` | Anteil | Relativ zu `battery_max_power_kw` (z. B. `0.2` = 20 %). Schwellwert für Modus-Erkennung und Entscheidung Zwangsentladen vs. Automatik |

## Sidebar vs. `config.json`

In der App-Sidebar sind dieselben Werte editierbar (Leistungsschwelle dort in **Prozent** der max. Batterieleistung). Nach „Alle Änderungen übernehmen“ landen sie in `runtime_settings`.

## Adaptives PV-Tuning (Sidebar, nur Echtzeit)

Die App kann einen **Korrekturfaktor** aus dem Vergleich Forecast.Solar vs. realem PV-Zähler (`pv_counter_name`) der letzten 14 Tage anzeigen. Logdatei: `loxone_blocks.pv_tuning_log_file`. Das automatische Schreiben des Vergleichslogs ist derzeit in `main.py` nicht angebunden — der Faktor bleibt praktisch bei 1,0, bis das Logging wieder aktiv ist.

## Szenarien

Zum Vergleich größerer Speicher ohne Produktiv-Änderung: `scenarios[]` in `config/backtesting_scenarios.json` (siehe [Überblick](ueberblick.md)).
