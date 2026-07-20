# Flexible Verbraucher

Ab **2.0** liegen steuerbare Verbraucher (SwimSpa, E-Auto, Wärmepumpe, Filter, Generics) primär im **Hausprofil** (`earnie_env/config/house_profiles.json`). Der Block `flexible_consumers[]` in `config.json` ist **Legacy** (meist leer) und wird nur noch bei Bedarf über `legacy_id` mit dem Profil überlagert.

Die Optimierung entscheidet **wann** sie laufen, nicht ob die Anlage technisch kann — die Freigabe an Loxone ist ein 0/1-Signal (E-Auto: Leistungs-Sollwert + PV-Follow). Die Feldnamen unten gelten für die aufgelöste Flex-Struktur (Profil-Bridge bzw. Legacy-Eintrag).

## Pflichtfelder (je Verbraucher)


| Feld                | Bedeutung                                                              |
| ------------------- | ---------------------------------------------------------------------- |
| `id`                | Interne Kennung (z. B. `eauto`)                                        |
| `name`              | Anzeigename in Charts und UI                                           |
| `nominal_power_kw`  | Nennleistung für die MILP                                              |
| `chart_color_index` | Farbindex 0–7 für Chart 1 und Sankey (siehe [Charts](../ui/charts.md)) |
| `optimizer_enabled` | `false` = von Optimierung ausgeschlossen                               |




## Tagesenergie-Ziel


| Feld                  | Bedeutung                                                                                                                                                                                                                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `daily_target_kwh`    | Festes 24h-Ziel in kWh (bei `daily_target_source: config`)                                                                                                                                                                                               |
| `daily_target_source` | `config` = fester Wert / `charging_schedule`; `historical` = Profil aus Vergangenheit; `loxone` = Live-Merker in kWh; `loxone_remaining_hours` = Live-Schulden in Stunden × `nominal_power_kw` (SwimSpa-Filter); `thermal` = RC-Modell (SwimSpa-Heizung) |
| `min_on_quarterhours` | Mindestlaufzeit pro Einschaltung in 15-Minuten-Slots                                                                                                                                                                                                     |
| `path_historical_log` | Loxone-CSV für historische Profile und Backtesting (Offline → `cons_data`). Beim Laden noch Alias `path_log` möglich                                                                                                                                   |
| `signal_type`         | `power` (kW) oder `binary` (Ein/Aus × `nominal_power_kw`)                                                                                                                                                                                                |
| `log_signal_type`     | Optional: anderes Format nur für `path_historical_log`                                                                                                                                                                                                  |




## Loxone-Anbindung pro Verbraucher


| Verbraucher                 | Lesen                      | Schreiben                                                                                 |
| --------------------------- | -------------------------- | ----------------------------------------------------------------------------------------- |
| SwimSpa, Wärmepumpe, Filter | `loxone_inputs.power_name` | `loxone_outputs.enable_name` (0/1)                                                        |
| E-Auto                      | `loxone_inputs.power_name` | `loxone_outputs.power_setpoint_name` (kW), `pv_follow_name` (0/1); `min_power_kw` Pflicht |


Optional: `loxone_inputs.subtract_consumer_ids` — Leistung anderer Verbraucher vom Ist abziehen (SwimSpa − Filter, siehe [Loxone-Signale](../referenz/loxone-signale.md)).

Signalübersicht: [Loxone-Signale](../referenz/loxone-signale.md).

## Pool: `thermal_control`

Bei `daily_target_source: thermal` steuert das RC-Modell das Tagesenergieziel aus Wassertemperatur und Umgebung:


| Feld                                         | Bedeutung                                                                                                      |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `thermal_control.enabled`                    | Modell aktiv                                                                                                   |
| `thermal_control.setpoint_c` / `tolerance_c` | Soll-Temperatur und Band                                                                                       |
| `thermal_control.water_volume_liters`        | Wasservolumen                                                                                                  |
| `thermal_control.heat_loss_kw_per_k`         | Wärmeverlust pro Kelvin                                                                                        |
| `thermal_control.loxone`                     | Merker für Ist-/Soll-/Außentemperatur und optional `heating_active_name` (binär, Fall B)                       |
| `thermal_control.history_logs`               | CSV-Pfade für Kalibrierung; optional `heating_active_csv` / `filter_active_csv` statt reiner Leistungsschwelle |


Details: [Loxone-Signale](../referenz/loxone-signale.md), [SwimSpa Filter](../spec/swimspa-filter.md).

## E-Auto: `charging_schedule`

Wenn gesetzt und `enabled: true`:


| Feld                   | Bedeutung                                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `target_soc_percent`   | Ziel-SOC beim Abfahren (meist 100)                                                                                                         |
| `charging_efficiency`  | Lade-Wirkungsgrad (Netz → Akku)                                                                                                            |
| `forecast_when_absent` | Bei `daily_target_source: loxone`: Ladebedarf auch prognostizieren, wenn Auto nicht angeschlossen                                          |
| `weekday` / `weekend`  | `car_available_from_hour`, `ready_by_hour`, `daily_rest_soc`                                                                               |
| `loxone`               | `plugged_in_name`, `ready_by_time_name`, `soc_at_plug_in_name`, `battery_capacity_kwh_name`, `nominal_power_kw_name`, `charge_immediate_*` |


Ladeziel in kWh (vereinfacht, Kapazität nur aus Loxone):

`(target_soc_percent − Rest-SOC) / 100 × Akkukapazität_Loxone / charging_efficiency`

`nominal_power_kw_name` überschreibt zur Laufzeit die konfigurierte `nominal_power_kw`, wenn der Merker lesbar ist.

Block `charging_schedule.milp` am EV-Verbraucher in `house_profiles.json`: Feintuning der MILP-Heuristik (`live_modus_a_min_remaining_kwh`, Tie-Break-Parameter) — siehe Schema.

## Pool-Filter: `filter_schedule` und `loxone_remaining_hours`

Getrennter Verbraucher `swimspa_filter` (Heizung bleibt `swimspa` mit `daily_target_source: thermal`).


| Feld                              | Bedeutung                                                                                       |
| --------------------------------- | ----------------------------------------------------------------------------------------------- |
| `daily_target_source`             | `loxone_remaining_hours` — Ziel_kWh = `Sollstunden` × `nominal_power_kw`                        |
| `loxone_target_hours_name`        | Loxone-Merker für verbleibende Filter-Schulden in **Stunden** (Float)                           |
| `filter_schedule.enabled`         | `true` = natives Duty-Cycle-Fenster sperrt MILP-Slots                                           |
| `filter_schedule.loxone`          | `native_start_hour_name`, `native_duration_hours_name` — natives Fenster `[Start, Start+Dauer)` |
| `filter_schedule.config_fallback` | Festes Fenster für Backtesting/Offline (kein `path_historical_log`)                             |


Earnie schaltet nur **ergänzend** außerhalb des nativen Fensters ein (`loxone_outputs.enable_name`). Spec: [SwimSpa Filter](../spec/swimspa-filter.md).

## Manuelle Geräte (Hausprofil, `type: generic`)

Waschmaschine, Trockner usw. als `generic`**-Verbraucher** in `house_profiles.json` (optional `appliance_recommendation` für Loxone-Leistung und Empfehlungsmodus). Planung über die Seite **Manuelle Geräte**; Persistenz in `runtime/appliance_schedules.json`. Geplante Laufzeiten erscheinen in Chart 1 (Flow-Balance).


| Feld                                                             | Bedeutung                                                      |
| ---------------------------------------------------------------- | -------------------------------------------------------------- |
| `id`, `label`                                                    | Kennung und Anzeigename                                        |
| `appliance_recommendation.power_source`                          | `loxone` oder `manual`                                         |
| `loxone_inputs.power_name`                                       | Bei `loxone`: Ist-Leistungsmerker (`known` und `manual`)       |
| `appliance_recommendation.default_power_kw`, `default_runtime_h` | Standard für Empfehlungsmodus (Seite liest nur aus Hausprofil) |




## Baseline in der UI

In Charts und Tabellen:

- **BL Profil:** historisches Verbrauchsmuster ohne Verschiebung
- **BL Ziel:** gleiche Tagesenergie wie die Optimierung, aber ohne zeitliche Verschiebung (Vergleich „was wäre ohne Optimierung“)



## Hausprofil: Generic-Verbraucher und `earnie_role`

Im Hausprofil (`house_profiles.json`, `type: generic`) steuert `earnie_role` (Standard: `known`) die Berücksichtigung in der Live-Optimierung:


| `earnie_role` | Bedeutung                                                                                                                   | `start_shift_h`                                       |
| ------------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `known`       | Geplante Laufzeiten werden zur **Grundlast** (`expected_p_act`) addiert — nicht als MILP-Flex                               | wird auf `0` gesetzt (fester Start)                   |
| `flex`        | Optimierbare Flex-Last (MILP)                                                                                               | Verschiebungsfenster (± h)                            |
| `manual`      | **Manuelles Gerät** — Planung auf **Live-Cockpit → Manuelle Geräte**; Start-Empfehlungen. In **Live-Planung und Szenario-Explorer** fließt die **Profil-Default-Schedule** wie bei `known` als fixe Grundlast ein (Annahme: Nutzer startet wie empfohlen). Nicht MILP-Flex. | **Empfehlungshorizont (h)** für die Startzeit-Tabelle |


Einrichtung im **Hauskonfigurator** unter „Earnie-Berücksichtigung“. Thermische Verbraucher (SwimSpa, Wärmepumpe) und E-Auto sind hiervon unberührt.

### Leistungsquelle (Loxone-Merker)

Bei `earnie_role: known` oder `manual` kann optional eine **Loxone-Leistungsquelle** konfiguriert werden:


| Feld                                         | Bedeutung                                                             |
| -------------------------------------------- | --------------------------------------------------------------------- |
| `loxone_inputs.power_name`                   | Loxone-Merker für Ist-Leistung (einheitlich für `known` und `manual`) |
| `appliance_recommendation.power_source`      | `manual` oder `loxone` (nur bei `manual`)                             |
| `appliance_recommendation.default_power_kw`  | Nennleistung für Empfehlung/Grundlast                                 |
| `appliance_recommendation.default_runtime_h` | Standard-Laufzeit (nur bei `manual`)                                  |


Der Merker wird gespeichert; Live-Abfrage und Adaption der Nennleistung folgen in **Version 2.+1**. Bis dahin nutzt die Grundlast-Overlay bzw. die Startzeit-Empfehlung die Werte aus dem Profil.