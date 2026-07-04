# Spezifikation: Sunset-Planungshorizont & SOC-Anker am Sonnenaufgang

**Version:** 0.2  
**Branch:** `feature/sunset-planning-horizon`  
**Status:** Phase 1–4 implementiert

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

## 4. Backtesting (unverändert)

```
Fenster:  [Anker − 24h, Anker)   mit Anker = E-Auto ready_by_hour
SOC @ Anker: frei
SOC-Kette: End-SOC Fenster N → Start-SOC Fenster N+1
```

Kein Sunset-Horizont, kein SOC_min-am-Sonnenaufgang im Backtesting.  
`end_soc_equals_start` darf in Szenarien **nicht** reaktiviert werden.

## 5. Config (geplant)

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
| **5** | Backtesting-Abgrenzung dokumentieren, Deprecation |

## 7. Akzeptanzkriterien

1. Fensterberechnung korrekt für 10:00 / 17:00 / 22:00 (SA₁, SA₂, `t_sunrise`).
2. MILP: `e_batt[t_sunrise] ≈ SOC_min`.
3. Zweiter Zyklus nach Sonnenaufgang ohne End-SOC-Constraint.
4. UI-Zonen: grau / neutral / grün gemäß Abschnitt 3.
5. Backtesting: SOC-Kette über Fenstergrenzen unverändert.

## 8. Entscheidungsprotokoll

| Datum | Entscheidung |
|-------|--------------|
| 2026-07-04 | Sonnen-Definition: official |
| 2026-07-04 | Kosten-Summe: sunrise→sunrise |
| 2026-07-04 | UI-Zonen: grau / keine / grün |
| 2026-07-04 | SA₂-Ausblick in UI: Phase 2 |
| 2026-07-04 | Backtesting: E-Auto-Anker, SOC frei am Ende |
