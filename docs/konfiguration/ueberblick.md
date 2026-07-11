# Konfiguration — Überblick

Die zentrale Datei ist **`config/config.json`**. Als Startpunkt dient [`config/config.example.json`](../../config/config.example.json).

## Schema und Editor-Hilfe

Am Dateianfang von `config/config.json`:

```json
"$schema": "./config.schema.json"
```

In Cursor/VS Code erscheinen für viele Felder **Hover-Beschreibungen** aus [`config/config.schema.json`](../../config/config.schema.json). Ausführlichere Zusammenhänge stehen in den folgenden Kapiteln dieser Dokumentation.

## Hauptblöcke

| Block | Zweck |
|-------|--------|
| `system` | Timeouts für HTTP und Optimierungs-Schleife |
| `loxone_blocks` | Zentrale Loxone-IO-Namen (Speicher, PV, Steuerung) |
| `live_scenario_id` | ID des **Live-Szenarios** in `backtesting_scenarios.json` (Standard: `live`) |
| `batteries[]` / `pv_systems[]` | Technische Parameter für Speicher und PV (referenziert über IDs) |
| `config/tariffs.json` | Tarif-Katalog (Bezug/Einspeise); referenziert über `import_tariff_id` / `export_tariff_id` |
| `config/house_profiles.json` | Standort (Geo/Zeitzone) und Planungs-Verbraucher; referenziert über `house_profile_id` |
| `config/backtesting_scenarios.json` | **Alle** Szenarien (Live + Varianten); einheitliches `settings`-Format |
| `file_paths_battery_simulation` | Pfade zu historischen CSVs, Preisquelle, `cons_data_hourly.csv` |
| `flexible_consumers` | Steuerbare Verbraucher (MILP) mit Loxone-Ein-/Ausgängen |

Vorlage für Szenarien: [`backtesting_scenarios.example.json`](../../config/backtesting_scenarios.example.json).

## Szenarien (Live und Scenario-Exploration)

Ab **2.0 P2** gibt es **kein** separates `runtime_settings` in `config.json` mehr.

- **`live_scenario_id`** in `config.json` wählt das Live-Szenario (Standard-ID: `live`).
- **`backtesting_scenarios.json`** enthält **alle** Szenarien im gleichen Format (`id`, `label`, `settings` mit Entitäts-Referenzen oder — für What-if — flachen Parametern).
- **Live-Betrieb** (`main.py`, Modus **Sunset-2-Sunset**) und **Scenario-Exploration** lösen dasselbe Live-Szenario über [`house_config/scenario_resolution.py`](../../house_config/scenario_resolution.py) auf.
- Weitere Szenarien in derselben Datei dienen nur dem Vergleich in Scenario-Exploration; sie ändern den Produktivbetrieb nicht.

## `file_paths_battery_simulation`

| Feld | Bedeutung |
|------|-----------|
| `path_consumption`, `path_production`, `path_price` | Historische Loxone-/Marktdaten für Analyse und Backtesting |
| `path_cons_data` | Stündliche Verbrauchs- und PV-Basis für Optimierung (wird von `main.py` gepflegt) |
| `cons_data_retention_months` | Wie lange Stundenwerte aufbewahrt werden |
| `cons_data_write_mode` | Schreibmodus (`hourly`) |
| `price_source` | `api` = Live-Preise; andere Werte für historische Preise aus CSV |
| `price_provider` | z. B. `awattar` |
| `price_range` | z. B. `last_12_months` für historische Auswertungen |
| `energy_charts_bzn` | Bidding Zone für Energy-Charts-CSV (z. B. `DE-LU`) |

Details zu Preisen: [Preise & aWATTar](preise.md).

## Greenfield-Planungsworkflow (1.25)

Nach Minimal-Bootstrap (`flexible_consumers` leer) gilt diese Reihenfolge:

1. **Hauskonfigurator** — Hausprofil mit Verbrauchern, optional Jahres-CSV zum Abgleich (`total_profile_csv`), PV-Entitäten in `config.json` → `pv_systems[]`, Profile in `config/house_profiles.json`.
2. **Szenarieneditor** — Live-Szenario (Pflicht): Entitäts-Referenzen in `backtesting_scenarios.json`; Auswahl über `live_scenario_id` in `config.json`. Optionale weitere Szenarien in derselben Datei.
3. **Scenario-Exploration** — Lauf aus der UI oder `python -m scripts.run_backtesting`; Ergebnisse in `backtesting_log.json`. Der Log enthält einen `config_fingerprint` zum Abgleich mit der aktuellen Konfiguration.

Tarif-Katalog: manuell in `config/tariffs.json` (kein UI-Editor).

## Migration von flachen `runtime_settings` (1.26.0 P5 → 2.0 P6)

Bestehende Produktiv-Configs mit flachem Block `runtime_settings` in `config.json` werden per Skript in ID-Referenzen überführt:

```powershell
python -m scripts.migrate_runtime_entities --input config/config.json --output-dir migrated/
```

Das Skript schreibt **Entwürfe** (`config.json`, `tariffs.json`, `house_profiles.json`, `MIGRATION_REVIEW.md`) — **manuelle Prüfung vor NAS-Deploy**. Für **2.0** folgt zusätzlich die Überführung in `live_scenario_id` + Live-Eintrag in `backtesting_scenarios.json` (Backlog **2.0 P6**). Globaler `battery_wear` wird in den gewählten `batteries[]`-Eintrag übernommen; aWATTar-Aufschläge in den passenden Tarif in `tariffs.json`. Geo/Zeitzone wandern ins referenzierte Hausprofil.

## Seite Konfiguration

Im Modus **Sunset-2-Sunset** wählt die Seite **Konfiguration** (Komfort-Ansicht Live-Szenario) Entitäten per Dropdown (`battery_id`, PV, Tarife, Hausprofil). Aufgelöste Werte (kWp, Kapazität, Vergütung) sind **read-only**; gespeichert werden nur IDs im Live-Szenario in `backtesting_scenarios.json`.

## Weiterführend

- [PV & Batterie](batterie-pv.md)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Loxone-Signale](../referenz/loxone-signale.md)
