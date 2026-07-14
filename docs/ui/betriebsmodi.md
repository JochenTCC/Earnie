# Betriebsmodi und Navigation

Die Streamlit-App nutzt **`st.navigation`** mit Seiten in Abschnitten — **kein** Sidebar-Radio „Betriebsmodus“ mehr. Welche Seiten sichtbar sind, steuert die Umgebungsvariable **`EARNIE_UI_MODES`** (Legacy-Alias: `ENERGY_OPTIMIZER_UI_MODES`).

```text
EARNIE_UI_MODES=sunset2sunset,scenario_exploration
```

Ohne diese Variable stehen in der Entwicklung **Sunset-2-Sunset** (Seite **Monitor**) und **Scenario-Exploration** zur Verfügung (optional **Preis-Prognose (Dev)**). Gültige Keys: `sunset2sunset`, `scenario_exploration`, `price_forecast` — **kein** Alias `live`, `historical` oder `backtesting`. Der frühere Key `backtesting` ist umbenannt; bei alter Env-Konfiguration erscheint ein Sidebar-Hinweis. Details zum Deployment: [Betrieb](../einrichtung/betrieb.md).

| Key | Seite | Abschnitt | Produktion |
|-----|-------|-----------|------------|
| `sunset2sunset` | **Monitor** | Betrieb | ja (Hauptansicht) |
| `scenario_exploration` | **Scenario-Exploration** | Analyse | optional (Dev) |
| `price_forecast` | **Preis-Prognose (Dev)** | Analyse | Dev-only |

Weitere Seiten (nicht über `EARNIE_UI_MODES` gesteuert): **Hauskonfigurator**, **Szenarieneditor**, **Live-Konfiguration**, **Manuelle Geräte**, **Verbraucheranalyse** — Freischaltung abhängig vom Setup-Fortschritt (`ui/setup_readiness.py`).

### Navigationsabschnitte (nach vollständiger Einrichtung)

| Abschnitt | Seiten |
|-----------|--------|
| **Betrieb** | Monitor, Manuelle Geräte |
| **Analyse** | Scenario-Exploration (wenn freigeschaltet), Preis-Prognose (Dev), Verbraucheranalyse |
| **Planung** | Hauskonfigurator, Szenarieneditor |
| **Echtzeit-Umgebung** | Live-Konfiguration |

Während der Greenfield-Ersteinrichtung sind zunächst nur **Planung** und **Echtzeit-Umgebung** sichtbar.

Spezifikation: [UI Sunset-2-Sunset](../spec/ui-sunset2sunset.md) (v0.6.2). Chart- und Panel-Details: [Charts & Panels](charts.md).

## Sunset-2-Sunset (Seite Monitor)

**Zweck:** Einheitliches Produktiv-Cockpit ohne Grenze zwischen Live und Historie. Vergangenheit aus dem Produktiv-Log (`optimization_history.jsonl`), Gegenwart und Vorausschau aus der Live-MILP — in zwei benachbarten Sonnenaufgang-Segmenten navigierbar.

**Ersetzt:** die früheren Modi **Echtzeit** und **Historischer Tag** sowie den Button **Produktiv-Archiv**. Es gibt **keine Nachrechnung** beliebiger Kalendertage im S-2-Modus (geplant als Dev-Feature in Scenario-Exploration).

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
| Laufende Stunde | Live-MILP + `main.py`-Overlay (Auflösung ab x:15: 15 min) |
| Vorausschau (neutral/grün) | Live-MILP bis Fensterrand SA₁ bzw. SA₂ |

Stunde 0 der Simulation = Werte aus dem **Produktiv-Durchlauf** (`optimizer_run_state.json`), sofern zum aktuellen Viertelstunden-Slot passend. Fehlende Log-Slots bleiben **leer** (orange markiert, kein Hold-Forward).

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

## Scenario-Exploration

**Zweck:** Langzeit-Auswertung aus dem Log von `scripts/run_backtesting.py` (`runtime/backtesting_log.json`).

**Keine Cockpit-Parameter** — nur Auswahl von Szenarien/Monaten in der Hauptansicht.

**Inhalt:**

- Gesamt- und Monatskostenvergleich (Referenz vs. optimierte Szenarien)
- Plausibilisierung und Stundenverläufe pro Monat

**Kein** S-2-Navigation, **kein** Produktiv-Log-Merge. Nicht für den täglichen Produktivbetrieb gedacht.

Geplant (Dev-only): Nachrechnung eines beliebigen Kalendertags — ersetzt den früheren Modus **Historischer Tag**.

## Entfallene Modi

| Früher | Status |
|--------|--------|
| **Echtzeit** | Ersetzt durch **Sunset-2-Sunset** / Seite **Monitor** |
| **Historischer Tag** | Entfernt; Nachrechnung folgt in **Scenario-Exploration** (Dev-only) |
| Button **Produktiv-Archiv** | Entfernt; Vergangenheit über ←-Navigation in SA-Zyklen |
| Sidebar **Betriebsmodus** (Radio) | Entfernt; Seiten-Navigation über `st.navigation` |
| `EARNIE_UI_MODES=live` | Ungültig — Prod: `sunset2sunset,scenario_exploration` |
| `…,backtesting` | Umbenannt → `scenario_exploration`; Sidebar-Hinweis bei alter Konfiguration |
| `…,historical` | Ungültig; Sidebar-Hinweis bei alter Konfiguration |
