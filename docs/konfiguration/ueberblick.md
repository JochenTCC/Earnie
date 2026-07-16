# Konfiguration — Überblick

Die zentrale Datei ist `config/config.json`. Als Startpunkt dient `[config/config.example.json](../../config/config.example.json)`.

## Schema und Editor-Hilfe

Am Dateianfang von `config/config.json`:

```json
"$schema": "./config.schema.json"
```

In Cursor/VS Code erscheinen für viele Felder **Hover-Beschreibungen** aus `[config/config.schema.json](../../config/config.schema.json)`. Ausführlichere Zusammenhänge stehen in den folgenden Kapiteln dieser Dokumentation.

## Hauptblöcke


| Block                               | Zweck                                                                                                                        |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `system`                            | Timeouts für HTTP und Optimierungs-Schleife                                                                                  |
| `market_prices`                     | Strategie für fehlende Zukunftspreise (`forecast` / `mirror`) — siehe [Preise](preise.md)                                    |
| `ui`                                | Streamlit-Port, Refresh-Intervalle, optionale Dev-Seiten                                                                     |
| `loxone_blocks`                     | Zentrale Loxone-IO-Namen (Speicher, PV, Steuerung)                                                                           |
| `live_scenario_id`                  | ID des **Live-Szenarios** in `backtesting_scenarios.json` (Standard: `live`)                                                 |
| `config/components.json`            | Technische Parameter für Speicher und PV (`batteries[]`, `pv_systems[]`; referenziert über IDs)                              |
| `config/tariffs.json`               | Tarif-Katalog (Bezug/Einspeise); referenziert über `import_tariff_id` / `export_tariff_id`                                   |
| `config/house_profiles.json`        | Standort (Geo/Zeitzone), Planungs-Verbraucher (EV, Wärmepumpe, Waschmaschine …); referenziert über `house_profile_id`        |
| `config/backtesting_scenarios.json` | **Alle** Szenarien (Live + Varianten); einheitliches `settings`-Format                                                       |
| `file_paths_battery_simulation`     | Pfade zu historischen CSVs, Preisquelle, `cons_data_hourly.csv`                                                              |
| `flexible_consumers`                | Legacy: steuerbare Verbraucher (MILP) mit Loxone-Ein-/Ausgängen — ab **2.0** leer; Live-Verbraucher in `house_profiles.json` |
| `planning_horizon`                  | MILP-Horizont (`sunrise_window` für Live)                                                                                    |


Vorlage für Szenarien: `[backtesting_scenarios.example.json](../../config/backtesting_scenarios.example.json)`.

## Szenarien (Live und Szenario-Explorer)

- `live_scenario_id` in `config.json` wählt das Live-Szenario (Standard-ID: `live`).
- `backtesting_scenarios.json` enthält **alle** Szenarien im gleichen Format (`id`, `label`, `settings` mit Entitäts-Referenzen oder — für What-if — flachen Parametern).
- **Live-Betrieb** (`main.py`, Modus **Sunset-2-Sunset**) und **Szenario-Explorer** lösen dasselbe Live-Szenario über `[house_config/scenario_resolution.py](../../house_config/scenario_resolution.py)` auf.
- Weitere Szenarien in derselben Datei dienen nur dem Vergleich in Szenario-Explorer; sie ändern den Produktivbetrieb nicht.



## `file_paths_battery_simulation`


| Feld                                                | Bedeutung                                                                         |
| --------------------------------------------------- | --------------------------------------------------------------------------------- |
| `path_consumption`, `path_production`, `path_price` | Historische Loxone-/Marktdaten für Analyse und Backtesting                        |
| `path_cons_data`                                    | Stündliche Verbrauchs- und PV-Basis für Optimierung (wird von `main.py` gepflegt) |
| `cons_data_retention_months`                        | Wie lange Stundenwerte aufbewahrt werden                                          |
| `cons_data_write_mode`                              | Schreibmodus (`hourly`)                                                           |
| `price_source`                                      | `api` = Live-Preise; andere Werte für historische Preise aus CSV                  |
| `price_provider`                                    | z. B. `awattar`                                                                   |
| `price_range`                                       | z. B. `last_12_months` für historische Auswertungen                               |
| `energy_charts_bzn`                                 | Bidding Zone für Energy-Charts-CSV (z. B. `DE-LU`)                                |


Details zu Preisen: [Preise & aWATTar](preise.md).


## Seite Live-Konfiguration

Im Abschnitt **Echtzeit-Umgebung** wählt die Seite **Live-Konfiguration** (Komfort-Ansicht Live-Szenario) Entitäten per Dropdown (`battery_id`, PV, Tarife, Hausprofil). Aufgelöste Werte (kWp, Kapazität, Vergütung) sind **read-only**; gespeichert werden nur IDs im Live-Szenario in `backtesting_scenarios.json`.

## Weiterführend

- [PV & Batterie](batterie-pv.md)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Loxone-Signale](../referenz/loxone-signale.md)

