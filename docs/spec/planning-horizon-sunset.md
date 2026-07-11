# Spezifikation: Sunset-Planungshorizont & SOC-Anker am Sonnenaufgang

**Version:** 0.5  
**Status:** Phasen 1–5 abgeschlossen (2026-07-04); Horizontende SA₂ (§2.4) **umgesetzt 2026-07-04**

## 1. Ziel

Ersetzt den fixen 24-h-Rollhorizont im Live-Betrieb durch einen
PV-/Tagesrhythmus-orientierten Planungshorizont mit sinnvoller SOC-Randbedingung am Sonnenaufgang.
Der frühere Config-Parameter `battery_end_soc_equals_start` ist entfernt (2026-07-04).

Gemeinsame Anker-Benennung mit [UI Sunset-2-Sunset](ui-sunset2sunset.md): **SA₀/SA₁/SA₂ = Sonnenaufgang** (nicht Sonnenuntergang).

### Annahmen (gesichert)

- Batterie ist zum **Sonnenaufgang** praktisch leer (`SOC ≈ SOC_min`).
- Nachtladung aus dem Netz ist wirtschaftlich irrelevant (5 kWh, 6 kWp PV).
- Nach dem SOC-Anker-Sonnenaufgang ist der zweite „Sonnenumlauf“ bis Horizontende **frei** (Entscheidung A).

## 2. Planungsfenster (MILP)

### 2.1 Definition (Zielbild ab v0.5)

```
Horizont:   t_now  →  SA₂     (zweiter Sonnenaufgang im S-2-Sinne, identisch UI-Segment SA₁→SA₂ Ende)
SOC-Anker:  t_SR   = erster Sonnenaufgang mit t_SR > t_now   (hart SOC_min)
```

- **SA₂:** übernächster Sonnenaufgang gemäß `compute_sunrise_anchors()` in `data/planning_window.py` (gleiche Logik wie UI).
- **Sonnenzeiten:** astronomisch **official** aus `latitude` / `longitude` (Modul `astral`).
- **Zeitzone:** explizit als Parameter (`timezone_name`, z. B. `Europe/Vienna`).

**Sonnenuntergänge (SU₁, SU₂)** bleiben als **Marker** in Charts/Diagnose erhalten, definieren aber **nicht** das Horizontende.

### 2.2 SOC-Randbedingung (MILP)

| Slot | Regel |
|------|--------|
| `t_sunrise` = erster Sonnenaufgang mit `t_sunrise > t_now` | `e_batt[t] == SOC_min` (hart) |
| Übrige Slots inkl. Horizontende SA₂ | nur min/max-SOC |

### 2.3 Slot-Granularität

Stündlich (wie bisher). Implementierung: `data/planning_window.py`.

### 2.4 Horizontende SA₂ (2026-07-04)

| | v0.4 (veraltet) | v0.5 (Live) |
|---|----------------|-------------|
| Horizontende | `sunset_2` (SU₂) | **SA₂** (`compute_sunrise_anchors().sa2`) |
| aWATTar-Abruf | `planning_end=sunset_2` | `planning_end=SA₂` |
| UI SA₁→SA₂ | Lücke ohne MILP-Daten | vollständig aus Live-MILP |

**Umsetzung:** `compute_planning_window()` in `data/planning_window.py`; SU₁/SU₂ bleiben als Chart-Marker.

## 3. UI (Live-Chart) — ersetzt durch [UI Sunset-2-Sunset](ui-sunset2sunset.md)

Die Produktiv-UI nutzt seit Epic **UI Sunset-2-Sunset** die Segmente SA₀→SA₁ und SA₁→SA₂ (Sonnenaufgang-Anker). Dieser Abschnitt beschreibt nur noch den MILP-Horizont; Darstellung siehe UI-Spec v0.5.

**Phase 4 (alt):** sunrise→sunrise mit Zonenfarben — durch S-2-UI abgelöst.

## 4. Backtesting

Backtesting unterstützt zwei **explizit wählbare** Horizont-Modi (CLI `--horizon-mode`, kein `.env`-Schalter).
Standard bleibt `fixed_24h` (Abwärtskompatibilität).

### 4.1 Modus `fixed_24h` (Standard, bisheriges Verhalten)

```
Fenster:  [Anker − 24h, Anker)   mit Anker = E-Auto ready_by_hour
MILP End-SOC: Anker-SOC des Schritts (intern terminal_soc_percent = initial_soc)
SOC-Kette: End-SOC Fenster N → Start-SOC Fenster N+1
MILP-Horizont: 24 h (identisch zum Output-Fenster)
```

Kein Config-Schalter für End-SOC; Verhalten ist fest im Modus verankert (früher `battery_end_soc_equals_start`, entfernt).

### 4.2 Modus `sunrise_window` (Vergleich zu Live-Prod)

Pro Backtesting-Schritt (weiterhin **24 h Output** pro E-Auto-Anker, fairer Vergleich):

```
t_now     = Anker − 24h          (Fensterstart wie fixed_24h)
MILP      = Jetzt → SA₂          (SA₂ = Sonnenaufgang, vgl. §2.1 / UI-Spec)
SOC       = hart SOC_min am Sonnenaufgang innerhalb des MILP
Simulation= rollierend max. 24 h pro Schritt (wie fixed_24h; kein Durchsimulieren bis SA₂)
Output    = erste 24 h ab t_now   (Kosten/SoC-Kette wie bisher)
Daten     = historische Ist-Verbräuche/PV aus cons_data_hourly.csv
Geo/Zeit  = latitude/longitude aus aufgelöstem Live-Szenario (Hausprofil oder Szenario-Override)
```

**Performance:** Volle SA₂-Matrix (typ. ~40–48 h) würde pro Schritt mehr MILP-Läufe
in `simulate_horizon` erzeugen als nötig; Backtesting kürzt daher auf 24 h Simulations-Tiefe.
Der Sonnenaufgang-Index liegt im Sommer-Halbjahr stets innerhalb dieser 24 h.

**Code-Stand:** Backtesting und Live nutzen bis zur Umsetzung von §2.4 noch `sunset_2` als Matrix-Ende.

**Abweichung zu Live:** Re-Optimierung nur einmal pro Schritt (nicht alle 15 min).
**Bewusst kein Ziel:** rollierende oder viertelstündliche Re-Optimierung im Backtesting —
ein Schritt pro E-Auto-Anker reicht für den Horizont-Vergleich; Live-Prod bleibt 15-min-Roll.
**Bewusst kein Ziel:** stündliches Durchrollen der vollen SA₂-Matrix in `simulate_horizon`.

### 4.3 Vergleichslauf

```bash
python run_backtesting.py --start-month 1 --end-month 12 --horizon-mode fixed_24h
python run_backtesting.py --start-month 1 --end-month 12 --horizon-mode sunrise_window
```

`horizon_mode` wird in `backtesting_log.json` unter `period.horizon_mode` persistiert.
Referenz „Historisch (ohne Optimierung)“ ist für beide Modi identisch.

## 5. Config (Live)

```json
"live_scenario_id": "live",
"planning_horizon": {
  "mode": "sunrise_window"
}
```

Live-Szenario `live` in `backtesting_scenarios.json` referenziert `house_profile_id` (Geo/Zeitzone aus `house_profiles.json`). Live akzeptiert derzeit nur `planning_horizon.mode: "sunrise_window"`.

## 6. Implementierungsphasen

| Phase | Inhalt | Status |
|-------|--------|--------|
| **1** | `planning_window.py`, Tests, Spec, Backlog | erledigt |
| **2** | Matrix/Preise/PV generalisieren, MILP SOC-Anker | erledigt |
| **3** | `main.py`, Simulation Live | erledigt |
| **4** | UI sunrise→sunrise mit Zonenfarben | erledigt |
| **5** | Backtesting `--horizon-mode` (fixed_24h / sunrise_window), Vergleichsdoku | erledigt |

Offen (Backlog): [UI Sunset-2-Sunset](ui-sunset2sunset.md) (SA₁→SA₂-Segment, fließende Historie), optional Live-Umschaltung `fixed_24h` \| `sunrise_window`.

## 7. Akzeptanzkriterien

1. Fensterberechnung korrekt für 10:00 / 17:00 / 22:00 (SA₁, SA₂, `t_sunrise`).
2. MILP: `e_batt[t_sunrise] ≈ SOC_min`.
3. Zweiter Zyklus nach Sonnenaufgang ohne End-SOC-Constraint.
4. UI-Zonen: grau / neutral / grün gemäß Abschnitt 3.
5. Backtesting `fixed_24h`: SOC-Kette über Fenstergrenzen unverändert.
6. Backtesting `sunrise_window`: Lauf ohne Fehler; `horizon_mode` im Log; Jahresvergleich manuell.

## 8. Entscheidungsprotokoll

| Datum | Entscheidung |
|-------|--------------|
| 2026-07-04 | Sonnen-Definition: official |
| 2026-07-04 | Kosten-Summe: sunrise→sunrise |
| 2026-07-04 | UI-Zonen: grau / keine / grün |
| 2026-07-04 | SA₂-Ausblick in UI: Phase 2 |
| 2026-07-04 | Backtesting fixed_24h: E-Auto-Anker; End-SOC = Anker-SOC (terminal_soc_percent) |
| 2026-07-04 | `battery_end_soc_equals_start` entfernt; Terminal-SOC nur noch modus-/aufrufgesteuert |
| 2026-07-04 | Backtesting-Vergleich: eine Version, CLI `--horizon-mode`, kein `.env` |
| 2026-07-04 | Backtesting sunset: Grundlast-Overlay für 24h-Output; Jahresvergleich 2025; Live sunset, Referenz fixed_24h |
| 2026-07-04 | **Korrektur:** MILP-Horizontende = SA₂ (**Sonnenaufgang**), nicht SU₂; v0.4 sunset_2 im Code = Rückstand (§2.4) |
