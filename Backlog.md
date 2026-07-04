🗺️ Projekt-Roadmap & Backlog

## Offene Todos

**Verknüpfung:** urgent-Regel-Review (bis ca. 2026-07-12) ↔ Prod-Dump-`xfail` (Live, Modus A) ↔ PWM/Mindestlademenge E-Auto.

- [ ] **UI Sunset-2-Sunset (Spec v0.6.1)** — [docs/spec/ui-sunset2sunset.md](docs/spec/ui-sunset2sunset.md)
  - Ersetzt Modi **Echtzeit** + **Historischer Tag**, Button **Produktiv-Archiv**, Live/History-Grenze; Prod: `ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting`
  - **Phase 3 — Charts & Kennzahlen:** Chart 2 getrennt „Ist bisher“ (Log) vs. „Prognose optimiert“ (MILP); grün ab erstem `Preis extrapoliert`; Marker SA₀/SA₁/SA₂, Jetzt-Linie; alte Pfade `history_offset_days`, `render_historical_*` aus Prod-UI entfernen
  - **Phase 4 — Docs & Tests:** `docs/ui/betriebsmodi.md`, `docker-compose-synology.yml`, Tests (`test_planning_window`, Navigation, gemischte Auflösung)
  - **Follow-ups (nach v0.5):** siehe unten Soll/Ist + Nachrechnung Backtesting
- [ ] **Simulations-Tabelle — Fixierung Kopfzeile und erste Spalte** (wie Excel „Fenster fixieren“): prüfen, ob `st.dataframe`/`st.table`, CSS oder Custom Component horizontales/vertikales Scrollen mit fixer `Uhrzeit`-Spalte und Header ermöglicht
- [ ] **Preis-Spiegelung (Markt):** statt einzelner Spiegelquelle (gleiche Uhrzeit, bis 7 Tage zurück) ggf. **Mittelung über mehrere vergangene Tage** prüfen — Genauigkeit/Robustheit vs. Einfachheit; Kontext `data/market_prices.py` (`resolve_market_slots`)
- [ ] **Optional: Live-Planungshorizont per `config.json` umschaltbar** (`planning_horizon.mode`: `fixed_24h` | `sunset_window`)
  - Aktuell Live nur `sunset_window` (Schema/Code); Backtesting kennt beide Modi bereits — Live-Verzweigung noch implementieren (`main.py`, `profile_manager`, UI-Chart, aWATTar-Fenster)
  - Modus **`fixed_24h`:** End-SOC-Verhalten **fest im Modus** verankern — wirtschaftlich äquivalent zu bisher `battery_end_soc_equals_start: true` (Start-SOC am Horizontende), **oder** harte Gleichheits-Nebenbedingung durch die bestehende **`battery_wear`-Strafe** ersetzen, die niedrigere End-SOCs angemessen „bestraft“ (eine Variante wählen, nicht beides parallel)
  - Modus **`sunset_window`:** unverändert **SOC_min am Sonnenaufgang** (hart)
  - Spec ergänzen, Live-Tests für beide Modi
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
- [ ] PWM für E-Auto-Laden nur noch benutzen für Ströme < A_min, ansonsten ersetzen durch Mindestlademenge pro h (Zähler, der runterzählt und bei jedem Ladevorgang wieder geresettet wird → wenn Null, fünf Minuten laden mit Mindest-Strom)
- [ ] Nutzung des Swim-Spa Filters reviewen (läuft derzeit ständig?)
  - Signal `Ernie_Swimspa_Filter_Sollstunden` (Sollstunden in 24 h), Steuerung `Ernie_Filter_Freigabe`
  - Ernie: Sollstunden in 24 h auf Null; Filterleistung; Laufzeiten in Loxone integriert
- [ ] **urgent-Regel auf Notwendigkeit prüfen** (Review bis ca. **2026-07-12**)
  - Auswertung: `urgent_rule_observability` in Log + `optimization_history.jsonl` (`role`: `redundant` / `nachholen` / `nur_urgent_fenster`)
  - Akzeptanz: durchgehend nur `redundant` → Nebenbedingung entfernen; sonst behalten und begründen
- [ ] **Prod-Dump-Regression: urgent-Nebenbedingung infeasible** (Stand 2026-07-03, Commit `a743318`)
  - Fixture: `eauto_urgent_deferred_cheap_hours_2026-06-28` (~7,99 kWh Rest)
  - Live Modus A: MILP mit urgent → **Infeasible**; ohne urgent → **Optimal**
  - `@pytest.mark.xfail` in `tests/test_prod_dump_regression.py` (2 Tests)
  - Nächster Schritt: Live urgent + Modus A prüfen; `xfail` entfernen wenn feasible
- [ ] **Soll/Ist-Abweichung in S-2-UI** (Visualisierung; Phase 2 des UI-Epics erledigt)
  - Stufe 1: Im grauen Bereich Soll (Ernie-Log) vs. Ist (`consumption_snapshot`), wo vorhanden — Chart-Overlay + Abweichungsmarkierung (analog Sankey)
  - Stufe 2: Kontinuierliches Haus-Ist unabhängig vom 15-min-Takt (Logging erweitern oder `cons_data`) — Spezifikation offen
- [ ] **Nachrechnung „Historischer Tag“ ins Backtesting** (Dev-only)
  - Beliebiger Kalendertag aus `cons_data_hourly.csv` + historische Preise; Umsetzung später klären (ersetzt Sidebar-Modus „Historischer Tag“)
- [ ] Empfehlungsmodus Waschmaschine / Geschirrspüler / Trockner (Laufzeit, Leistung → Startgüte in 6 h)
  - Loxone-Merker für Waschmaschinen-Leistung: "Leistung Waschmaschine"
  - Loxone-Merker für Trockner-Leistung: "Leistung Trockner"
  - Für Geschirrspüler ist keine Leistung bekannt (vielleicht später über Hue?)
  - [ ] Könnte auch adaptiv sein bzgl. Laufzeit und Energieverbrauch pro Lauf
- [ ] **E-Auto-MILP: optionale Nacharbeiten**
- [ ] Generische Wärme-Modelle für Verbraucher/Erzeuger anhand der konkreten Beispiele entwickeln
  - Wärme-Modelle
    - Isolierte Ein-Knoten-Modelle (Gefrierschrank, Swimspa), aber mit variablen Wärmepfaden (gegen Unendlich)
    - Gekoppelte Ein-Knoten-Modelle (Haus <-> Wärmespeicher <-> Solaranlage)
    - Parameter für Haus aus Energieausweis extrahieren ("C:\Users\joche\Documents\Hausbau\Hausbau_Köhler_Schreyögg\Energieausweis_komplett_EFH-Köhler_Dornbirn-2014.pdf")
- [ ] **PV-Adaption (neuer Ansatz)** — ersetzt Sidebar-PV-Tuning (wird mit UI Sunset-2-Sunset entfernt); siehe auch `runtime/pv_accuracy_log.csv`
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
- [ ] Erinnerung am Monatsanfang für Einspeisepreis (E-Mail von Loxone!)
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Gefrierschrank (Prio2)
  - [ ] Wärmepumpe (Prio3) — nur indirekte Steuerung über Anpassung der Solltemperaturen
- [ ] Generisches E-Auto-Modell - für bessere Wiederverwendbarkeit

## Erledigte Punkte

### UI Sunset-2-Sunset Phase 2 — Vergangenheit füllen (2026-07-04)

- [x] **Daten-Schicht v0.6.1:** `build_chart_history`, `build_chart_display_context` — 15-min Produktiv-Log (kein Hold-Forward im Live-Chart), MILP-Tail (1 h bzw. 15-min-Soll ab x:15)
- [x] **Chart + Tabelle:** gemeinsamer Merge-Pfad (`display_ctx`), Soll aus `consumer_powers_kw`; Datenbasis-Hinweis (Runtime-Pfad, Merge-Status)
- [x] **Simulationsergebnis-Tabelle:** Log/MILP-Mix, Spalte Datenquelle, `st.table`, Flex-kW-Spalten nach vorne; orange für fehlende Log-Slots
- [x] **Chart vs. Tabelle grauer Bereich:** Abweichung war Darstellungsart (`st.dataframe`, Spaltenverwechslung); `chart_key` für Live-Chart
- [x] **Produktiv-Log:** `k_push_act`, Einspeisevergütung und `sofort_laden` in Tabellenzeilen; TZ-Fix für `completed_at`-Lookup
- [x] **Tests:** `test_chart_history`, `test_simulation_results_table`, `test_production_log_source`
- [x] **Diagnose:** `scripts/_diag_swimspa_nas.py` (NAS-`optimization_history.jsonl`)

### Dev-Umgebung NAS-Produktiv-Log (2026-07-04)

- [x] **VS Code-Launch „Streamlit app.py (NAS Produktiv-Log)“** — `ENERGY_OPTIMIZER_RUNTIME_DIR` und `ENERGY_OPTIMIZER_CONFIG_PATH` auf NAS-Pfade (`.vscode/launch.json`)
- [x] **Lokale Produktiv-Runtime bereinigt** — versehentliche Nutzung lokaler Logs ausgeschlossen; historischer E-Auto-Baseline-Test ohne lokale `cons_data` überspringen

### UI Sunset-2-Sunset Phase 1 (2026-07-04)

- [x] **Phase 1 — Modus & Fenster:** `mode_selector`, `app.py`, Sidebar ohne adaptives PV-Tuning; Sunset-2-Sunset-Modus in der UI
- [x] **Phase 1b — MILP bis SA₂ (Spec-Korrektur):** `compute_planning_window` — Horizontende Sonnenaufgang SA₂; Tests und Spec angepasst

### Live-Chart IndexError kumulierte Kosten (2026-07-04)

- [x] **IndexError in Produktiv-UI behoben** (`_segment_connected_line_xy`, kumulierte Kosten/Verbrauch)
  - Ursache: Stundenkosten-Listen kürzer als sunrise→sunrise-Chart-Fenster (Matrix vs. `display_df`)
  - `align_hourly_values_to_chart_slots` in `ui/chart_context.py`; Padding in `ui/charts.py`
  - Release **1.13.1**

### Cursor Session-Abschluss (2026-07-04)

- [x] **Zweiphasiger Session-Abschluss automatisieren**
  - Phase 1: `Backlog.md` pflegen, alle offenen Änderungen committen und pushen (bei lokalen/temporären Dateien nachfragen)
  - Phase 2: optional Docker-Image bauen und nach ghcr.io pushen (`python -m scripts.build_container --push`)
  - Skill: `.cursor/skills/session-abschluss/SKILL.md`; Rule: `.cursor/rules/session-abschluss.mdc`
  - Hook: `docker push` erfordert explizite Bestätigung (`.cursor/hooks/approve_docker_push.py`)
  - Trigger: „Session beenden“, „Backlog sync“, „Commit und Push“

### Konfiguration Dev/Prod (2026-07-04)

- [x] **Zentrale `config.json` über NAS-Pfad adressierbar**
  - Pfad per `ENERGY_OPTIMIZER_CONFIG_PATH` (in `.env`, siehe `.env.example`); Dev-Beispiel: `\\DS-KO-DO-2\docker\energy_optimizer\config\config.json`
  - Fallback unverändert: `config/config.json` → Legacy `config.json` im Projektroot
  - Docker/Synology: Volume `./config` → `config/config.json` im Container
- [x] **`loxone_silent_mode` in lokale Datei ausgelagert**
  - Maschinenspezifisch: `runtime/local_settings.json` (Vorlage `runtime/local_settings.example.json`)
  - Optional: `ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH`; Bootstrap legt fehlende Datei an
  - Aus zentraler `config.json` / Schema / Example entfernt; verbleibender Schlüssel dort → klare Fehlermeldung
  - Tests: `tests/test_local_settings.py`

### Sunset-Planungshorizont + SOC_min am Sonnenaufgang (2026-07-04)

- [x] **Hauptfeature abgeschlossen** (Branch `feature/sunset-planning-horizon`, merged)
  - Spec: [docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)
  - Fenster: Jetzt→SA₁ + SA₁→SA₂; harte SOC-Randbedingung am nächsten Sonnenaufgang; danach frei bis SA₂
  - Ersetzt `battery_end_soc_equals_start` im Live-Betrieb
  - Backtesting: E-Auto-`ready_by_hour`-Anker; `--horizon-mode fixed_24h|sunset_window`
  - Entscheidung: **Live** `sunset_window`; **Backtesting-Referenz** `fixed_24h` (10 kWh dyn. ~779 € vs. sunset ~784 €/J; früherer Sunset-Vorteil war Plausibilitäts-Artefakt)
- [x] **Phase 1:** `data/planning_window.py` + Tests
- [x] **Phase 2:** Matrix/Preise/PV generalisieren, MILP SOC-Anker
  - Day-Ahead für variable Fensterlänge (`resolve_market_slots`); aWATTar-Abruf bis SA₂
  - Preis-Spiegelung: gleiche Uhrzeit, bis 7 Tage zurück; aWATTar-Lookback für Spiegelquellen
  - Zeitzonen-Ausrichtung Planungs-Slots ↔ aWATTar (`Europe/Vienna`)
  - Loxone-Verify: fehlende E-Auto-Fertig-Uhrzeit nur **Warnung** (nicht angeschlossen)
- [x] **Phase 3:** `main.py`, Live-Simulation — **Live-Durchlauf verifiziert 2026-07-04**
- [x] **Phase 4:** UI sunrise→sunrise mit Zonenfarben — **verifiziert 2026-07-04** (wird durch Epic **UI Sunset-2-Sunset** abgelöst: SA₀→SA₁/SA₁→SA₂, neue Zonenlogik)
  - UI Live: sunrise→sunrise; Zonen grau (Vergangenheit) / neutral (jetzt→SA) / grün (Rest)
  - `ui/chart_context.py`: Chart-Fenster, Zeilen-Ausrichtung, Kosten-Summe nur über sunrise→sunrise
  - Live-Navigation ←/→; Button **Produktiv-Archiv** für 24h-Historie (Sankey/Countdown dort deaktiviert)
  - Platzhalter-Slots im Chart: NaN-sichere Hilfsfunktionen in `ui/charts.py`
  - Debug-Snapshot: `slot_datetime` (pandas Timestamp) JSON-serialisierbar; Persist nach Chart-Render
  - Sankey **Energiefluss (Live)** unverändert unterhalb der Charts in `app.py`
- [x] **Phase 5:** Backtesting-Vergleich fixed_24h vs sunset_window — **abgeschlossen 2026-07-04**
  - CLI `--horizon-mode`; Log-Feld `period.horizon_mode`; Standard Backtesting `fixed_24h`
  - Kein rollierendes Re-Optimieren im Backtesting (1× MILP pro Anker-Schritt; Spec Abschnitt 4.2)
  - Sunset-Pfad in `simulation/engine.py` (MILP Jetzt→SA₂, 24h Output/Schritt)
  - Performance: Sunset-Matrix vor `simulate_horizon` auf 24 h gekürzt (volle SA₂-Matrix wäre ~36–39 MILP/Schritt)
  - Jahres-Backtest 2025 beide Modi; Plausibilität sunset **333/333** nach Grundlast-Overlay-Fix
  - **Grundlast-Overlay** in `build_sunset_window_matrix`: 24h-`expected_p_act` aus Schritt-Matrix
  - Diagnose-Skripte: `scripts/diagnose_sunset_plausibility.py`, `scripts/debug_sunset_matrix_alignment.py`
  - Jahreslauf-Log: `backtesting_logs/horizon_compare_2025_full_sunset_window_v3.log`
  - Kostenvergleich: Referenz 1.195 €; fixed_24h 10 kWh dyn. 779 €; sunset 784 € (Einsparung vs. Historisch 416 € bzw. 411 €)

### Config-Aufräumen Planungshorizont (2026-07-04)

- [x] **`battery_end_soc_equals_start` entfernt** (NAS-Config, Schema, Example, `get_battery_params`, Test-Fixtures)
  - Terminal-SOC nur noch über `terminal_soc_percent` (Backtesting `fixed_24h`) bzw. Sonnenaufgang-Anker (Live `sunset_window`)
  - Kein separater Config-Parameter mehr

### Verbrauchshistorie Live (2026-07-04)

- [x] **Erster Schritt** der Verbrauchshistorie im Live-Modus (Produktiv-Archiv, 96×15 min) — vollständige Integration → Epic **UI Sunset-2-Sunset**

### E-Auto-MILP (2026-07-04)

- [x] **Hybrid-Lieferung / Preset-Rest:** experimentell verworfen (Jahres-Backtest 2025)

### Optimierung & Einspeise (2026-07-03)

- [x] **Batterieschädigung als Straffaktor in der MILP-Zielfunktion**
  - `optimizer/battery_wear.py`, Config-Block `battery_wear`; Durchsatz-Modell (2,5 ct/kWh bei 5 kWh: 1500 € / 6000 Zyklen / 50 % zyklenbedingt)
  - Jahres-Backtest 2025: ~33 €/J weniger Nettonutzen vs. ohne Verschleiß; Einsparung ~416 € (10 kWh dynamisch) — Parameter **plausibel**
- [x] **Monatliche Fix-Einspeisetarife im Backtesting**
  - `fixed_monthly_feed_in_rates` in `backtesting_scenarios.json`; Tarif = Kalendermonat der Stunde
  - `get_backtesting_feed_in_settings()`; Randfenster Dez 2024 ergänzt
  - Jahres-Backtest 2025: **333/333** Plausibilität (Log `backtesting_logs/backtesting_2025_wear_monthly.log`)

### Backtesting & CBC (2026-07-03)

- [x] **Grundlast-Validierung (Backtesting)**
  - `simulation/baseload_validation.py`; getrennte Plausibilität Grundlast + Flex + Gesamt
  - `scripts/analyze_plausibility_failures.py`
- [x] **E-Auto-MILP (Phase 1–4)**
  - Phase 1–4: logged_day binär, Preset, Live Modus A/B, Tie-Break; Config `eauto_milp`
  - Jahres-Backtest 2025 (Phase 3+4): 303/333 Plausibilität, 10 kWh dynamisch 774,51 € (`backtesting_logs/backtesting_2025_phase34.log`)
- [x] **UTF-8 für Backtesting-Logs**
- [x] **CBC zweistufiger Solver** (`cbc_gap_rel`, Strict-Timeout 3 s)
- [x] **CBC-Gap-Diagnose** (`scripts/bench_cbc_gaps.py`, `analyze_benchmark_window.py`)
- [x] **Backtesting urgent / Zeitfenster** (logged_day ohne urgent-Nebenbedingung)
- [x] **`run_backtesting` parallelisiert** (`--workers N`)
- [x] **Dynamische Einspeise (Awattar SUNNY Spot)** + MILP `k_push_act` aus Matrix

### Ältere Meilensteine (Kurz)

- [x] MILP-Optimierung (PV/Verbrauch), NAS-Deployment, Sankey/UI, Versionierung
- [x] Flexible Verbraucher (E-Auto, SwimSpa, WP), historische Simulation, Testsuite 24 h
- [x] E-Auto: variable Leistung, PV-Follow, Event-Trigger, SOFORT-LADEN, Loxone-Debug
- [x] Charts (Ersparnis, Einspeisung), Silent-Modus, 24h-Horizont, Refactoring
- [x] Thermische Modelle (Swim-Spa Prio1, WP indirekt), dynamische Einspeise (Vorstufe)
- [x] Packaging 7a–7d (pyproject, Bootstrap, Build, Streamlit extern)

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
