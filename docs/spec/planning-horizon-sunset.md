# Spezifikation: Sunset-Planungshorizont & SOC-Anker am Sonnenaufgang

**Version:** 0.3  
**Branch:** `feature/sunset-planning-horizon`  
**Status:** Phase 1–4 implementiert; Phase 5 abgeschlossen (2026-07-04, Jahresvergleich 2025)

## 1. Ziel

Ersetzt den fixen 24-h-Rollhorizont und `battery_end_soc_equals_start` im Live-Betrieb durch einen
PV-/Tagesrhythmus-orientierten Planungshorizont mit sinnvoller End-SOC-Randbedingung.

### Annahmen (gesichert)

- Batterie ist zum **Sonnenaufgang** praktisch leer (`SOC ≈ SOC_min`).
- Nachtladung aus dem Netz ist wirtschaftlich irrelevant (5 kWh, 6 kWp PV).
- Nach dem SOC-Anker-Sonnenaufgang ist der zweite „Sonnenumlauf“ bis Horizontende **frei** (Entscheidung A).

## 2. Planungsfenster (MILP)

### 2.1 Definition

```
Segment A:  t_now  →  SA₁   (erster kommender Sonnenuntergang)
Segment B:  SA₁    →  SA₂   (vollständiger sunset→sunset-Tag)
Horizont:   t_now  →  SA₂
```

- **SA₁:** Sonnenuntergang heute, falls `t_now < SA_heute`; sonst morgen.
- **Sonnenzeiten:** astronomisch **official** aus `latitude` / `longitude` (Modul `astral`).
- **Zeitzone:** explizit als Parameter (`timezone_name`, z. B. `Europe/Vienna`).

### 2.2 SOC-Randbedingung (MILP)

| Slot | Regel |
|------|--------|
| `t_sunrise` = erster Sonnenaufgang mit `t_sunrise > t_now` | `e_batt[t] == SOC_min` (hart) |
| Übrige Slots inkl. Horizontende SA₂ | nur min/max-SOC |

### 2.3 Slot-Granularität

Stündlich (wie bisher). Implementierung: `data/planning_window.py`.

## 3. UI (Live-Chart sunrise→sunrise)

Anzeigefenster: **letzter Sonnenaufgang → nächster Sonnenaufgang** (nicht voller MILP-Horizont bis SA₂).

Einsparungs-/Kosten-Summe: über dieses sunrise→sunrise-Fenster.

### Hintergrundzonen

| Zone | Zeitraum | Hintergrund |
|------|----------|-------------|
| Vergangenheit | letzter SA → jetzt | **Grau** |
| Live/Plan | jetzt → nächster SA (SOC-Anker) | **Keine** |
| Vorausschau | nächster SA → Ende Chart (nächster SA) | **Grün** |

Navigation ←/→: verschiebt das sunrise→sunrise-Fenster; fließender Übergang Ist/Vorausschau/Historie.

**Phase 2:** Erweiterter MILP-Ausblick bis SA₂ (eigene Darstellung).

Marker: Jetzt-Linie, Sonnenaufgang (SOC-Anker), Sonnenuntergänge.

## 4. Backtesting

Backtesting unterstützt zwei **explizit wählbare** Horizont-Modi (CLI `--horizon-mode`, kein `.env`-Schalter).
Standard bleibt `fixed_24h` (Abwärtskompatibilität).

### 4.1 Modus `fixed_24h` (Standard, bisheriges Verhalten)

```
Fenster:  [Anker − 24h, Anker)   mit Anker = E-Auto ready_by_hour
SOC @ Anker: frei
SOC-Kette: End-SOC Fenster N → Start-SOC Fenster N+1
MILP-Horizont: 24 h (identisch zum Output-Fenster)
```

`battery_end_soc_equals_start` darf in Szenarien **nicht** reaktiviert werden.

### 4.2 Modus `sunset_window` (Vergleich zu Live-Prod)

Pro Backtesting-Schritt (weiterhin **24 h Output** pro E-Auto-Anker, fairer Vergleich):

```
t_now     = Anker − 24h          (Fensterstart wie fixed_24h)
MILP      = Jetzt → SA₂          (Planungsdaten bis SA₂)
SOC       = hart SOC_min am Sonnenaufgang innerhalb des MILP
Simulation= rollierend max. 24 h pro Schritt (wie fixed_24h; kein Durchsimulieren bis SA₂)
Output    = erste 24 h ab t_now   (Kosten/SoC-Kette wie bisher)
Daten     = historische Ist-Verbräuche/PV aus cons_data_hourly.csv
Geo/Zeit  = latitude/longitude aus Szenario + runtime_settings.timezone_name
```

**Performance:** Volle SA₂-Matrix (typ. 36–39 h) würde pro Schritt ~58 % mehr MILP-Läufe
in `simulate_horizon` erzeugen als nötig; Backtesting kürzt daher auf 24 h Simulations-Tiefe.
Der Sonnenaufgang-Index liegt im Sommer-Halbjahr stets innerhalb dieser 24 h.

**Abweichung zu Live:** Re-Optimierung nur einmal pro Schritt (nicht alle 15 min).
**Bewusst kein Ziel:** rollierende oder viertelstündliche Re-Optimierung im Backtesting —
ein Schritt pro E-Auto-Anker reicht für den Horizont-Vergleich; Live-Prod bleibt 15-min-Roll.
**Bewusst kein Ziel:** stündliches Durchrollen der vollen SA₂-Matrix in `simulate_horizon`.

### 4.3 Vergleichslauf

```bash
python run_backtesting.py --start-month 1 --end-month 12 --horizon-mode fixed_24h
python run_backtesting.py --start-month 1 --end-month 12 --horizon-mode sunset_window
```

`horizon_mode` wird in `backtesting_log.json` unter `period.horizon_mode` persistiert.
Referenz „Historisch (ohne Optimierung)“ ist für beide Modi identisch.

## 5. Config (Live)

```json
"planning_horizon": {
  "mode": "sunset_window",
  "timezone_name": "Europe/Vienna",
  "terminal_soc_at_sunrise": true
}
```

`battery_end_soc_equals_start` → deprecated (Live: `false`).

## 6. Implementierungsphasen

| Phase | Inhalt |
|-------|--------|
| **1** | `planning_window.py`, Tests, Spec, Backlog |
| **2** | Matrix/Preise/PV generalisieren, MILP SOC-Anker |
| **3** | `main.py`, Simulation Live |
| **4** | UI sunrise→sunrise mit Zonenfarben |
| **5** | Backtesting `--horizon-mode` (fixed_24h / sunset_window), Vergleichsdoku |

## 7. Akzeptanzkriterien

1. Fensterberechnung korrekt für 10:00 / 17:00 / 22:00 (SA₁, SA₂, `t_sunrise`).
2. MILP: `e_batt[t_sunrise] ≈ SOC_min`.
3. Zweiter Zyklus nach Sonnenaufgang ohne End-SOC-Constraint.
4. UI-Zonen: grau / neutral / grün gemäß Abschnitt 3.
5. Backtesting `fixed_24h`: SOC-Kette über Fenstergrenzen unverändert.
6. Backtesting `sunset_window`: Lauf ohne Fehler; `horizon_mode` im Log; Jahresvergleich manuell.

## 8. Entscheidungsprotokoll

| Datum | Entscheidung |
|-------|--------------|
| 2026-07-04 | Sonnen-Definition: official |
| 2026-07-04 | Kosten-Summe: sunrise→sunrise |
| 2026-07-04 | UI-Zonen: grau / keine / grün |
| 2026-07-04 | SA₂-Ausblick in UI: Phase 2 |
| 2026-07-04 | Backtesting fixed_24h: E-Auto-Anker, SOC frei am Ende |
| 2026-07-04 | Backtesting-Vergleich: eine Version, CLI `--horizon-mode`, kein `.env` |
| 2026-07-04 | Backtesting sunset: Grundlast-Overlay für 24h-Output; Jahresvergleich 2025; Live sunset, Referenz fixed_24h |
