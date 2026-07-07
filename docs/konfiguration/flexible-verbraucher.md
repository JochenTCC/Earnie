# Flexible Verbraucher

Einträge in `flexible_consumers[]` sind zeitlich verschiebbare Lasten (SwimSpa, E-Auto, Wärmepumpe). Die Optimierung entscheidet **wann** sie laufen, nicht ob die Anlage technisch kann — die Freigabe an Loxone ist ein 0/1-Signal.

## Pflichtfelder (je Verbraucher)

| Feld | Bedeutung |
|------|-----------|
| `id` | Interne Kennung (z. B. `eauto`) |
| `name` | Anzeigename in Charts und UI |
| `nominal_power_kw` | Nennleistung für die MILP |
| `optimizer_enabled` | `false` = von Optimierung ausgeschlossen |

## Tagesenergie-Ziel

| Feld | Bedeutung |
|------|-----------|
| `daily_target_kwh` | Festes 24h-Ziel in kWh (bei `daily_target_source: config`) |
| `daily_target_source` | `config` = fester Wert / `charging_schedule`; `historical` = Profil aus Vergangenheit; `loxone` = Live-Merker in kWh; `loxone_remaining_hours` = Live-Schulden in Stunden × `nominal_power_kw` (SwimSpa-Filter); `thermal` = RC-Modell |
| `min_on_quarterhours` | Mindestlaufzeit pro Einschaltung in 15-Minuten-Slots |
| `path_log` | Loxone-CSV für historische Profile und Backtesting |
| `signal_type` | `power` (kW) oder `binary` (Ein/Aus × `nominal_power_kw`) |
| `log_signal_type` | Optional: anderes Format nur für `path_log` |

## Loxone-Anbindung pro Verbraucher

| Block | Richtung | Feld |
|-------|----------|------|
| `loxone_inputs` | Lesen | `power_name` — aktuelle Leistung oder Ein/Aus |
| `loxone_outputs` | Schreiben | `enable_name` — `0` gesperrt, `1` Freigabe |

Signalübersicht: [Loxone-Signale](../referenz/loxone-signale.md).

## E-Auto: `charging_schedule`

Wenn gesetzt und `enabled: true`:

| Feld | Bedeutung |
|------|-----------|
| `target_soc_percent` | Ziel-SOC beim Abfahren (meist 100) |
| `charging_efficiency` | Lade-Wirkungsgrad (Netz → Akku) |
| `forecast_when_absent` | Bei `daily_target_source: loxone`: Ladebedarf auch prognostizieren, wenn Auto nicht angeschlossen |
| `weekday` / `weekend` | `car_available_from_hour`, `ready_by_hour`, `daily_rest_soc` |
| `loxone` | `plugged_in_name`, `ready_by_time_name`, `soc_at_plug_in_name`, `battery_capacity_kwh_name`, `nominal_power_kw_name` |

Ladeziel in kWh (vereinfacht, Kapazität nur aus Loxone):

`(target_soc_percent − Rest-SOC) / 100 × Akkukapazität_Loxone / charging_efficiency`

`nominal_power_kw_name` überschreibt zur Laufzeit die konfigurierte `nominal_power_kw`, wenn der Merker lesbar ist.

## SwimSpa-Filter: `filter_schedule` und `loxone_remaining_hours`

Getrennter Verbraucher `swimspa_filter` (Heizung bleibt `swimspa` mit `daily_target_source: thermal`).

| Feld | Bedeutung |
|------|-----------|
| `daily_target_source` | `loxone_remaining_hours` — Ziel_kWh = `Sollstunden` × `nominal_power_kw` |
| `loxone_target_hours_name` | Loxone-Merker für verbleibende Filter-Schulden in **Stunden** (Float) |
| `filter_schedule.enabled` | `true` = natives Duty-Cycle-Fenster sperrt MILP-Slots |
| `filter_schedule.loxone` | `native_start_hour_name`, `native_duration_hours_name` — natives Fenster `[Start, Start+Dauer)` |
| `filter_schedule.config_fallback` | Festes Fenster für Backtesting/Offline (kein `path_log`) |

Ernie schaltet nur **ergänzend** außerhalb des nativen Fensters ein (`loxone_outputs.enable_name`). Spec: [SwimSpa Filter](../spec/swimspa-filter.md).

## Baseline in der UI

In Charts und Tabellen:

- **BL Profil:** historisches Verbrauchsmuster ohne Verschiebung
- **BL Ziel:** gleiche Tagesenergie wie die Optimierung, aber ohne zeitliche Verschiebung (Vergleich „was wäre ohne Optimierung“)
