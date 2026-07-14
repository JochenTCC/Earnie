# Flexible Verbraucher

Einträge in `flexible_consumers[]` sind zeitlich verschiebbare Lasten (SwimSpa, E-Auto, Wärmepumpe). Die Optimierung entscheidet **wann** sie laufen, nicht ob die Anlage technisch kann — die Freigabe an Loxone ist ein 0/1-Signal (E-Auto: Leistungs-Sollwert + PV-Follow).

## Pflichtfelder (je Verbraucher)

| Feld | Bedeutung |
|------|-----------|
| `id` | Interne Kennung (z. B. `eauto`) |
| `name` | Anzeigename in Charts und UI |
| `nominal_power_kw` | Nennleistung für die MILP |
| `chart_color_index` | Farbindex 0–7 für Chart 1 und Sankey (siehe [Charts](../ui/charts.md)) |
| `optimizer_enabled` | `false` = von Optimierung ausgeschlossen |

## Tagesenergie-Ziel

| Feld | Bedeutung |
|------|-----------|
| `daily_target_kwh` | Festes 24h-Ziel in kWh (bei `daily_target_source: config`) |
| `daily_target_source` | `config` = fester Wert / `charging_schedule`; `historical` = Profil aus Vergangenheit; `loxone` = Live-Merker in kWh; `loxone_remaining_hours` = Live-Schulden in Stunden × `nominal_power_kw` (SwimSpa-Filter); `thermal` = RC-Modell (SwimSpa-Heizung) |
| `min_on_quarterhours` | Mindestlaufzeit pro Einschaltung in 15-Minuten-Slots |
| `path_log` | Loxone-CSV für historische Profile und Backtesting |
| `signal_type` | `power` (kW) oder `binary` (Ein/Aus × `nominal_power_kw`) |
| `log_signal_type` | Optional: anderes Format nur für `path_log` |

## Loxone-Anbindung pro Verbraucher

| Verbraucher | Lesen | Schreiben |
|-------------|-------|-----------|
| SwimSpa, Wärmepumpe, Filter | `loxone_inputs.power_name` | `loxone_outputs.enable_name` (0/1) |
| E-Auto | `loxone_inputs.power_name` | `loxone_outputs.power_setpoint_name` (kW), `pv_follow_name` (0/1); **`min_power_kw`** Pflicht |

Optional: `loxone_inputs.subtract_consumer_ids` — Leistung anderer Verbraucher vom Ist abziehen (SwimSpa − Filter, siehe [Loxone-Signale](../referenz/loxone-signale.md)).

Signalübersicht: [Loxone-Signale](../referenz/loxone-signale.md).

## SwimSpa: `thermal_control`

Bei `daily_target_source: thermal` steuert das RC-Modell das Tagesenergieziel aus Wassertemperatur und Umgebung:

| Feld | Bedeutung |
|------|-----------|
| `thermal_control.enabled` | Modell aktiv |
| `thermal_control.setpoint_c` / `tolerance_c` | Soll-Temperatur und Band |
| `thermal_control.water_volume_liters` | Wasservolumen |
| `thermal_control.heat_loss_kw_per_k` | Wärmeverlust pro Kelvin |
| `thermal_control.loxone` | Merker für Ist-/Soll-/Außentemperatur und optional `heating_active_name` (binär, Fall B) |
| `thermal_control.history_logs` | CSV-Pfade für Kalibrierung; optional `heating_active_csv` / `filter_active_csv` statt reiner Leistungsschwelle |

Bei SwimSpa **Fall B** (Gesamtzähler): `power_csv` = Gesamtleistung; Heizleistung für Kalibrierung/Backtest aus `heating_active_csv` (+ optional `filter_active_csv`) ableiten. Live: `heating_active_name` (`homie_bwa_spa_heating`). Details: [Loxone-Signale](../referenz/loxone-signale.md), [SwimSpa Filter](../spec/swimspa-filter.md).

## E-Auto: `charging_schedule`

Wenn gesetzt und `enabled: true`:

| Feld | Bedeutung |
|------|-----------|
| `target_soc_percent` | Ziel-SOC beim Abfahren (meist 100) |
| `charging_efficiency` | Lade-Wirkungsgrad (Netz → Akku) |
| `forecast_when_absent` | Bei `daily_target_source: loxone`: Ladebedarf auch prognostizieren, wenn Auto nicht angeschlossen |
| `weekday` / `weekend` | `car_available_from_hour`, `ready_by_hour`, `daily_rest_soc` |
| `loxone` | `plugged_in_name`, `ready_by_time_name`, `soc_at_plug_in_name`, `battery_capacity_kwh_name`, `nominal_power_kw_name`, `charge_immediate_*` |

Ladeziel in kWh (vereinfacht, Kapazität nur aus Loxone):

`(target_soc_percent − Rest-SOC) / 100 × Akkukapazität_Loxone / charging_efficiency`

`nominal_power_kw_name` überschreibt zur Laufzeit die konfigurierte `nominal_power_kw`, wenn der Merker lesbar ist.

Block **`eauto_milp`** in `config.json` (Root): Feintuning der MILP-Heuristik (`live_modus_a_min_remaining_kwh`, Tie-Break-Parameter) — siehe Schema.

## SwimSpa-Filter: `filter_schedule` und `loxone_remaining_hours`

Getrennter Verbraucher `swimspa_filter` (Heizung bleibt `swimspa` mit `daily_target_source: thermal`).

| Feld | Bedeutung |
|------|-----------|
| `daily_target_source` | `loxone_remaining_hours` — Ziel_kWh = `Sollstunden` × `nominal_power_kw` |
| `loxone_target_hours_name` | Loxone-Merker für verbleibende Filter-Schulden in **Stunden** (Float) |
| `filter_schedule.enabled` | `true` = natives Duty-Cycle-Fenster sperrt MILP-Slots |
| `filter_schedule.loxone` | `native_start_hour_name`, `native_duration_hours_name` — natives Fenster `[Start, Start+Dauer)` |
| `filter_schedule.config_fallback` | Festes Fenster für Backtesting/Offline (kein `path_log`) |

Earnie schaltet nur **ergänzend** außerhalb des nativen Fensters ein (`loxone_outputs.enable_name`). Spec: [SwimSpa Filter](../spec/swimspa-filter.md).

## Manuelle Geräte (`appliances[]`)

Getrennt von `flexible_consumers`: Waschmaschine, Trockner usw. mit fester Laufzeit. Konfiguration in `config.json` → `appliances[]`; Planung über die Seite **Manuelle Geräte**; Persistenz in `runtime/appliance_schedules.json`. Geplante Laufzeiten erscheinen in Chart 1 (Flow-Balance).

| Feld | Bedeutung |
|------|-----------|
| `id`, `name` | Kennung und Anzeigename |
| `power_source` | `loxone` oder `manual` |
| `loxone_power_name` | Bei `loxone`: Ist-Leistungsmerker |
| `default_power_kw`, `default_runtime_h` | Standard für manuelle Planung |

## Baseline in der UI

In Charts und Tabellen:

- **BL Profil:** historisches Verbrauchsmuster ohne Verschiebung
- **BL Ziel:** gleiche Tagesenergie wie die Optimierung, aber ohne zeitliche Verschiebung (Vergleich „was wäre ohne Optimierung“)
