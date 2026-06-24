# Konfiguration — Überblick

Die zentrale Datei ist **`config.json`** im Projektroot. Als Startpunkt dient [`config.example.json`](../../config.example.json).

## Schema und Editor-Hilfe

Am Dateianfang:

```json
"$schema": "./config.schema.json"
```

In Cursor/VS Code erscheinen für viele Felder **Hover-Beschreibungen** aus [`config.schema.json`](../../config.schema.json). Ausführlichere Zusammenhänge stehen in den folgenden Kapiteln dieser Dokumentation.

## Hauptblöcke

| Block | Zweck |
|-------|--------|
| `awattar` | API und Aufschläge für Bezugsstrompreis (Österreich) |
| `system` | Timeouts für HTTP und Optimierungs-Schleife |
| `loxone_blocks` | Zentrale Loxone-IO-Namen (Speicher, PV, Steuerung) |
| `runtime_settings` | PV-Anlage, Batterie, Standort — **Produktiv und Simulation** |
| `scenarios` | Zusätzliche Parameter-Sets nur für Simulation/Backtesting |
| `file_paths_battery_simulation` | Pfade zu historischen CSVs, Preisquelle, `cons_data_hourly.csv` |
| `flexible_consumers` | Steuerbare Verbraucher (MILP) mit Loxone-Ein-/Ausgängen |

## `scenarios` vs. `runtime_settings`

- **`runtime_settings`:** Maßgeblich für `main.py` und die App im Modus **Echtzeit**.
- **`scenarios`:** Alternative Batterie-/PV-Konfigurationen zum Vergleich in Simulation und Backtesting (z. B. „10 kWh Speicher“). Ändern **nicht** automatisch den Produktivbetrieb.

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

## Sidebar in der App

Im Modus **Echtzeit** und **Historischer Tag** können PV-, Batterie- und Einspeiseparameter in der Sidebar geändert werden. Gespeichert wird direkt in `runtime_settings` von `config.json` — nicht in `scenarios`.

## Weiterführend

- [PV & Batterie](batterie-pv.md)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Loxone-Signale](../referenz/loxone-signale.md)
