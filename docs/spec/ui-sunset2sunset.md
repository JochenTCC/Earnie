# Spezifikation: UI-Modus „Sunset-2-Sunset“

**Version:** 0.8.0  
**Status:** Epic abgeschlossen (2026-07-05); Phasen 1–4 umgesetzt (P4a–P4c Docs & Tests; P4d entfallen)  
**Ersetzt:** Streamlit-Modi „Echtzeit“ und „Historischer Tag“, Button „Produktiv-Archiv“, getrennte Live/History-Umschaltung, UI-seitige Standard-Live-MILP

## 1. Ziel

Ein einheitlicher Produktiv-Cockpit-Modus ohne Grenze zwischen Live und Historie: Vergangenheit aus dem Produktiv-Log, Gegenwart und Vorausschau aus dem **Produktiv-Snapshot** (`live_optimization_debug.json`, geschrieben von `main.py`) — in zwei benachbarten Sonnenaufgang-Segmenten navigierbar.

**Keine Nachrechnung** im S-2-Modus (beliebiger Kalendertag → später Backtesting, Dev-only).

## 2. Betriebsmodi

| Modus | Key | Prod |
|-------|-----|------|
| Sunset-2-Sunset | `sunset2sunset` | ja |
| Szenario-Explorer | `scenario_explorer` | optional Dev |

`ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,scenario_explorer` (Prod). Kein Alias `live`, `backtesting` oder `scenario_exploration`.

**Sidebar:** Live-Szenario (PV-, Batterie-, Einspeiseparameter über Entitäts-Referenzen) — **ohne** adaptives PV-Tuning (entfernen; neuer Adaptions-Ansatz separat im Backlog).

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

**Chart-Marker (P3b):** Vertikale Linien **SA₀**, **SA₁**, **SA₂** (Sonnenaufgang), jeweils nur wenn der Anker im sichtbaren Segment liegt. **Jetzt** (gestrichelt) nur im Live-Segment SA₀→SA₁ (`cycle_offset=0`, `segment_index=0`). Keine SU-Marker mehr.

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
| Laufende Stunde, vor x:15 | Produktiv-Snapshot Stunde 0 (`live_optimization_debug.json`) | 1 h (Overlay in main.py; Anteile bis x:15 unsichtbar) |
| Laufende Stunde, ab x:15 | Log (abgeschlossene Viertelstunden) + Snapshot Stunde 0 (verbleibende Viertelstunden) | 15 min |
| Ab nächster voller Stunde | Produktiv-Snapshot | 1 h |

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

**Kennzahlen-Horizont (BL Ziel, Energievergleich, Ersparnis-Summen):** **Jetzt → SA₂** (voller MILP-Planungshorizont). BL Ziel und Optimierung werden über diesen Zeitraum auf gleiche Flex-Energie ausgerichtet. Die Chart-Segmente SA₀→SA₁ und SA₁→SA₂ sind **Darstellungsfenster** — kumulierte Kurven darin sind Ausschnitte, keine eigene Matching-Periode. Ist-Anteil (Log) unterliegt dem Matching nicht.

## 7. Live-Panels

| Panel | Verhalten |
|-------|-----------|
| Sankey | immer (aktuelle Loxone-Daten) |
| Countdown | immer |
| Auto-Refresh | nur Fenster SA₀→SA₁ |

### 7.1 UI-Layout (Follow-up, umgesetzt 2026-07-05)

Kompaktere Chart-UI; Details in [docs/ui/charts.md](../ui/charts.md).

| Element | Verhalten |
|---------|-----------|
| Sidebar (oben) | App-Version als Caption (`app.py`) |
| Seitentitel | Modus-Scope; Scope-Erklärung im **?** (`ui/help_hint.py`) |
| Chart 1 | Segment-Label als Überschrift + **?** (Zonen, Navigation); kein separates Segment-Banner |
| Navigation | ←/→ **zwischen Chart 1 und Chart 2**, schmal, ohne Caption dazwischen |
| Chart 2 | Überschrift + **?** (Ist vs. Prognose, orange Lücken) statt Caption unter dem Chart |
| Sync-Wartezeit | Status sichtbar (`st.info`/`st.caption`); Erklärung im **?** (`ui/main_py_sync.py`) |
| Simulations-Tabelle / Energievergleich | Expander unverändert (Erklär-Texte bleiben im Expander) |
| Footer | Trennlinie → **Datenbasis**-Expander → Optimierungs-Takt / Countdown |

## 8. Follow-ups (nicht v0.5)

- **Soll/Ist-Abweichung:** eigenes Epic **Soll-Ist** — [soll-ist-abweichung.md](soll-ist-abweichung.md) (Stufe 1 Log-Soll vs. `consumption_snapshot`; Stufe 2 kontinuierliches Haus-Ist als Follow-up)
- **Nachrechnung** (ex Historischer Tag) ins Backtesting, Dev-only
- **Preis-Prognose:** EU-Wetter & Erzeugung für grüne Zone — [price-forecast-renewables.md](price-forecast-renewables.md)
- **UI-Layout optional:** kompakteres Button-CSS; Mobil-Check — siehe Backlog

## 9. Bezug

- MILP-Horizont: [planning-horizon-sunset.md](planning-horizon-sunset.md) — Jetzt → **SA₂** (Sonnenaufgang, identisch UI-Segment SA₁→SA₂ Ende)
- Produktiv-Log: `runtime_store/history_timeline.py`, `runtime/optimization_history.jsonl` (grauer Bereich ab **Phase 2**)

## Änderungshistorie

| Datum | Version | Inhalt |
|-------|---------|--------|
| 2026-07-05 | 0.7.0 | Epic-Abschluss Phase 4: Betriebsmodi-Doku, Deployment-Querverweise, Navigationstests (P4a–P4c); P4d entfallen |
| 2026-07-05 | 0.6.3 | Follow-up UI-Layout: Navigation zwischen Charts, ?-Hilfen, Footer-Datenbasis (§7.1) |
| 2026-07-05 | 0.6.2 | P3b: Chart-Marker SA₀/SA₁/SA₂; Jetzt nur Live SA₀→SA₁; P3d Horizont Jetzt→SA₂ |
| 2026-07-04 | 0.6.1 | Fehlende Log-Slots: orange markieren, keine Hold-Forward-Befüllung |
| 2026-07-04 | 0.6 | Laufende Stunde ab x:15 im 15-Min-Takt: Log für vergangene Viertelstunden, konstantes MILP-Soll für offene; vor x:15 unverändert 1h-MILP |
| 2026-07-04 | 0.5 | Erstfassung Phase 1 UI |
