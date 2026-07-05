# Erledigte Punkte

Archiv abgeschlossener Arbeiten. Offene Todos → [Backlog.md](Backlog.md).


### Chart 1 Soll-Ist-Marker NAS (2026-07-05)

- [x] **Bugfix: Chart-1-Soll/Ist-Marker auf NAS fehlten trotz gleichem `optimization_history.jsonl`** — Ursache fehlende `config/deviation_rules.json` (und Vorlagen) auf dem NAS-Config-Volume; ohne Regeldatei unterdrückt `deviation_timeline` alle Events still. Fix: Dateien manuell auf NAS kopiert; Bootstrap legt `deviation_rules.example.json`, `deviation_rules.schema.json` und `deviation_rules.json` aus Image-Vorlage an; Dockerfile `share/config/` ergänzt (`runtime_store/bootstrap.py`)

### UI S-2 Chart 2 Einsparungs-Text (2026-07-05)

- [x] **UI S-2 Chart 2: Einsparungs-Texteinblendungen in beiden Segmenten** — `show_cost_summary` nicht mehr an `not split_mode` gekoppelt; Annotationen (`BL Ziel`, `Optimiert`, `Ersparnis`) in SA₀→SA₁ und SA₁→SA₂ mit Gesamt-Horizont-Werten aus `_cost_totals_from_savings`; Test `test_chart2_s2_split_mode_shows_cost_summary_annotations` (`ui/charts.py`)

### Chart 2 Ist-Kosten Log-Bereich (2026-07-05)

- [x] **Bugfix Chart 2: Ist-Kosten im grauen Log-Bereich konstant 0 €** — `entry_to_chart_row` nutzt bei vorhandenem Snapshot **`consumption_snapshot.grid_kw`** für Netzbezug statt Soll-Bilanz (PV + `battery_plan_kw`); `_netzbezug_kw_from_entry` in `runtime_store/history_timeline.py`; Regressionstest `test_build_chart_history_uses_snapshot_grid_kw_for_slot_cost`

### UI Chart 1 SoC-Brücke Log/MILP (2026-07-05)

- [x] **Bugfix Chart 1: SoC-Lücke grau → neutral (Log/MILP-Grenze)** — `add_optimized_soc_trace` deaktivierte `bridge_left` fälschlich an `history_slot_count`; Brückenpunkt wie bei neutral→grün wieder aktiv; Test `test_soc_trace_bridges_at_history_boundary` (`ui/charts.py`)

### UI Chart PV-Zeitbasis (2026-07-05)

- [x] **PV-Leistung auf X-Achse korrekt positioniert** — Ursache: glatte Linearinterpolation zwischen Slotbeginnen ließ PV vor Sonnenaufgang ansteigen (Rohdaten stündlich ab Slotbeginn waren plausibel); Fix: PV-Anker in **Slotmitte** (`_LINE_ANCHOR_SLOT_CENTER` in `_add_pv_trace`, `ui/charts.py`); Regressionstest `test_chart1_pv_center_anchor_avoids_early_morning_ramp`; S-2-Nav zwischen Chart 1/2 aus Fragment ausgelagert (`StreamlitFragmentWidgetsNotAllowedOutsideError`, `ui/live_mode.py`)

### UI Fragment-Refresh (2026-07-05)

- [x] **UI: Fragment-Refresh getrennt konfigurierbar** — `ui/fragment_refresh.py`; Charts 1+2 **60 s** (`ui/live_mode.py`), Sankey/Countdown **10 s** (`ui/sankey.py`, `ui/countdown.py`); optional `config.json` → `ui.fragment_refresh_charts_sec` / `ui.fragment_refresh_status_sec` oder Env `ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC` / `ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC`; Schema/Beispiel, Tests `tests/test_fragment_refresh.py`

### Historische Tests & Energiebilanz (2026-07-05)

- [x] **stderr-Warnung `Keine historischen Daten in cons_data_hourly`** — `profile_manager.get_historical_day_data`: `cons_data_hourly.csv` fehlt oder ist leer (Datum in der Meldung = angefragter Tag, typisch heute via `consumer_targets` in der Live-UI); Ausgabe per `print()` → stderr; Fallback Grundlast 0,5 kW/h, Verbraucher-Tagesziele 0; Abhilfe: `runtime/cons_data_hourly.csv` pflegen (`main.py` oder `scripts/generate_cons_data.py`)
- [x] **Pre-commit / historische Testsuite validieren** — Nachholen von `--no-verify` (Commit `8721df2`): `pytest tests` inkl. 25× `test_historical_24h_consistency` grün; Pre-commit-Hook wieder sinnvoll nutzbar für Code-Änderungen
- [x] **`runtime/cons_data_hourly.csv`** aus Loxone-Logs regeneriert (≥12 Monate Retention)
- [x] **Test-Fixture** `tests/fixtures/historical/cons_data_hourly.csv` + `scripts/extract_historical_fixtures.py` (isoliert von Runtime)
- [x] **`test_historical_24h_consistency.py`:** Fixture-Pfad, parametrisierte Konsistenzläufe grün
- [x] **Bugfix** `simulate_horizon`: `finalize_chart_row_energy` nach jeder Stunde — Netzbezug konsistent mit gerundeten Flex-Spalten (Δ 8 W am Fall `2026-03-21_high_pv`)
- [x] **Testsuite-Inventur (optional / Env, kein Blocker):** Loxone-Integration (`test_loxone_integration.py`, 5× Skip ohne Env), thermische CSV-Fixtures (`tests/fixtures/thermal/` fehlt, 2× Skip) — bewusst unverändert offen

### UI main.py-Sync (2026-07-05)

- [x] **Doppelte UI-Wartezeit nach main.py-Durchlauf klären**
  - Ursache: feste 60-s-Phase (`delay`) ohne `completed_at`-Check, danach bis 120 s Grace (`wait_main`) — wirkte wie zweimaliges Warten
  - Fix: früher Exit bei Sync im aktuellen Slot; max. 60+30 s Wartezeit; UNC-Lesefix in `run_state`; einheitlicher UI-Hinweis; Tests `tests/test_schedule.py`
- [x] **UI: main.py-Sync schneller nach Durchlauf** — Fallback **15+15 s** (`optimizer/schedule.py`); Anzeige „nächster Abgleich spätestens in X s“ statt voller Fallback-Countdown (`sync_ui_countdown_seconds`, `ui/main_py_sync.py`); 15-s-Poll-Fragment `poll_main_py_sync_if_pending` + Footer (`ui/countdown.py`, `app.py`); Config `ui.main_sync_poll_sec` / Env `ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC`; Tests `tests/test_schedule.py`, `tests/test_main_py_sync_ui.py`

### UI Sunset-2-Sunset Epic abgeschlossen (2026-07-05)

- [x] Prod-Cockpit **Sunset-2-Sunset** (`ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting`); ersetzt Echtzeit, Historischer Tag, Produktiv-Archiv
- [x] Phasen 1–3 UI + Follow-up Layout; Phase 4 P4a–P4c (Betriebsmodi-Doku, Deployment-Querverweise, Navigationstests); P4d entfallen
- [x] Spec [docs/spec/ui-sunset2sunset.md](docs/spec/ui-sunset2sunset.md) **v0.7.0**; App-Version **1.14.0**
- Follow-ups (eigenständig im Backlog): Soll/Ist-Abweichung, Nachrechnung Backtesting, Preis-Spiegelung, optionales Layout/Mobil

### UI Sunset-2-Sunset — Phase 4 P4d entfallen (2026-07-05)

- [x] **P4d** gestrichen — dedizierte Missing-Slots-Tests entfallen; Abdeckung durch bestehende Chart-/Tabellen-Tests (Spec §6)

### UI Sunset-2-Sunset — Phase 4 P4c Navigationstests (2026-07-05)

- [x] **P4c** `tests/test_s2_navigation.py`: `segment_navigation_label`, `max_sunrise_cycle_offset`, `build_live_chart_context` (Segment-/Zyklus-Fenster, zone_reference, max_cycle ↔ Nav); Spec §4

### UI Sunset-2-Sunset — Phase 4 P4b Deployment & Querverweise (2026-07-05)

- [x] **P4b** `docker-compose-synology.yml` bestätigt (`sunset2sunset,backtesting`); `betrieb.md`, `container.md`, `docs/README.md`, `charts.md`, `ueberblick.md`, `preise.md`, `batterie-pv.md`; Spec-Status Phasen 1–3 erledigt

### UI Sunset-2-Sunset — Phase 4 P4a Betriebsmodi-Doku (2026-07-05)

- [x] **P4a** `docs/ui/betriebsmodi.md` auf Spec v0.6.2: Sunset-2-Sunset (Prod), Backtesting (Dev); SA₀→SA₁/SA₁→SA₂, Navigation, Panels, Kennzahlen Jetzt→SA₂; entfallene Modi; Env-Var `sunset2sunset,backtesting`

### UI Sunset-2-Sunset — Follow-up Layout (2026-07-05)

- [x] **Layout-a** Navigation kompakt zwischen Chart 1 und Chart 2; Segment-Label in Chart-1-Überschrift (`ui/history_navigation.py`, `ui/charts.py`, `ui/simulation_results.py`, `ui/live_mode.py`)
- [x] **Layout-b** Hilfe-„?“ (`ui/help_hint.py`, `st.popover`): Zonen (Chart 1), Chart 2 Ist/Prognose, Sync-Wartezeit, Modus-Scope am Seitentitel; Version als Caption neben Titel
- [x] **Datenbasis** Expander im Footer unter Trennlinie, vor Optimierungs-Takt (`ui/countdown.py`, `app.py`)
- [x] **H2/H6/H7** bewusst ohne Änderung (kein „Aktuelle Stunde“-Hinweis; Tabellen-/Energievergleich-Expander unverändert)
- [x] Docs: `docs/ui/charts.md`, Spec §7.1 in `docs/spec/ui-sunset2sunset.md`

### UI Sunset-2-Sunset — Phase 3 Charts & Kennzahlen abgeschlossen (2026-07-05)

- [x] **Phase 3 (P3a–P3d)** — Chart 2 Ist/Prognose, SA-Marker, Legacy-Cleanup Prod-UI, Kennzahlen-Horizont Jetzt→SA₂; Details in den Unterpunkten unten

### UI Sunset-2-Sunset — Phase 3 P3d Kennzahlen-Horizont Jetzt→SA₂ (2026-07-05)

- [x] **P3d** Ersparnis-/Kosten-Kennzahlen und Energievergleich über volle Matrix (Jetzt→SA₂), nicht Chart-Segment; Labels „(24h)“ entfernt; `[:24]` bei Grundlast/Profil-Zielen bereinigt (`ui/chart_context.py`, `ui/simulation_results.py`, `ui/charts.py`, `optimizer/targets.py`, `data/consumer_targets.py`); Tests `test_horizon_targets.py`, `test_chart_context.py`

### UI Sunset-2-Sunset — Phase 3 P3c Legacy-Pfade entfernt (2026-07-05)

- [x] **P3c** `history_offset_days`, Produktiv-Archiv-Navigation, Modus „Historischer Tag“ und `render_historical_*` aus Prod-UI entfernt; S-2 nur noch `render_s2_navigation` (`ui/history_navigation.py`, `ui/live_mode.py`, `app.py`, `ui/mode_selector.py`); `ui/historical.py` gelöscht; Tests `test_mode_selector.py`

### UI Sunset-2-Sunset — Phase 3 P3a Chart 2 Ist/Prognose (2026-07-05)

- [x] **P3a** Chart 2: „Ist bisher“ (Log) und „Prognose optimiert“ (MILP) getrennt, keine Brücke an Log/MILP-Grenze; Matrix-Index-Fix für SA₁→SA₂; matched baseline über volle Matrix (`ui/chart_context.py`, `ui/charts.py`, `optimizer/simulation.py`); Tests `test_chart2_s2_split.py`, `test_chart_context.py`

### UI Sunset-2-Sunset — Phase 3 P3b SA-Marker (2026-07-05)

- [x] **P3b** Vertikale Marker SA₀/SA₁/SA₂ im Chart (nur Anker im sichtbaren Fenster); **Jetzt** nur Live-Segment SA₀→SA₁ (`ui/charts.py`, `ui/simulation_results.py`); Tests `test_chart_ui_bugs.py`

### UI Sunset-2-Sunset — Chart-Darstellung (2026-07-05)

- [x] **SOC-Sprünge / fehlende Log-Slots (Spec §6)** — Orange vrect im Chart und Tabellenzeilen für `SLOT_MISSING`; sichtbare SoC-Lücken an Log/MILP-Grenze (kein fälscher Brückenpunkt) und neutral→grün (Extrap-Start); kein UTC-Versatz mehr bei SoC/Preis-X
- [x] **SoC-Lücke am Übergang neutral→grün** — extrapoliertes Segment ohne Brückenpunkt (`bridge_left` fälschlich für gesamtes MILP deaktiviert); Fix: nur an Log/MILP-Grenze (`abs_start == history_slot_count`); Test `test_soc_trace_bridges_extrapolation_start`
- [x] **Kein Strichwechsel/Transparenz in grüner Zone** — gepunktete Preis-Linie und 50 %-Opacity extrapolierter Traces entfernt (Kennzeichnung nur noch grüner Hintergrund, Spec §5)
- [x] **SoC/Preis-Zeitbezug im Chart** — Plotly-X für SOC- und Preis-Traces wurde fälschlich als `datetime64[ns, UTC]` erzeugt (+2 h Versatz in CEST, wirkte wie fehlende Linien bis zum Achsenrand); Fix: `_chart_time_series()` in `ui/charts.py`; Test `test_soc_and_price_traces_align_with_slot_datetimes`
- [x] **Grau-/Grünzone an X-Achsen-Rändern** — variable Slot-Dauer in `ChartSlotAxis`; Zonen auf Display-Slots (`ui/simulation_results.py`); Fensterrand SA₀/SA₁ via `x_range(range_start=chart.start)`; volle Grauzone bei Vergangenheits-Zyklen (`is_live_segment=False`)
- [x] **15-Min → 1-h gemischte Achse** — Preis stündliche HV-Treppe an Slot-Grenzen; Balkenbreite pro Slot (`_bar_widths_ms`); Zonen/vrect auf `display_ctx.slot_datetimes`
- [x] **SU-Marker entfernt** — nur noch Jetzt + SA (SOC)
- [x] **Tests:** `tests/test_chart_ui_bugs.py`, `tests/test_chart_mixed_resolution_traces.py` (Zeitbezug, Zonen, extrap-Brücke, gemischte Achse)

### UI Sunset-2-Sunset — Navigation SA-Zyklen (2026-07-04)

- [x] **Symmetrische Zyklus-Navigation** — `ui/s2_navigation.py` (reine Zustandslogik); `ui/history_navigation.py`: „Vor →“ bei `cycle_offset > 0` einen Zyklus Richtung Live, bei `cycle_offset == 0` Wechsel SA₁→SA₂; Zyklus zurück setzt Segment auf SA₀→SA₁ — **in Prod prinzipiell ok** (2026-07-04)
- [x] **Crash bei Zyklus zurück behoben** — fehlender SoC im Historie-Fenster (`TypeError` in `_soc_tail_y_from_row`); Baseline-SoC bei `history_only` aus; `None`/NaN-sichere SoC-Linien (`ui/charts.py`, `ui/simulation_results.py`)
- [x] **Tests:** `tests/test_s2_navigation.py`, `test_soc_tail_y_returns_none_for_missing_soc`

### Simulations-Tabelle & Datenbasis UI (2026-07-04)

- [x] **Fixierung Kopfzeile und Uhrzeit-Spalte** — scrollbare HTML-Tabelle mit CSS Freeze-Panes (`ui/simulation_table_view.py`); orange Zeilen via Pandas-Styler
- [x] **Datenbasis-Hinweis als Expander** — eingeklappt nur Produktiv-Log-Pfad, ausgeklappt voller Merge-/Runtime-Text
- [x] **Layout:** Simulations-Tabelle direkt unter Chart, vor Energievergleich
- [x] **Tests:** `test_simulation_results_table`, `test_production_log_source`

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

### Epic Soll-Ist (2026-07-05)

- [x] **Soll/Ist-Abweichung in Chart 1** — Icons Hinweis / Warnung / Fehler im grauen Produktiv-Log-Bereich
  - Spec [docs/spec/soll-ist-abweichung.md](docs/spec/soll-ist-abweichung.md) v0.2 · Regeln `config/deviation_rules.json`
  - P1–P4: Facts, Regelwerk, Slot-Auswertung, Chart-Marker, Szenario-Katalog S1–S7, [docs/ui/charts.md](docs/ui/charts.md)
  - Dev-Test: `scripts/seed_deviation_test_log.py`, VS Code Launch **Streamlit app.py (Deviation-Test)**

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
