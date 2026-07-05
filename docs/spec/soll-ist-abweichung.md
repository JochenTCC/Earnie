# Spezifikation: Soll/Ist-Abweichung (Chart 1)

**Version:** 0.1  
**Status:** Epic geplant (2026-07-05); Phasen 1–4 offen  
**Epic-Kurzname:** **Soll-Ist**  
**Voraussetzung:** Epic **UI Sunset-2-Sunset** abgeschlossen ([ui-sunset2sunset.md](ui-sunset2sunset.md) v0.7.0)

## 1. Ziel

Im **grauen Bereich** von Chart 1 (Produktiv-Log, 15-Min-Slots) sollen Abweichungen zwischen **Soll** (Ernie/MILP zum Laufzeitpunkt) und **Ist** (Loxone/Messung) sichtbar werden — als **Icons** mit drei Kategorien:

| Kategorie | Bedeutung | Beispiel (vorläufig) |
|-----------|-----------|----------------------|
| **Hinweis** | Unkritische Abweichung | *(noch ohne festes Beispiel — Kategorie reserviert)* |
| **Warnung** | Erwartete Abweichung — Loxone kennt die Anforderung, entscheidet bewusst anders | SwimSpa nicht geheizt, obwohl Soll > 0, weil Ist-Temperatur noch im Band |
| **Fehler** | Fehlerhafte Abweichung — Anweisung von Ernie nicht befolgt | E-Auto lädt nicht trotz Soll und Restladung; Zwangs-Laden der Batterie fehlt |

Kategorien und Zuordnung werden **gemeinsam nach und nach** verfeinert. Technisch sind sie in einer **JSON-Regeldatei** pflegbar (nicht hart codiert).

**Stufe 1 (dieses Epic):** Log-Soll vs. gespeichertes Ist pro Viertelstunden-Slot (`optimization_history.jsonl`).  
**Stufe 2 (Follow-up, nicht Epic):** Kontinuierliches Haus-Ist (feinere Auflösung als 15-min-Log).

## 2. Abgrenzung

| Im Epic | Nicht im Epic |
|---------|----------------|
| Regelwerk + Auswertung pro Log-Slot | Nachrechnung über beliebige historische Tage (→ Backtesting-Follow-up) |
| Icons/Marker in Chart 1 | Chart 2, Sankey (hat bereits einfaches Soll/Ist-Farb-Overlay) |
| Tooltip + ?-Hilfe | Automatische Loxone-Korrektur (bleibt `loxone_watchdog`) |
| Unit-Tests mit JSONL-Fixtures | Vollständige Regelabdeckung aller Verbraucher am ersten Tag |

## 3. Datenquellen pro Slot

Aus einem Eintrag in `optimization_history.jsonl` (siehe `main.py` → `append_production_run`):

| Signal | Soll-Feld | Ist-Feld | Anmerkung |
|--------|-----------|----------|-----------|
| Flex-Leistung je Verbraucher | `consumer_powers_kw.{id}` | `consumption_snapshot.flex_kw.{id}` | Fallback Ist: `flex_live_kw.{id}` |
| Batterie-Modus | `mode`, `target_power_kw`, `battery_plan_kw` | `consumption_snapshot.battery_kw` | Modus 1/3 = Zwangs-Laden/-Entladen |
| PV / Grundlast | `forecast_*` | `consumption_snapshot.pv_kw`, `baseload_kw` | Stufe 1: nur wo für Regeln nötig |
| Thermik (SwimSpa) | `thermal_observability` | `readings_c.actual`, Band | Kontext für Warnungs-Regeln |
| E-Auto-Kontext | `charging_contexts.eauto` | — | `plugged_in`, `remaining_kwh`, `immediate_charge` |
| Loxone-Soll gesendet | `loxone_sent` | — | optional für erweiterte Regeln |

**Auswertungsgrenze:** nur Slots mit `slot_quality == present` im grauen Bereich (Spec UI S-2 §6). Keine Icons bei `missing` oder `held`.

## 4. Architektur

Drei Schichten — Trennung von Fakten, Regeln und Darstellung:

```
optimization_history.jsonl
        │
        ▼
  deviation_facts     ← Python: normalisierte Slot-Fakten
        │
        ▼
  deviation_rules.json  ← JSON: Kategorien + Regeln (Hybrid-Prädikate)
        │
        ▼
  DeviationEvent[]    ← pro Slot, scope, category, message
        │
        ▼
  Chart 1 (Plotly)    ← Marker/Icons + Tooltip
```

### 4.1 Facts-Schicht (`optimizer/deviation_facts.py`)

Extrahiert aus einem Log-Eintrag ein stabiles Dict/Dataclass:

- `slot`, `consumer_id` → `{soll_kw, ist_kw, mismatch_kw}`
- Batterie: `{soll_mode, soll_power_kw, ist_power_kw}`
- Thermik: `{actual_c, band_min, band_max, heating_scheduled}`
- Kontext: `charging_contexts`, `delivery_plausibility`, `slot_quality`

Toleranzen werden aus der Regeldatei gelesen (keine stillen Default-Änderungen an Berechnungsergebnissen).

### 4.2 Regelwerk (Hybrid)

**JSON** definiert Kategorien, Prioritäten, Regelketten und Meldungstexte.  
**Python** implementiert **benannte Prädikate** (unit-getestet) — keine eigene Ausdruckssprache in JSON.

Dateien:

| Datei | Zweck |
|-------|--------|
| `config/deviation_rules.json` | Produktiv-Regeln (lokal pflegbar, committbar) |
| `config/deviation_rules.schema.json` | Schema für Editor-Validierung |
| `config/deviation_rules.example.json` | Vorlage / Dokumentation |

Laden beim App-Start bzw. erstem Chart-Aufbau; bei unbekanntem Prädikat oder Schema-Fehler: **klare Fehlermeldung** (kein stilles Ignorieren).

### 4.3 Auswertung (`optimizer/deviation_eval.py`)

- Regeln nach `priority` **absteigend** prüfen.
- Pro `scope` (z. B. `eauto`, `swimspa`, `battery`) gewinnt die **erste** passende Regel.
- Mehrere Scopes pro Slot → mehrere Icons möglich.
- `fallback.on_unclassified_mismatch`: explizit `none` | `warning` | `error` (Standard MVP: `none`).

### 4.4 UI (`ui/charts.py`, `ui/chart_context.py`)

- Plotly-Scatter `mode="markers"` oberhalb der Chart-Fläche (y-Referenz: oberer Rand oder dedizierte Icon-Zeile).
- Symbol/Farbe aus `categories` in JSON.
- Hover: Kategorie-Label + `message` (mit Platzhaltern `{soll_kw}`, `{ist_kw}`, `{consumer_name}`).
- **?**-Hilfe Chart 1 um Abschnitt „Soll/Ist-Icons“ ergänzen.

## 5. Regeldatei (Struktur)

Siehe `config/deviation_rules.schema.json` und `config/deviation_rules.example.json`.

```json
{
  "$schema": "./deviation_rules.schema.json",
  "version": 1,
  "tolerances": {
    "power_kw": 0.05,
    "soc_percent": 0.1
  },
  "categories": {
    "hint":    { "label": "Hinweis",  "symbol": "triangle-up", "color": "#f1c40f" },
    "warning": { "label": "Warnung",  "symbol": "diamond",     "color": "#e67e22" },
    "error":   { "label": "Fehler",   "symbol": "octagon",     "color": "#c0392b" }
  },
  "rules": [
    {
      "id": "swimspa_thermal_band_ok",
      "enabled": true,
      "category": "warning",
      "priority": 100,
      "scope": "swimspa",
      "when": ["power_mismatch_positive", "thermal_actual_in_band", "heating_was_scheduled"],
      "message": "SwimSpa nicht geheizt — Ist-Temperatur im Sollband"
    }
  ],
  "fallback": {
    "on_unclassified_mismatch": "none"
  }
}
```

### 5.1 Prädikat-Bibliothek (MVP)

| Prädikat | Bedeutung |
|----------|-----------|
| `power_mismatch_positive` | `soll_kw - ist_kw > tolerance` und `soll_kw > tolerance` |
| `power_mismatch_any` | `|soll - ist| > tolerance` |
| `plugged_in` | `charging_contexts.{scope}.plugged_in == true` |
| `remaining_kwh_above_threshold` | Restladung > Schwelle (Schwelle in Regel-`params` oder global) |
| `thermal_actual_in_band` | Ist-Temp zwischen `band_min` und `band_max` |
| `heating_was_scheduled` | Thermik-Schedule sieht Heizen für Slot vor |
| `mode_is_forced_charge` | `mode == 1` (Zwangs-Laden) |
| `mode_is_forced_discharge` | `mode == 3` |
| `battery_power_below_tolerance` | Ist-Lade-/Entladeleistung weicht von Soll ab |
| `slot_quality_present` | Slot hat echten Log-Eintrag |

Neue Domänenkenntnis = neues Prädikat (Python + Test) + JSON-Regelzeile.

### 5.2 Szenario-Katalog (Acceptance)

Vor Implementierung der Chart-Icons als Tests fixieren (JSONL-Fixtures unter `tests/fixtures/deviation/`):

| ID | Situation | Erwartete Kategorie |
|----|-----------|---------------------|
| S1 | SwimSpa Soll > 0, Ist ≈ 0, Temp im Band | Warnung |
| S2 | E-Auto Soll > 0, angesteckt, Rest > Schwelle, Ist ≈ 0 | Fehler |
| S3 | Modus Zwangs-Laden, Batterie lädt nicht | Fehler |
| S4 | Soll ≈ Ist (innerhalb Toleranz) | kein Icon |
| S5 | Soll > 0, Ist ≈ 0, ohne passende Regel | `fallback` (MVP: kein Icon) |

Weitere Szenarien werden im Betrieb ergänzt; Kategorie **Hinweis** erst bei konkretem Fall.

## 6. Epic-Phasen

| Phase | Inhalt | Akzeptanz |
|-------|--------|-----------|
| **P1** | Facts, Schema, Beispiel-JSON, Prädikat-MVP, Evaluator, Tests S1–S5 | `pytest tests/test_deviation_*.py` grün |
| **P2** | Anbindung `build_chart_history` / `ChartDisplayContext`; Events pro Slot | Events nur bei `present`; keine Events in neutral/grün |
| **P3** | Chart-1-Marker, Tooltip, ?-Hilfe | Icons sichtbar in Streamlit; Hover zeigt Kategorie + Text |
| **P4** | `docs/ui/charts.md`, Szenario-Doku, Regel-Pflegehinweis | Spec v0.2; Backlog Epic-Abschluss |

Commit-Präfix: `deviation(soll-ist): P1a …` bzw. kurz `soll-ist: P1 …`.

## 7. Follow-ups (nach Epic)

| Thema | Beschreibung |
|-------|--------------|
| **Nachrechnung Backtesting** | Regelwerk batchweise über historische JSONL / Prod-Dumps; Statistik je Kategorie |
| **Stufe 2 Haus-Ist** | Kontinuierlicher Abgleich (feinere Auflösung als 15-min-Log) |
| **Hinweis-Kategorie** | Regeln sobald konkrete unkritische Fälle identifiziert |
| **Weitere Prädikate** | `urgent_window_active`, `pv_follow_enabled`, `loxone_sent_mismatch` |

## 8. Bezug

- UI-Rahmen: [ui-sunset2sunset.md](ui-sunset2sunset.md) §6 (grauer Bereich), §8 (ursprüngliches Follow-up Soll/Ist)
- Produktiv-Log: `runtime_store/history_timeline.py`, `runtime/optimization_history.jsonl`
- Bestehende Abgleich-Logik: `integrations/loxone_watchdog.py`, `ui/sankey_produktiv.py` (`KW_TOLERANCE`)
- Thermik: `optimizer/thermal_targets.py` (`thermal_observability`)
- Lieferung: `optimizer/delivery_tracking.py` (`delivery_plausibility`)

## Änderungshistorie

| Datum | Version | Inhalt |
|-------|---------|--------|
| 2026-07-05 | 0.1 | Erstfassung Epic-Plan, Architektur, Regelwerk, Phasen P1–P4 |
