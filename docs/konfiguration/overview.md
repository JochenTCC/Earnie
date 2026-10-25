# Konfiguration – Überblick

Die zentrale Datei ist `earnie_env/config/config.json`. Als Ausgangspunkt dient [`share/config/config.example.json`](../../share/config/config.example.json); der Bootstrap kopiert fehlende Dateien. Siehe auch [Speichern / Laden](speichern-laden.md) und [Private Haus-Config](../einrichtung/private-env.md).

## Schema und Editor-Hilfe

Am Anfang von `config.json` steht der Verweis auf das Schema:

```json
"$schema": "./config.schema.json"
```

Damit zeigen Cursor und VS Code für viele Felder **Hover-Beschreibungen** aus [`share/config/config.schema.json`](../../share/config/config.schema.json) an. Die folgenden Kapitel liefern mehr Kontext.

## Hauptblöcke

| Block | Zweck |
| ----- | ----- |
| `system` | Timeouts für HTTP und den Optimierungszyklus |
| `market_prices` | Strategie für fehlende Zukunftspreise (`forecast` / `mirror`), siehe [Preise](preise.md) |
| `ui` | Streamlit-Port, Refresh-Intervalle, optionale Dev-Seiten |
| `loxone_blocks` | Optional, darf leer bleiben; das Mapping läuft nur noch über `plant.ehal_bindings` bzw. die `ehal_bindings` der Verbraucher (EHAL-Com) |
| `live_scenario_id` | ID des **Live-Szenarios** in `backtesting_scenarios.json` (Default: `live`) |
| `earnie_env/config/components.json` | Technische Parameter für Speicher und PV (`batteries[]`, `pv_systems[]`); Referenz über IDs |
| `earnie_env/config/tariffs.json` | Laufzeit-Tarifkatalog (Bezug/Einspeise); Seed aus dem öffentlichen [`share/config/tariffs.json`](../../share/config/tariffs.json) |
| `earnie_env/config/house_profiles.json` | Standort (Geo/Zeitzone), Arbeitspreis der Netznutzung, Planungs-Verbraucher (EV, WP, Waschmaschine, …); Referenz über `house_profile_id` |
| `earnie_env/config/backtesting_scenarios.json` | **Alle** Szenarien (Live und Varianten) im einheitlichen `settings`-Format |
| `scenario_explorer_conf` | Szenario-Explorer / Backtesting: `cons_data.csv` und Preisquelle; der Zeitraum ergibt sich aus den Monaten in `cons_data` |
| `appliance_recommendation` | Globale Sterne und Schwellen für manuelle Geräte (keine Geräte-Definitionen) |
| `planning_horizon` | MILP-Horizont (`sunrise_window` für Live) |

Vorlage für Szenarien: [`backtesting_scenarios.example.json`](../../share/config/backtesting_scenarios.example.json).

## Szenarien (Live und Szenario-Explorer)

- **Auswahl:** `live_scenario_id` in `config.json` legt das Live-Szenario fest (Default-ID: `live`).
- **Format:** `backtesting_scenarios.json` enthält **alle** Szenarien im gleichen Format: `id`, `label` und `settings`. Die `settings` enthalten Entitäts-Referenzen oder, für Was-wäre-wenn-Varianten, flache Parameter.
- **Gemeinsame Auflösung:** Der Live-Betrieb (`main.py`, Modus **Sunset-2-Sunset**) und der **Szenario-Explorer** lösen dasselbe Live-Szenario über [`house_config/scenario_resolution.py`](../../house_config/scenario_resolution.py) auf.
- **Weitere Szenarien:** Zusätzliche Einträge in derselben Datei dienen nur dem Vergleich im Szenario-Explorer. Den Produktivbetrieb ändern sie nicht.

## `scenario_explorer_conf`

| Feld | Bedeutung |
| ---- | --------- |
| `path_cons_data` | Stündliche Verbrauchs- und PV-Baseline (von `main.py` gepflegt); bestimmt den Gesamtzeitraum im Szenario-Explorer |
| `path_price` | Optional: historische Börsenpreise (Energy-Charts-CSV) |
| `cons_data_retention_months` | Aufbewahrungsdauer der Stundenwerte |
| `cons_data_write_mode` | Schreibmodus (`hourly`) |
| `price_source` | `api` = Live-Preise; andere Werte für historische Preise aus CSV |
| `price_provider` | Legacy; die API nutzt zuerst Energy-Charts (Fallback auf aWATTar-Stundenpreise) |
| `price_range` | `last_12_months`: 12 Kalendermonate bis zum letzten **vollständigen** Monat in `cons_data` (rückwärts definiert, Tage chronologisch) |
| `energy_charts_bzn` | Bidding Zone für die Energy-Charts-CSV (z. B. `DE-LU`) |

**Drei CSV-Ebenen**, die getrennt bleiben:

1. **`path_cons_data`:** Laufzeitdaten für den Live-Betrieb und den Szenario-Explorer.
2. **Hausprofil-CSVs** (`total_profile_csv` / `pv_profile_csv` / `profile_csv`): Planung sowie Vergleich von Ist-Werten und Modell (siehe [Verbrauchs-CSV](verbrauchs-csv.md)).
3. **`path_consumption` / `path_production`:** entfernt (Datenmodell v3). Früher waren das Paare von Roh-CSVs aus Loxone, die nur die Zeitraumgrenzen lieferten.

Details zu Preisen: [Preise und Marktdaten](preise.md).

## Szenarienkonfigurator (Live-Szenario)

Im Abschnitt **Konfiguration** pflegt der **Szenarienkonfigurator** das Live-Szenario und weitere Varianten.

- **Auswahl und Reihenfolge:** Szenarien werden aus einer **Liste** gewählt. Die Pfeile ↑/↓ daneben ändern die **Reihenfolge** der übrigen Szenarien für die Anzeige im Szenario-Explorer; das Live-Szenario bleibt oben.
- **Entitäten:** Hausprofil, Batterie, PV und Tarife werden per Dropdown gewählt (`battery_id`, PV, Tarife, Hausprofil).
- **aktiv für Szenario-Explorer** (`enabled`, Default true): steuert, ob die Variante in die Berechnung des Szenario-Explorers eingeht.
- **Eigene Referenz ohne Optimierung** (`own_reference`): steuert, ob Earnie für das Szenario eine separate, nicht optimierte Referenz rechnet. Fehlt der Schalter, gilt Earnies Heuristik: Eine eigene Referenz gibt es bei abweichendem Tarif oder `pv_kwp`; Batterie-Varianten teilen sich die Referenz des Live-Szenarios.
- **Tarif-Filter:** Vor den Tarif-Dropdowns steht ein gemeinsamer **Länder**-Filter für Bezug und Einspeise (`land`: AT/DE/CH). Er ist **immer gesetzt**, eine Option „alle“ gibt es nicht; die Vorgabe stammt aus dem Standort des Hausprofils. Dazu kommen getrennte **Typ**-Filter. Beim Einspeise-**Typ** erscheint `monthly_table` als **Monatspreis**. Ein Regionsfilter fehlt noch.
- **Tarifparameter:** Nach der Tarifwahl erscheinen die Katalogparameter schreibgeschützt, einschließlich `supplier_id` und ungefährer Monatsgebühr.
- **Eigener Festpreis:** `__user_fixed__` mit `user_import_cent_kwh` / `user_export_cent_kwh` am Szenario (siehe [Preise](preise.md)).

Die gewählten IDs landen im jeweiligen Szenario in `backtesting_scenarios.json`. Der **Name** des Live-Szenarios (`live_scenario_id` in `config.json`, Default-ID: `live`) ist fest und lässt sich weder umbenennen noch entfernen.

## Weiterlesen

- [Speichern / Laden](speichern-laden.md)
- [PV & Batterie](batterie-pv.md) (inkl. Anlagen-Topologie und der drei Fragen für den Live-Pfad)
- [Flexible Verbraucher](flexible-verbraucher.md)
- [Verbrauchs-CSV](verbrauchs-csv.md)
- [Preise und Marktdaten](preise.md)
- [Loxone-Signale](../referenz/loxone-signals.md)
