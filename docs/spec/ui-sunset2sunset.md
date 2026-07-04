# Spezifikation: UI-Modus „Sunset-2-Sunset“

**Version:** 0.5  
**Status:** Spezifiziert (2026-07-04), Implementierung offen  
**Ersetzt:** Streamlit-Modi „Echtzeit“ und „Historischer Tag“, Button „Produktiv-Archiv“, getrennte Live/History-Umschaltung

## 1. Ziel

Ein einheitlicher Produktiv-Cockpit-Modus ohne Grenze zwischen Live und Historie: Vergangenheit aus dem Produktiv-Log, Gegenwart und Vorausschau aus der Live-MILP — in zwei benachbarten Sonnenaufgang-Segmenten navigierbar.

**Keine Nachrechnung** im S-2-Modus (beliebiger Kalendertag → später Backtesting, Dev-only).

## 2. Betriebsmodi

| Modus | Key | Prod |
|-------|-----|------|
| Sunset-2-Sunset | `sunset2sunset` | ja |
| Backtesting | `backtesting` | optional Dev |

`ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting` (Prod). Kein Alias `live`.

**Sidebar:** wie bisher Echtzeit (PV-, Batterie-, Einspeiseparameter, Runtime) — **ohne** adaptives PV-Tuning (entfernen; neuer Adaptions-Ansatz separat im Backlog).

## 3. Sonnenaufgang-Anker SA₀, SA₁, SA₂

Immer **Sonnenaufgang** (nicht Sonnenuntergang; abweichend von MILP-Spec SU₁/SU₂).

| Situation | SA₀ | SA₁ | SA₂ |
|-----------|-----|-----|-----|
| Gerade in der SA-Stunde | **jetzt** | morgen | übermorgen |
| Jede andere Stunde | letzter SA (Vergangenheit) | nächster SA | übernächster SA |

## 4. Chart-Fenster & Navigation

Zwei umschaltbare Segmente (~24 h):

| Index | Fenster | Standard |
|-------|---------|----------|
| 0 | SA₀ → SA₁ | ja (App-Start) |
| 1 | SA₁ → SA₂ | per „Vor →“ |

| Steuerung | Verhalten |
|-----------|-----------|
| ← Zurück | Weitere SA-Zyklen zurück, max. bis `optimization_history.jsonl` reicht |
| Vor → | Wechsel SA₀→SA₁ ↔ SA₁→SA₂; in SA₁→SA₂ deaktiviert |
| Produktiv-Archiv | entfällt |

Beschriftung z. B. „SA₀→SA₁ (Live)“ / „SA₁→SA₂ (Vorausschau)“ plus Datumsbereich.

## 5. Hintergrundzonen

| Zone | Zeitraum |
|------|----------|
| Grau | SA₀ → letzte **abgeschlossene** volle Stunde |
| Neutral | aktuelle volle Stunde bis erster extrapolierter Preis |
| Grün | erster Slot mit `Preis extrapoliert == true` → **Fensterrand** (SA₁ bzw. SA₂) |

Grün ersetzt die bisherige Zone „Vorausschau nach SOC-Anker“ (Phase 4 `planning-horizon-sunset.md`).

## 6. Daten & Auflösung

| Bereich | Quelle | Auflösung |
|---------|--------|-----------|
| Grau | `optimization_history.jsonl` (via `history_timeline`) | 15 min, nur abgeschlossene Stunden |
| Ab aktueller voller Stunde | Live-MILP + `main.py`-Overlay Stunde 0 | 1 h |
| Laufende Stunde | Anteile bis Stundenwechsel unsichtbar | wie bisher Echtzeit |

**Chart 1 (grau):** Ist aus Log — SOC, Verbrauch, PV, Batterie/Flex, Preis zum Laufzeitpunkt. Keine rückwirkende MILP-Simulation.

**Chart 2:** getrennt — „Ist bisher“ (Log, 15 min) und „Prognose optimiert“ (MILP ab voller Stunde); kein künstliches Zusammenfügen der Kurven.

## 7. Live-Panels

| Panel | Verhalten |
|-------|-----------|
| Sankey | immer (aktuelle Loxone-Daten) |
| Countdown | immer |
| Auto-Refresh | nur Fenster SA₀→SA₁ |

## 8. Follow-ups (nicht v0.5)

- **Soll/Ist-Overlay** im grauen Bereich: Stufe 1 Log-Soll vs. `consumption_snapshot`; Stufe 2 kontinuierliches Haus-Ist
- **Nachrechnung** (ex Historischer Tag) ins Backtesting, Dev-only
- **Preis-Spiegelung:** optional Mittelung über mehrere Tage (`data/market_prices.py`)

## 9. Bezug

- MILP-Horizont: [planning-horizon-sunset.md](planning-horizon-sunset.md) (Jetzt → SU₂; UI zeigt SA-Segmente)
- Produktiv-Log: `runtime_store/history_timeline.py`, `runtime/optimization_history.jsonl`
