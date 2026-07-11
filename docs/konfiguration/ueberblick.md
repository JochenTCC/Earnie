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
| `runtime_settings` | **Nur Entitäts-Referenzen** für Live-Betrieb: `battery_id`, `pv_system_id`, `import_tariff_id`, `export_tariff_id`, `house_profile_id` |
| `batteries[]` / `pv_systems[]` | Technische Parameter für Speicher und PV (referenziert über IDs) |
| `config/tariffs.json` | Tarif-Katalog (Bezug/Einspeise); referenziert über `import_tariff_id` / `export_tariff_id` |
| `config/house_profiles.json` | Standort (Geo/Zeitzone) und Planungs-Verbraucher; referenziert über `house_profile_id` |
| `file_paths_battery_simulation` | Pfade zu historischen CSVs, Preisquelle, `cons_data_hourly.csv` |
| `flexible_consumers` | Steuerbare Verbraucher (MILP) mit Loxone-Ein-/Ausgängen |

Zusätzlich für Backtesting: **`config/backtesting_scenarios.json`** mit alternativen Parameter-Sets (Vorlage: [`backtesting_scenarios.example.json`](../../config/backtesting_scenarios.example.json)).

## `backtesting_scenarios.json` vs. `runtime_settings`

- **`runtime_settings`:** Maßgeblich für `main.py` und die App im Modus **Sunset-2-Sunset**. Enthält nur **Referenz-IDs** auf Entitäten in `config.json` / `tariffs.json` / `house_profiles.json` (keine flachen PV-/Batterie-/Tarif-/Geo-Duplikate).
- **`backtesting_scenarios.json`:** Alternative Batterie-/PV-Konfigurationen zum Vergleich in Simulation und Backtesting (z. B. „10 kWh Speicher“). Ändern **nicht** automatisch den Produktivbetrieb. Die Baseline im Backtesting ist weiterhin `runtime_settings` aus `config.json`.

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
2. **Szenarieneditor** — Runtime-Szenario (Pflicht): Batterie-Entitäten, Tarifwahl und Entitäts-Referenzen in `runtime_settings`; optionale weitere Szenarien in `backtesting_scenarios.json`.
3. **Backtesting** — Lauf aus der UI oder `python -m scripts.run_backtesting`; Ergebnisse in `backtesting_log.json`. Der Log enthält einen `config_fingerprint` zum Abgleich mit der aktuellen Konfiguration.

Tarif-Katalog: manuell in `config/tariffs.json` (kein UI-Editor).

## Migration von flachen `runtime_settings` (1.26.0 P5)

Bestehende Produktiv-Configs mit flachen Feldern (`pv_kwp`, `battery_capacity_kwh`, `k_push_cent`, Geo in `runtime_settings`) werden per Skript in ID-Referenzen überführt:

```powershell
python -m scripts.migrate_runtime_entities --input config/config.json --output-dir migrated/
```

Das Skript schreibt **Entwürfe** (`config.json`, `tariffs.json`, `house_profiles.json`, `MIGRATION_REVIEW.md`) — **manuelle Prüfung vor NAS-Deploy**. Globaler `battery_wear` wird in den gewählten `batteries[]`-Eintrag übernommen; aWATTar-Aufschläge in den passenden Tarif in `tariffs.json`. Geo/Zeitzone wandern ins referenzierte Hausprofil.

## Sidebar / Seite Konfiguration

Im Modus **Sunset-2-Sunset** wählt die Seite **Konfiguration** (Runtime-Szenario) Entitäten per Dropdown (`battery_id`, PV, Tarife, Hausprofil). Aufgelöste Werte (kWp, Kapazität, Vergütung) sind **read-only**; gespeichert werden nur IDs in `runtime_settings` — nicht in `backtesting_scenarios.json`.

## Weiterführend

- [PV & Batterie](batterie-pv.md)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Loxone-Signale](../referenz/loxone-signale.md)
