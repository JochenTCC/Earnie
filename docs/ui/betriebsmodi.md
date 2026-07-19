# Betriebsmodi und Navigation

Die Streamlit-App nutzt **`st.navigation`** mit Seiten in Abschnitten — **kein** Sidebar-Radio „Betriebsmodus“ mehr. Welche Seiten sichtbar sind, steuert die Umgebungsvariable **`EARNIE_UI_MODES`** (Legacy-Alias: `ENERGY_OPTIMIZER_UI_MODES`).

```text
EARNIE_UI_MODES=sunset2sunset,scenario_explorer
```

Ohne diese Variable stehen in der Entwicklung **Sunset-2-Sunset** (Seite **Monitor**) und **Szenario-Explorer** zur Verfügung (optional **Preis-Prognose (Dev)**). Gültige Keys: `sunset2sunset`, `scenario_explorer`, `price_forecast` — **kein** Alias `live` oder `historical`. Frühere Keys `backtesting` und `scenario_exploration` sind umbenannt; bei alter Env-Konfiguration erscheint ein Sidebar-Hinweis. Details zum Deployment: [Betrieb](../einrichtung/betrieb.md).

| Key | Seite | Abschnitt | Produktion |
|-----|-------|-----------|------------|
| `sunset2sunset` | **Monitor**, **Manuelle Geräte** | Betrieb | ja (Hauptansicht; ohne Key kein Betrieb-Abschnitt) |
| `scenario_explorer` | **Szenario-Explorer** | Analyse | optional (Dev / Community Cloud) |
| `price_forecast` | **Preis-Prognose (Dev)** | Analyse | Dev-only |

Beispiel Community Cloud (nur Analyse): `EARNIE_UI_MODES=scenario_explorer` — Betrieb entfällt.

Weitere Seiten (nicht über `EARNIE_UI_MODES` gesteuert): **Hauskonfigurator**, **Szenarieneditor**, **Live-Konfiguration**, **Optimierer-Dienst**, **Loxone-Kommunikation**, **Verbraucheranalyse** — Freischaltung abhängig vom Setup-Fortschritt (`ui/setup_readiness.py`).

In der Sidebar: App-Version, Setup-Hinweise und **„Konfiguration speichern / laden“** (ZIP-Export/Import der Config-Sidecars und `uploads/` — siehe [Speichern / Laden](../konfiguration/speichern-laden.md)).

### Navigationsabschnitte (nach vollständiger Einrichtung)

| Abschnitt | Seiten |
|-----------|--------|
| **Betrieb** | Monitor, Manuelle Geräte |
| **Analyse** | Szenario-Explorer (wenn freigeschaltet), Preis-Prognose (Dev), Verbraucheranalyse |
| **Planung** | Hauskonfigurator, Szenarieneditor |
| **Echtzeit-Umgebung** | Live-Konfiguration, Optimierer-Dienst, Loxone-Kommunikation |

Während der Greenfield-Ersteinrichtung sind zunächst nur **Planung** und **Echtzeit-Umgebung** sichtbar.

Spezifikation: [UI Sunset-2-Sunset](../spec/ui-sunset2sunset.md) (v0.6.2). Chart- und Panel-Details: [Charts & Panels](charts.md).

## Sunset-2-Sunset (Seite Monitor)

**Zweck:** Einheitliches Produktiv-Cockpit ohne Grenze zwischen Live und Historie. Vergangenheit aus dem Produktiv-Log (`optimization_history.jsonl`), Gegenwart und Vorausschau aus dem **Produktiv-Snapshot** (`live_optimization_debug.json`, geschrieben von `main.py`) — in zwei benachbarten Sonnenaufgang-Segmenten navigierbar.

**Ersetzt:** die früheren Modi **Echtzeit** und **Historischer Tag** sowie den Button **Produktiv-Archiv**. Es gibt **keine Nachrechnung** beliebiger Kalendertage im S-2-Modus (geplant als Dev-Feature in Szenario-Explorer).

### Sonnenaufgang-Anker SA₀, SA₁, SA₂

Immer **Sonnenaufgang** (nicht Sonnenuntergang):

| Situation | SA₀ | SA₁ | SA₂ |
|-----------|-----|-----|-----|
| Gerade in der SA-Stunde | **jetzt** | morgen | übermorgen |
| Jede andere Stunde | letzter SA (Vergangenheit) | nächster SA | übernächster SA |

### Chart-Fenster & Navigation

Zwei umschaltbare Segmente (~24 h):

| Index | Fenster | Standard |
|-------|---------|----------|
| 0 | SA₀ → SA₁ | ja (App-Start) |
| 1 | SA₁ → SA₂ | per „Vor →“ |

| Steuerung | Verhalten |
|-----------|-----------|
| ← Zurück | Weitere SA-Zyklen zurück, bis `optimization_history.jsonl` reicht |
| Vor → | Wechsel SA₀→SA₁ ↔ SA₁→SA₂; in SA₁→SA₂ deaktiviert |
| Navigation | Kompakte Buttons **zwischen Chart 1 und Chart 2** |

Beschriftung z. B. „SA₀→SA₁ (Live)“ / „SA₁→SA₂ (Vorausschau)“ plus Datumsbereich. Vertikale Marker **SA₀**, **SA₁**, **SA₂** im Chart; **Jetzt** nur im Live-Segment SA₀→SA₁.

### Datenquellen

| Bereich | Quelle |
|---------|--------|
| Vergangenheit (grau) | Produktiv-Log, 15-Min-Slots |
| Laufende Stunde | Produktiv-Snapshot Stunde 0 (Overlay bereits in `main.py` angewendet; Auflösung ab x:15: 15 min) |
| Vorausschau (neutral/grün) | Produktiv-Snapshot bis Fensterrand SA₁ bzw. SA₂ |

Stunde 0 stammt aus dem **Produktiv-Durchlauf** (`main.py` → `live_optimization_debug.json`). Fehlende Log-Slots bleiben **leer** (orange markiert, kein Hold-Forward).

**main.py aus:** Snapshot ≤ 1 h alt → Anzeige mit Hinweis; älter → optional **einmalige** UI-Simulation (opt-in, kein forecast.solar im Normalbetrieb).

### Live-Szenario (Entitäts-Referenzen)

PV-, Batterie- und Einspeise-Parameter werden über Entitäts-IDs im **Live-Szenario** (`backtesting_scenarios.json`, gewählt via `live_scenario_id` in `config.json`) konfiguriert — Seite **Live-Konfiguration** oder **Szenarieneditor**. **Kein** adaptives PV-Tuning mehr — neuer Adaptions-Ansatz separat im Backlog.

### Panels

| Panel | Verhalten |
|-------|-----------|
| Charts 1 & 2 | Leistung/SoC/Preis; kumulierte Kosten & Verbrauch (Ist vs. Prognose getrennt) |
| Simulations-Tabelle | Rohdaten des sichtbaren Fensters; orange = fehlende Log-Einträge |
| Energievergleich | Expander: Baseline vs. Optimierung |
| Sankey | immer (aktuelle Loxone-Daten) |
| Countdown / Optimierungs-Takt | immer |
| Auto-Refresh | nur Fenster SA₀→SA₁ |

Details: [Charts & Panels](charts.md).

### Kennzahlen-Horizont

Ersparnis-, Kosten-Kennzahlen und Energievergleich beziehen sich auf **Jetzt → SA₂** (voller MILP-Planungshorizont). Die Chart-Segmente SA₀→SA₁ und SA₁→SA₂ sind **Darstellungsfenster** — kumulierte Kurven darin sind Ausschnitte, keine eigene Matching-Periode.

## Szenario-Explorer

**Zweck:** Langzeit-Auswertung aus dem Log von `scripts/run_backtesting.py` (`runtime/backtesting_log.json`).

**Keine Cockpit-Parameter** — nur Auswahl von Szenarien/Monaten in der Hauptansicht.

**Inhalt:**

- Gesamt- und Monatskostenvergleich (Referenz vs. optimierte Szenarien)
- Plausibilisierung und Stundenverläufe pro Monat

**Kein** S-2-Navigation, **kein** Produktiv-Log-Merge. Nicht für den täglichen Produktivbetrieb gedacht.

Geplant (Dev-only): Nachrechnung eines beliebigen Kalendertags — ersetzt den früheren Modus **Historischer Tag**.

### Gesamtkosten — Jahres Verbrauch

Tabelle **Gesamtkosten**: Spalten `Szenario`, `Jahres Verbrauch [kWh]`, `Jahres Kosten [€]`, `Δ vs Referenz [€]` (Delta immer gegen die Live-Referenz-Zeile).

**Datenquellen für `Jahres Verbrauch [kWh]`** (UI: `build_annual_cost_rows` / `_jahres_kwh_for_row`):

| Zeile | kWh-Quelle |
| ----- | ---------- |
| `historical_reference` (Historisch) | `reference_kwh_for_period` → Summe `cons_data` `total_kw` über `meta.period` |
| Szenario-Referenz (`ref__…`) | `plausibility[<parent>].consumption_totals.historical_kwh` (Summe der 24h-Fenster) |
| Optimiertes Szenario | `plausibility[<id>].consumption_totals.optimized_kwh` |

Mit Hausprofil ist `consumption_source` typisch `profile_spec`: Fenster-Referenz = Spec-Last (Jahresverbrauch/Zeitpläne), nicht der Zähler. Historisch bleibt bewusst am Ist-Zähler — Abweichungen zu den übrigen Zeilen sind erwartbar, wenn Ist ≠ Modell. Kurzfassung in der UI-Caption unter der Tabelle; Anwendertext: [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#gesamtkosten-jahres-verbrauch-kwh).

