# Konfiguration — Überblick

Die zentrale Datei ist `earnie_env/config/config.json`. Als Startpunkt dient [`share/config/config.example.json`](../../share/config/config.example.json) (Bootstrap kopiert fehlende Dateien). Siehe auch [Speichern / Laden](speichern-laden.md) und [Private Haus-Config](../einrichtung/private-env.md).

## Schema und Editor-Hilfe

Am Dateianfang von `config.json`:

```json
"$schema": "./config.schema.json"
```

In Cursor/VS Code erscheinen für viele Felder **Hover-Beschreibungen** aus [`share/config/config.schema.json`](../../share/config/config.schema.json). Ausführlichere Zusammenhänge stehen in den folgenden Kapiteln dieser Dokumentation.

## Hauptblöcke


| Block                               | Zweck                                                                                                                        |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `system`                            | Timeouts für HTTP und Optimierungs-Schleife                                                                                  |
| `market_prices`                     | Strategie für fehlende Zukunftspreise (`forecast` / `mirror`) — siehe [Preise](preise.md)                                    |
| `ui`                                | Streamlit-Port, Refresh-Intervalle, optionale Dev-Seiten                                                                     |
| `loxone_blocks`                     | Zentrale Loxone-IO-Namen (Speicher, PV, Steuerung)                                                                           |
| `live_scenario_id`                  | ID des **Live-Szenarios** in `backtesting_scenarios.json` (Standard: `live`)                                                 |
| `earnie_env/config/components.json`            | Technische Parameter für Speicher und PV (`batteries[]`, `pv_systems[]`; referenziert über IDs)                              |
| `earnie_env/config/tariffs.json`               | Laufzeit-Tarifkatalog (Bezug/Einspeise); Seed aus öffentlichem [`share/config/tariffs.json`](../../share/config/tariffs.json) |
| `earnie_env/config/house_profiles.json`        | Standort (Geo/Zeitzone), Planungs-Verbraucher (EV, Wärmepumpe, Waschmaschine …); referenziert über `house_profile_id`        |
| `earnie_env/config/backtesting_scenarios.json` | **Alle** Szenarien (Live + Varianten); einheitliches `settings`-Format                                                       |
| `scenario_explorer_conf`     | Szenario-Explorer / Backtesting: `cons_data_hourly.csv`, Preisquelle; Zeitraum aus cons_data-Monaten |
| `flexible_consumers`                | Legacy-Overlay (meist leer); Live-Verbraucher in `house_profiles.json` |
| `appliance_recommendation`          | Globale Sterne-/Schwellen für Manuelle Geräte (keine Geräte-Definitionen) |
| `planning_horizon`                  | MILP-Horizont (`sunrise_window` für Live)                                                                                    |


Vorlage für Szenarien: [`backtesting_scenarios.example.json`](../../share/config/backtesting_scenarios.example.json).

## Szenarien (Live und Szenario-Explorer)

- `live_scenario_id` in `config.json` wählt das Live-Szenario (Standard-ID: `live`).
- `backtesting_scenarios.json` enthält **alle** Szenarien im gleichen Format (`id`, `label`, `settings` mit Entitäts-Referenzen oder — für What-if — flachen Parametern).
- **Live-Betrieb** (`main.py`, Modus **Sunset-2-Sunset**) und **Szenario-Explorer** lösen dasselbe Live-Szenario über `[house_config/scenario_resolution.py](../../house_config/scenario_resolution.py)` auf.
- Weitere Szenarien in derselben Datei dienen nur dem Vergleich in Szenario-Explorer; sie ändern den Produktivbetrieb nicht.



## `scenario_explorer_conf`


| Feld                         | Bedeutung                                                                 |
| ---------------------------- | ------------------------------------------------------------------------- |
| `path_cons_data`             | Stündliche Verbrauchs-/PV-Basis (von `main.py` gepflegt); SE-Gesamtzeitraum |
| `path_price`                 | Optional: historische Börsenpreise (Energy-Charts-CSV)                    |
| `cons_data_retention_months` | Wie lange Stundenwerte aufbewahrt werden                                  |
| `cons_data_write_mode`       | Schreibmodus (`hourly`)                                                   |
| `price_source`               | `api` = Live-Preise; andere Werte für historische Preise aus CSV          |
| `price_provider`             | z. B. `awattar`                                                           |
| `price_range`                | `last_12_months`: 12 Kalendermonate bis zum letzten **vollständigen** Monat in `cons_data` (rückwärts definiert; Tage chronologisch) |
| `energy_charts_bzn`          | Bidding Zone für Energy-Charts-CSV (z. B. `DE-LU`)                        |

**Drei CSV-Ebenen (nicht vermischen):**

1. **`path_cons_data`** — Runtime-Brennstoff für Live und Szenario-Explorer  
2. **Hausprofil-CSVs** (`total_profile_csv` / `pv_profile_csv` / `profile_csv`) — Planung / Ist-vs-Modell (siehe [Historische Verbrauchs-CSV](verbrauchs-csv.md))  
3. **`path_consumption` / `path_production`** — entfernt (data-model v3); früher rohe Loxone-Paar-CSVs nur für Zeitraumgrenzen  

Details zu Preisen: [Preise & aWATTar](preise.md).


## Szenarieneditor (Live-Szenario)

Im Abschnitt **Konfiguration** pflegt der **Szenarieneditor** das Live-Szenario und weitere Varianten. Entitäten werden per Dropdown gewählt (`battery_id`, PV, Tarife, Hausprofil). Vor den Tarif-Dropdowns gibt es einen gemeinsamen Filter **Land** (`land`: AT/DE/CH) für Bezug und Einspeise sowie getrennte **Typ**-Filter. Beim Einspeise-**Typ** erscheinen `monthly_table` und `monthly_float` gemeinsam als **Monatspreis** (monatsfester Charakter; die interne Berechnung bleibt im Katalog getrennt, bis das Datenmodell vereinheitlicht ist). Ein Regionsfilter ist noch nicht verfügbar. Nach der Tarifwahl erscheinen die Katalogparameter read-only inkl. Hinweis, dass Monatsfixkosten noch nicht in die Kostenrechnung einfließen. Gespeichert werden IDs im jeweiligen Szenario in `backtesting_scenarios.json`. Die **Bezeichnung** des Live-Szenarios (`live_scenario_id` in `config.json`, Standard-ID: `live`) ist fest und kann nicht umbenannt oder entfernt werden.

## Weiterführend

- [Speichern / Laden](speichern-laden.md)
- [PV & Batterie](batterie-pv.md)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Historische Verbrauchs-CSV](verbrauchs-csv.md)
- [Preise & aWATTar](preise.md)
- [Loxone-Signale](../referenz/loxone-signale.md)

