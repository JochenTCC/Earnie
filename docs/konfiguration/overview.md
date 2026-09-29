# Konfiguration — Überblick

Zentrale Datei ist `earnie_env/config/config.json`. Ausgangspunkt: [`share/config/config.example.json`](../../share/config/config.example.json) (Bootstrap kopiert fehlende Dateien). Siehe auch [Speichern / Laden](speichern-laden.md) und [Private Haus-Config](../einrichtung/private-env.md).

## Schema und Editor-Hilfe

Am Anfang von `config.json`:

```json
"$schema": "./config.schema.json"
```

In Cursor/VS Code erscheinen für viele Felder **Hover-Beschreibungen** aus [`share/config/config.schema.json`](../../share/config/config.schema.json). Mehr Kontext in den folgenden Kapiteln.

## Hauptblöcke

| Block | Zweck |
| ----- | ----- |
| `system` | Timeouts für HTTP und den Optimierungszyklus |
| `market_prices` | Strategie für fehlende Zukunftspreise (`forecast` / `mirror`) — siehe [Preise](preise.md) |
| `ui` | Streamlit-Port, Refresh-Intervalle, optionale Dev-Seiten |
| `loxone_blocks` | Optional leer; Mapping nur noch über `plant.ehal_bindings` / Consumer-`ehal_bindings` (EHAL-Com) |
| `live_scenario_id` | ID des **Live-Szenarios** in `backtesting_scenarios.json` (Default: `live`) |
| `earnie_env/config/components.json` | Technische Parameter Speicher und PV (`batteries[]`, `pv_systems[]`; Referenz über IDs) |
| `earnie_env/config/tariffs.json` | Laufzeit-Tarifkatalog (Bezug/Einspeise); Seed aus dem öffentlichen [`share/config/tariffs.json`](../../share/config/tariffs.json) |
| `earnie_env/config/house_profiles.json` | Standort (Geo/Zeitzone), Netznutzung Arbeitspreis, Planungs-Verbraucher (EV, WP, Waschmaschine, …); Referenz über `house_profile_id` |
| `earnie_env/config/backtesting_scenarios.json` | **Alle** Szenarien (Live + Varianten); einheitliches `settings`-Format |
| `scenario_explorer_conf` | Szenario-Explorer / Backtesting: `cons_data.csv`, Preisquelle; Zeitraum aus `cons_data`-Monaten |
| `flexible_consumers` | Legacy-Overlay (meist leer); Live-Verbraucher liegen in `house_profiles.json` |
| `appliance_recommendation` | Globale Sterne/Schwellen für manuelle Geräte (keine Geräte-Definitionen) |
| `planning_horizon` | MILP-Horizont (`sunrise_window` für Live) |

Vorlage für Szenarien: [`backtesting_scenarios.example.json`](../../share/config/backtesting_scenarios.example.json).

## Szenarien (Live und Szenario-Explorer)

- `live_scenario_id` in `config.json` wählt das Live-Szenario (Default-ID: `live`).
- `backtesting_scenarios.json` enthält **alle** Szenarien im gleichen Format (`id`, `label`, `settings` mit Entitäts-Referenzen oder — für Was-wäre-wenn — flachen Parametern).
- **Live-Betrieb** (`main.py`, Modus **Sunset-2-Sunset**) und **Szenario-Explorer** lösen dasselbe Live-Szenario über [`house_config/scenario_resolution.py`](../../house_config/scenario_resolution.py) auf.
- Weitere Szenarien in derselben Datei dienen nur dem Vergleich im Szenario-Explorer; sie ändern den Produktivbetrieb nicht.

## `scenario_explorer_conf`

| Feld | Bedeutung |
| ---- | --------- |
| `path_cons_data` | Stündliche Verbrauchs-/PV-Baseline (von `main.py` gepflegt); SE-Gesamtzeitraum |
| `path_price` | Optional: historische Börsenpreise (Energy-Charts-CSV) |
| `cons_data_retention_months` | Aufbewahrungsdauer der Stundenwerte |
| `cons_data_write_mode` | Schreibmodus (`hourly`) |
| `price_source` | `api` = Live-Preise; andere Werte für historische Preise aus CSV |
| `price_provider` | Legacy; API nutzt zuerst Energy-Charts (aWATTar-Stunden-Fallback) |
| `price_range` | `last_12_months`: 12 Kalendermonate bis zum letzten **vollständigen** Monat in `cons_data` (rückwärts definiert; Tage chronologisch) |
| `energy_charts_bzn` | Bidding Zone für die Energy-Charts-CSV (z. B. `DE-LU`) |

**Drei CSV-Ebenen (nicht vermischen):**

1. **`path_cons_data`** — Laufzeit-Treibstoff für Live und Szenario-Explorer
2. **Hausprofil-CSVs** (`total_profile_csv` / `pv_profile_csv` / `profile_csv`) — Planung / Ist-vs.-Modell (siehe [Verbrauchs-CSV](verbrauchs-csv.md))
3. **`path_consumption` / `path_production`** — entfernt (Datenmodell v3); früher Roh-Loxone-Paar-CSVs, nur für Zeitraumgrenzen

Details zu Preisen: [Preise & aWATTar](preise.md).

## Szenarienkonfigurator (Live-Szenario)

Im Abschnitt **Konfiguration** pflegt der **Szenarienkonfigurator** das Live-Szenario und weitere Varianten. Szenarien werden aus einer **Liste** gewählt; ↑/↓ daneben ändern die **Reihenfolge** der Nicht-Live-Szenarien (Live bleibt oben) für die Anzeige im Szenario-Explorer. Entitäten (Hausprofil, Batterie, PV, Tarife) wählen Sie per Dropdown (`battery_id`, PV, Tarife, Hausprofil). Pro Szenario steuert **aktiv für Szenario-Explorer** (`enabled`, Default true), ob die Variante in die SE-Rechnung eingeht. **Eigene Referenz ohne Optimierung** (`own_reference`) steuert, ob für das Szenario eine separate nicht-optimierte Referenz gerechnet wird; fehlt der Schalter, gilt Earnies Heuristik (eigene Referenz bei abweichendem Tarif/`pv_kwp`, Batterie-Varianten teilen die Live-Referenz). Vor den Tarif-Dropdowns gibt es einen gemeinsamen **Länder**-Filter (`land`: AT/DE/CH, **immer gesetzt**, kein „alle“; Vorgabe aus dem Standort des Hausprofils) für Bezug und Einspeise sowie getrennte **Typ**-Filter. Beim Einspeise-**Typ** erscheint `monthly_table` als **Monatspreis**. Ein Regionsfilter fehlt noch. Nach Tarifwahl erscheinen die Katalogparameter read-only (inkl. `supplier_id` und ungefährer Monatsgebühr). Zusätzlich: **Eigener Festpreis** (`__user_fixed__` mit `user_import_cent_kwh` / `user_export_cent_kwh` am Szenario — siehe [Preise](preise.md)). IDs landen im jeweiligen Szenario in `backtesting_scenarios.json`. Der **Name** des Live-Szenarios (`live_scenario_id` in `config.json`, Default-ID: `live`) ist fest und lässt sich nicht umbenennen oder entfernen.

## Weiterlesen

- [Speichern / Laden](speichern-laden.md)
- [PV & Batterie](batterie-pv.md)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Verbrauchs-CSV](verbrauchs-csv.md)
- [Preise & aWATTar](preise.md)
- [Loxone-Signale](../referenz/loxone-signals.md)
