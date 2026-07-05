🗺️ Projekt-Roadmap & Backlog

Erledigte Punkte → [Backlog-Erledigt.md](Backlog-Erledigt.md)

## Offene Bugfixes

- [ ] **Bugfix Chart 2: Ist-Kosten im grauen Log-Bereich konstant 0 €** — Kurve „Kosten (Ist bisher)“ bleibt in Prod flach, obwohl Verbrauch/Log-Slots befüllt sind; vermutlich `_slot_cost_euro` / `entry_to_chart_row` (`runtime_store/history_timeline.py`): Netzbezug aus Soll (PV + `battery_plan_kw`) statt **`consumption_snapshot.grid_kw`** bzw. fehlendes `market_price_cent` im Log; Pipeline `build_chart_history` → `_actual_slot_increments` → `add_cumulative_s2_split_traces` (`ui/charts.py`); Akzeptanz: kumulierte Ist-Kosten > 0 bei realem Netzbezug im `optimization_history.jsonl`; Regressionstest mit Log-Eintrag inkl. Snapshot
- [ ] **UI S-2 Chart 2: Einsparungs-Texteinblendungen in beiden Segmenten** — Plotly-Annotationen (`BL Ziel`, `Optimiert`, `Ersparnis`) via `_cost_summary_annotations` in `ui/charts.py` fehlen im S-2-Split-Modus (`show_cost_summary` nur bei `not split_mode`); in **SA₀→SA₁** und **SA₁→SA₂** anzeigen, Werte **immer Gesamt-Horizont Jetzt→SA₂** (wie Kennzahlen/Energievergleich, unabhängig vom sichtbaren Chart-Segment); Kontext `ui/simulation_results.py` (`_cost_totals_from_savings`)
- [ ] **Bugfix Chart 1: SoC-Lücke grau → neutral (Log/MILP-Grenze)** — SoC-Linie bricht am Übergang grauer Log-Zone in neutralen MILP-Bereich ab; analog zur behobenen Lücke neutral→grün (`test_soc_trace_bridges_extrapolation_start`): `add_optimized_soc_trace` setzt `bridge_left=False` an `history_slot_count` (`ui/charts.py`); vermutlich fehlender Brückenpunkt wie bei Extrap-Start oder fehlendes SoC im ersten MILP-Slot nach Merge (`ui/chart_context.py` `_milp_tail_rows`); Akzeptanz: durchgehende SoC-Linie an Log/MILP-Grenze ohne sichtbare Lücke; Test anpassen/ergänzen (`test_soc_trace_splits_at_history_boundary`)
- [ ] Warum zeigt streamlit auf PC Warnungen und Fehler an, Produktivsystem aber nicht?
- [ ] **Verknüpfung:** urgent-Regel-Review (bis ca. 2026-07-12) ↔ Prod-Dump-`xfail` (Live, Modus A) ↔ PWM/Mindestlademenge E-Auto.


## Feature-Backlog

### Version 0.+1
- [ ] Vor / Zurück Button kleiner machen und neuen Knopf Heute einfügen, sowie Datumsauswahl ermöglichen (nur für vorhandene Daten)
- [ ] Chart 1 für variable Anzahl von Verbrauchern fit machen (max 4 anzeigen, nach Leistung priorisieren, Zoom einführen) — alternativ ein negativer Balken mit allen aufsummierten Verbrauchern
- [ ] `scripts.migrate_persist_layout` löschen
- [ ] **Preis-Spiegelung (Markt):** statt einzelner Spiegelquelle (gleiche Uhrzeit, bis 7 Tage zurück) ggf. **Mittelung über mehrere vergangene Tage** prüfen — Genauigkeit/Robustheit vs. Einfachheit; Kontext `data/market_prices.py` (`resolve_market_slots`)
- [ ] Erweitertes Temperaturmodell für Swim-Spa mit zweitem Wärmepfad in die Erde. Hier ist eine Lookup-Table für die Erdtemperatur:
bodentemperaturen_nach_monat = {
    1:  6.5,   # Januar
    2:  5.0,   # Februar
    3:  4.0,   # März (Minimum)
    4:  5.5,   # April
    5:  8.5,   # Mai
    6:  11.5,  # Juni
    7:  14.0,  # Juli
    8:  16.0,  # August
    9:  17.5,  # September (Maximum)
    10: 15.5,  # Oktober
    11: 12.5,  # November
    12: 9.5    # Dezember
}

### Version 0.+1
- [ ] PWM für E-Auto-Laden nur noch benutzen für Ströme < A_min, ansonsten ersetzen durch Mindestlademenge pro h (Zähler, der runterzählt und bei jedem Ladevorgang wieder geresettet wird → wenn Null, fünf Minuten laden mit Mindest-Strom)
- [ ] **E-Auto-MILP: optionale Nacharbeiten**
- [ ] **urgent-Regel auf Notwendigkeit prüfen** (Review bis ca. **2026-07-12**)
  - Auswertung: `urgent_rule_observability` in Log + `optimization_history.jsonl` (`role`: `redundant` / `nachholen` / `nur_urgent_fenster`)
  - Akzeptanz: durchgehend nur `redundant` → Nebenbedingung entfernen; sonst behalten und begründen
- [ ] **Prod-Dump-Regression: urgent-Nebenbedingung infeasible** (Stand 2026-07-03, Commit `a743318`)
  - Fixture: `eauto_urgent_deferred_cheap_hours_2026-06-28` (~7,99 kWh Rest)
  - Live Modus A: MILP mit urgent → **Infeasible**; ohne urgent → **Optimal**
  - `@pytest.mark.xfail` in `tests/test_prod_dump_regression.py` (2 Tests)
  - Nächster Schritt: Live urgent + Modus A prüfen; `xfail` entfernen wenn feasible

### Version 0.+1
- [ ] Nutzung des Swim-Spa Filters reviewen (läuft derzeit ständig?)
  - Signal `Ernie_Swimspa_Filter_Sollstunden` (Sollstunden in 24 h), Steuerung `Ernie_Filter_Freigabe`
  - Ernie: Sollstunden in 24 h auf Null; Filterleistung; Laufzeiten in Loxone integriert
- [ ] **Nachrechnung „Historischer Tag“ ins Backtesting** (Dev-only)
  - Beliebiger Kalendertag aus `cons_data_hourly.csv` + historische Preise; Umsetzung später klären (ersetzt Sidebar-Modus „Historischer Tag“)
- [ ] **Soll-Ist Hinweis-Regeln** — Kategorie „Hinweis“ sobald konkrete unkritische Fälle identifiziert (Follow-up Epic Soll-Ist)
- [ ] **Soll-Ist Nachrechnung (Backtesting)** — Regelwerk batchweise über historische JSONL / Prod-Dumps; Statistik je Kategorie (Follow-up Epic Soll-Ist)

### Verstion 0.+1
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Gefrierschrank (Prio2)

### Version 0.+1
- [ ] **Optional: Live-Planungshorizont per `config.json` umschaltbar** (`planning_horizon.mode`: `fixed_24h` | `sunset_window`)
  - Aktuell Live nur `sunset_window` (Schema/Code); Backtesting kennt beide Modi bereits — Live-Verzweigung noch implementieren (`main.py`, `profile_manager`, UI-Chart, aWATTar-Fenster)
  - Modus **`fixed_24h`:** End-SOC-Verhalten **fest im Modus** verankern — wirtschaftlich äquivalent zu bisher `battery_end_soc_equals_start: true` (Start-SOC am Horizontende), **oder** harte Gleichheits-Nebenbedingung durch die bestehende **`battery_wear`-Strafe** einführen, die niedrigere End-SOCs angemessen „bestraft“ (eine Variante wählen, nicht beides parallel)
  - Modus **`sunset_window`:** unverändert **SOC_min am Sonnenaufgang** (hart)
  - Spec ergänzen, Live-Tests für beide Modi

### Version 0.+1
- [ ] Empfehlungsmodus Waschmaschine / Geschirrspüler / Trockner (Laufzeit, Leistung → Startgüte in 6 h)
  - Loxone-Merker für Waschmaschinen-Leistung: "Leistung Waschmaschine"
  - Loxone-Merker für Trockner-Leistung: "Leistung Trockner"
  - Für Geschirrspüler ist keine Leistung bekannt (vielleicht später über Hue?)
  - [ ] Könnte auch adaptiv sein bzgl. Laufzeit und Energieverbrauch pro Lauf
- [ ] Readme ausführlicher machen mit Motivation / Nutzen

### Version 2.0
- [ ] Ausführlicher Code-Review und Refactoring
### Version 2.+1
- [ ] Generische Wärme-Modelle für Verbraucher/Erzeuger anhand der konkreten Beispiele entwickeln
  - Wärme-Modelle
    - Isolierte Ein-Knoten-Modelle (Gefrierschrank, Swimspa), aber mit variablen Wärmepfaden (gegen Unendlich)
    - Gekoppelte Ein-Knoten-Modelle (Haus <-> Wärmespeicher <-> Solaranlage)
    - Parameter für Haus aus Energieausweis extrahieren ("C:\Users\joche\Documents\Hausbau\Hausbau_Köhler_Schreyögg\Energieausweis_komplett_EFH-Köhler_Dornbirn-2014.pdf")
- [ ] **PV-Adaption (neuer Ansatz)** — ersetzt Sidebar-PV-Tuning (wird mit UI Sunset-2-Sunset entfernt); siehe auch `runtime/pv_accuracy_log.csv`

### Version 2.+1
- [ ] Einen Adaptionsalgo einbauen, der definierte Parameter selbständig ändert, um Vorhersage zu verbessern. Die Wärmemodelle bleiben weiterhin linear  
- [ ] Generisches Adaptionsmodell entwickeln, das zur Parameter-Adaption verschiedener Modelle benutzt werden kann
  - PV-Ertrag
  - Wärmemodelle
  - Solar-Kollektor
  - Ein generisches Vorhersagemodell muss hinterlegt werden mit:
    - Referenzwert (auf den adaptiert werden soll)
    - Veränderliche Parameter
    - Zeithorizont (z.B. 24h für Gefrierschrank oder PV-Ertrag, 1 Jahr für Swimspa und Haus)
    - Der Adapationsalgo entnimmt Start-Parameter (live-Parameter) aus config.json und hinterlegt Adaptionshistorie getrennt und korrigiert Live-Parameter bei Bedarf (festgelegter Rhythmus - am Zeithorizont orientiert)

### Version 2.+1
- [ ] Generisches E-Auto-Modell - für bessere Wiederverwendbarkeit

### Version 2.+1
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Wärmepumpe (Prio3) — nur indirekte Steuerung über Anpassung der Solltemperaturen

### Version 2.+1
- [ ] Eigene UI-Seite zur Visualisierung der Adaptionsalgos
- [ ] Visualisierung des tatsächlichen Verbraucher-Verhaltens evtl. mit Empfehlungen

### Version 2.+1
- [ ] Konfigurationsseite einfügen zum einfachen Editieren der `config.json` und Szenarien

### Version 2.+1
- [ ] Was-wäre-wenn-Assistenten für Backtesting designen:
  - würde sich Ernie lohnen (mit aWATTar)?
  - würde sich (mehr) Batterie lohnen?
  - Verbraucher abfragen und daraus Verbraucherprofile generieren
- [ ] Erinnerung am Monatsanfang für Einspeisepreis (E-Mail von Loxone!)


## Packaging & Deployment

Empfohlene Reihenfolge offen: **7e → 7f**

- [x] **7a–7d** — pyproject, Bootstrap, Build-Pipeline, Streamlit extern ([container.md](docs/einrichtung/container.md))
- [ ] **7e — Prod/Dev-Datensync** — Skript runtime/ + CSVs; dokumentierter Ablauf Dev ↔ Prod
- [ ] **7f — Loxberry-Container** — erst nach Loxberry 4; Go/No-Go im README

## Referenz

### Log-Dateien (Review 2026-06)

| Datei | Status | Aktion |
|-------|--------|--------|
| `runtime/optimization_history.jsonl` | **kanonisch** | Produktiv-Historie |
| `runtime/energy_optimizer.log` | **aktiv** | Rotierend 5×5 MB |
| `runtime/optimizer_run_state.json` | **aktiv** | Letzter main-Durchlauf |
| `runtime/live_optimization_debug.json` | **aktiv** | App-24h-Debug |
| `runtime/system_history_log.csv` | **Legacy, nur Lesen** | Archivieren wenn JSONL reicht |
| `runtime/pv_accuracy_log.csv` | **Lesen aktiv, Schreiben aus** | siehe Backlog **PV-Adaption (neuer Ansatz)** |
| `backtesting_log.json` | **nur Dev** | nicht für Prod-NAS |
