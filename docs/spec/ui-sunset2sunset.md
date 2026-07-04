# Spezifikation: UI-Modus „Sunset-2-Sunset“

**Version:** 0.6.1  
**Status:** Phase 1 UI umgesetzt (2026-07-04); Phase 2 (Charts) teilweise — Daten-Schicht v0.6, Hold-Forward-Abschaffung offen; Phase 3–4 offen  
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
| Grau | SA₀ → letzter **abgeschlossener** 15-Min-Slot (siehe §6 — ab x:15 inkl. vergangene Viertelstunden der laufenden Stunde) |
| Neutral | offener Bereich ab letztem grauen Slot bis erster extrapolierter Preis (verbleibende Viertelstunden der laufenden Stunde mit MILP-Soll; danach stündliche MILP-Slots) |
| Grün | erster Slot mit `Preis extrapoliert == true` → **Fensterrand** (SA₁ bzw. SA₂) |

**Grenze grau/neutral in der laufenden Stunde**

| Uhrzeit | Grau endet bei | Neutral beginnt mit |
|---------|----------------|---------------------|
| x:00–x:14 | letzte **volle** Stunde (wie bisher) | einem stündlichen MILP-Slot für die laufende Stunde |
| ab x:15 | letztem abgeschlossenen 15-Min-Slot | den verbleibenden Viertelstunden der laufenden Stunde (Soll aus MILP-Stunde 0) |

Grün ersetzt die bisherige Zone „Vorausschau nach SOC-Anker“ (Phase 4 `planning-horizon-sunset.md`).

## 6. Daten & Auflösung

| Bereich | Quelle | Auflösung |
|---------|--------|-----------|
| Vollständig vergangene Stunden | `optimization_history.jsonl` (via `history_timeline`) | 15 min (Log-Ist) |
| Laufende Stunde, vor x:15 | Live-MILP Stunde 0 + `main.py`-Overlay | 1 h (wie bisher Echtzeit; Anteile bis x:15 unsichtbar) |
| Laufende Stunde, ab x:15 | Log (abgeschlossene Viertelstunden) + MILP Stunde 0 (verbleibende Viertelstunden) | 15 min |
| Ab nächster voller Stunde | Live-MILP + `main.py`-Overlay | 1 h |

### Laufende Stunde ab x:15

Ab Minute **15** der laufenden Stunde wird diese im **15-Minuten-Takt** dargestellt (Slots x:00, x:15, x:30, x:45):

| Viertelstunde | Status | Befüllung |
|---------------|--------|-----------|
| bereits abgeschlossen | Vergangenheit (grau) | Produktiv-Log (`optimization_history.jsonl`) |
| noch offen | Zukunft innerhalb der Stunde (neutral) | **konstant** die Soll-Werte der aktuellen MILP-Stunde 0 (keine Interpolation, kein stündlicher Aggregat-Slot) |

Die Simulations-Tabelle und die Charts nutzen dieselbe Slot-Auflösung und dieselben Grenzen.

### Fehlende Log-Slots

Viertelstunden-Slots im **grauen Bereich** ohne Eintrag in `optimization_history.jsonl`:

| Aspekt | Verhalten |
|--------|-----------|
| Werte | **leer** (`null` / keine Anzeige) — **kein** Hold-Forward, **keine** Übernahme älterer Messwerte |
| Kennzeichnung | **Orange** Hintergrund in Simulations-Tabelle und Charts (einheitliche Farbe) |
| Kumulativ | Kosten-/Verbrauchssummen zählen fehlende Slots **nicht** mit (Lücken in Kurven) |

Hold-Forward (bisher „hellorange / gehalten“) gilt im S-2-Modus **nicht**. Fehlende Daten bleiben sichtbar als Lücke.

**Chart 1 (grau):** Ist aus Log — SOC, Verbrauch, PV, Batterie/Flex, Preis zum Laufzeitpunkt. Keine rückwirkende MILP-Simulation.

**Chart 2:** getrennt — „Ist bisher“ (Log, 15 min, inkl. abgeschlossene Viertelstunden der laufenden Stunde ab x:15) und „Prognose optimiert“ (Soll-Viertelstunden der laufenden Stunde ab x:15, danach MILP ab nächster voller Stunde); kein künstliches Zusammenfügen der Kurven.

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

- MILP-Horizont: [planning-horizon-sunset.md](planning-horizon-sunset.md) — Jetzt → **SA₂** (Sonnenaufgang, identisch UI-Segment SA₁→SA₂ Ende)
- Produktiv-Log: `runtime_store/history_timeline.py`, `runtime/optimization_history.jsonl` (grauer Bereich ab **Phase 2**)

## Änderungshistorie

| Datum | Version | Inhalt |
|-------|---------|--------|
| 2026-07-04 | 0.6.1 | Fehlende Log-Slots: orange markieren, keine Hold-Forward-Befüllung |
| 2026-07-04 | 0.6 | Laufende Stunde ab x:15 im 15-Min-Takt: Log für vergangene Viertelstunden, konstantes MILP-Soll für offene; vor x:15 unverändert 1h-MILP |
| 2026-07-04 | 0.5 | Erstfassung Phase 1 UI |
