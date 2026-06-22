# Migrationsplan: Dateistruktur Energy-Optimizer

Ziel: Bessere Übersicht und Pflegbarkeit, ohne Deployment oder tägliche Workflows zu brechen.

**Leitplanken**

- `main.py`, `app.py`, `config.py`, `config.json` bleiben in der **Projektwurzel**
- Jeder Schritt endet mit **`pytest`** und einem kurzen **Smoke-Test** (Streamlit + ein `main.py`-Durchlauf)
- Verschobene Module bekommen zunächst eine **Kompatibilitäts-Shim-Datei** an der alten Stelle (Re-Export), die erst in Phase 6 entfernt wird
- Kein Big-Bang: ein Merge/Commit pro abgeschlossener Phase

**Zielstruktur (Endzustand)**

```
Energy-Optimizer/
├── main.py
├── app.py
├── config.py / config.json
├── version.py
├── logger_config.py
│
├── optimizer/           # Facade + Implementierung
├── integrations/        # Loxone, Awattar, Log-Import
├── data/                # Profile, Verbrauch, PV
├── simulation/          # Backtesting-Engine
├── runtime_store/       # JSON-Persistenz
├── ui/                  # Streamlit-Komponenten
├── scripts/             # CLI/Wartung
│
├── tests/
└── runtime/             # Laufzeit-JSON (unverändert)
```

---

## Fortschritt

| Phase | Status | Datum / Notiz |
|-------|--------|---------------|
| 0 Vorbereitung | offen | |
| 1 scripts/ | **erledigt** | Wrapper in Wurzel für generate_cons_data + run_backtesting |
| 2a ui/ Grundgerüst | **erledigt** | styles, runtime_config, mode_selector, auto_refresh |
| 2b config_forms | **erledigt** | |
| 2c charts | **erledigt** | |
| 2d Modus-Panels | **erledigt** | inkl. simulation_results.py |
| 2e schlankes app.py | **erledigt** | ~75 Zeilen |
| 3 optimizer/ | **erledigt** | Facade in optimizer/__init__.py, Shims in Wurzel |
| 4 integrations + data + simulation | offen | |
| 5 runtime_store/ | offen | |
| 6 Cleanup | offen | |
| 7 pyproject (optional) | offen | |

---

## Phase 0 — Vorbereitung (½ Tag)

**Ziel:** Sicherer Ausgangszustand, keine funktionalen Änderungen.

| Aktion | Details |
|--------|---------|
| Baseline-Tests | `pytest` grün dokumentieren |
| Import-Inventar | `rg "^import \|^from " --glob "*.py"` als Referenz speichern |
| README prüfen | Verweis auf fehlendes `containers.build` notieren (Phase 6) |
| Branch | `refactor/file-structure` anlegen |

**Akzeptanzkriterium:** `pytest` grün, Streamlit startet, `main.py` läuft einmal durch (oder bricht erwartbar ab ohne Loxone).

---

## Phase 1 — Skripte isolieren (geringes Risiko, ~1 h)

**Ziel:** Wurzelverzeichnis entrümpeln, keine Import-Ketten anfassen.

| Verschieben nach `scripts/` | Umbenennung |
|-----------------------------|-------------|
| `GenerateConsData.py` | `generate_cons_data.py` |
| `run_backtesting.py` | `run_backtesting.py` (bleibt) |
| `merge-logs.py` | `merge_logs.py` |

**Anpassungen**

- `.vscode/launch.json`: Pfade auf `scripts/run_backtesting.py`
- Fehlermeldungen in `profile_manager.py`, `simulation_engine.py`, `backtesting_log.py`: Texte auf `scripts/generate_cons_data.py` etc.
- Optional: dünne Wrapper in der Wurzel (nur wenn alte Aufrufe behalten werden sollen)

**Tests:** `pytest`  
**Smoke:** `python -m scripts.run_backtesting --help`

**Hinweis:** `GenerateConsData.py` und `run_backtesting.py` in der Wurzel sind dünne Kompatibilitäts-Wrapper.

---

## Phase 2 — `app.py` aufbrechen (höchster Nutzen, ~2–3 Tage)

**Ziel:** `app.py` auf ~80–120 Zeilen (nur `main()`, Routing, Page-Config).

### 2a — `ui/`-Grundgerüst

```
ui/
├── __init__.py
├── styles.py          # inject_compact_numeric_css
├── runtime_config.py  # reload_runtime_config, get_runtime_settings, update_config_file, Cache-Helfer
├── mode_selector.py   # render_mode_selector, get_enabled_ui_modes, UI_MODE_*
└── auto_refresh.py    # setup_auto_refresh
```

`render_parameter_input` wandert in **Phase 2b** (`ui/config_forms.py`), da es `render_config_form` benötigt.

Zusätzlich: `ui/simulation_results.py` für gemeinsame Ergebnis-Darstellung (Live + Historisch).

**Akzeptanz:** `app.py` importiert aus `ui.*`; Streamlit startet; `pytest` grün.

### 2b — Konfigurations-UI

```
ui/config_forms.py     # render_pv_config_inputs, render_battery_config_inputs, render_config_form, render_pv_tuning_sidebar, render_parameter_input
```

### 2c — Charts (Zeilen ~672–905 in altem app.py)

```
ui/charts.py         # get_bar_colors, add_power_traces, render_optimization_chart, alle _chart_* Helfer
```

### 2d — Modus-spezifische Panels

| Modul | Inhalt |
|-------|--------|
| `ui/history_panel.py` | `render_optimization_history_panel` + Helfer |
| `ui/backtesting.py` | `render_backtesting_block` + alles Backtesting |
| `ui/historical.py` | `render_historical_*`, `load_historical_matrix` |
| `ui/live_mode.py` | Live-Optimierung, Savings, Debug |
| `ui/sankey.py` | Sankey + `render_live_power_flow` |
| `ui/sync_panel.py` | `render_main_run_sync_panel` |
| `ui/countdown.py` | `render_countdown_block` |

### 2e — Schlankes `app.py`

Nur Page-Config, Routing, `main()`.

**Regeln beim Extrahieren**

- Keine neuen Default-Parameter in Berechnungsfunktionen
- Gemeinsame Imports pro Modul, nicht alles in `ui/__init__.py`
- Streamlit-`@st.fragment` bleibt bei der Funktion, die es nutzt

**Tests:** `pytest`  
**Smoke:** Alle drei UI-Modi in Streamlit durchklicken (Live, Historischer Tag, Backtesting)

---

## Phase 3 — Optimizer physisch gruppieren (~1 Tag)

| Alt (Wurzel) | Neu |
|--------------|-----|
| `optimizer.py` | `optimizer/__init__.py` (Facade + `__all__`) |
| `optimizer_battery.py` | `optimizer/battery.py` |
| `optimizer_milp.py` | `optimizer/milp.py` |
| `optimizer_simulation.py` | `optimizer/simulation.py` |
| `optimizer_targets.py` | `optimizer/targets.py` |
| `charging_context.py` | `optimizer/charging_context.py` |
| `optimization_schedule.py` | `optimizer/schedule.py` |
| `optimization_consistency.py` | `optimizer/consistency.py` |

**Tests:** `pytest`, besonders `test_optimizer_facade.py` und `test_historical_24h_consistency.py`

---

## Phase 4 — Integrationen & Daten (~1 Tag)

### 4a — `integrations/`

`loxone_client.py`, `awattar_client.py`, `loxone_log_import.py` → `integrations/` + Shims in Wurzel

### 4b — `data/`

`profile_manager.py`, `cons_data_store.py`, `consumer_targets.py`, `live_consumption.py`, `pv_forecast.py`, `pv_tuner.py`, `data_loader.py` → `data/` + Shims

### 4c — `simulation/`

`simulation_engine.py` → `simulation/engine.py`, `backtesting_log.py` → `simulation/backtesting_log.py` + Shims

---

## Phase 5 — Runtime-Persistenz (~½ Tag)

`run_state.py`, `optimization_history.py`, `live_optimization_debug.py`, `file_metadata.py` → `runtime_store/`

**Hinweis:** `runtime/` = Laufzeit-**Daten**; `runtime_store/` = **Code** für Persistenz.

---

## Phase 6 — Aufräumen & Doku (~½ Tag)

- Shims entfernen, Imports projektweit anpassen
- `Backlog.md`: „Dateistruktur aufräumen“ abhaken
- `README.md` aktualisieren

---

## Phase 7 — Optional: installierbares Paket

Nur bei Bedarf für Wiederverwendung außerhalb des Repos (`pyproject.toml`).

---

## Abhängigkeiten zwischen Phasen

```
Phase 0 → Phase 1, Phase 2
Phase 1 → Phase 6
Phase 2a–2e → Phase 6
Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 (optional)
```

Phase 1 und Phase 2 können parallel laufen.

---

## Checkliste pro Schritt

```
[ ] Branch aktuell
[ ] Nur ein thematisches Paket/Modul pro Commit
[ ] pytest
[ ] Streamlit: app.py startet
[ ] Optional: main.py einmal ausführen
[ ] Keine neuen stillen Default-Parameter in Optimierungslogik
[ ] Fehlermeldungen mit neuen Pfaden aktualisiert
```

---

## Risiken & Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|--------|----------------|
| Zirkuläre Imports nach `ui/`-Split | Charts und Live-Mode nicht gegenseitig importieren |
| Docker/Synology bricht | `main.py`/`app.py` nie verschieben |
| Tests importieren alte Pfade | Shims bis Phase 6 |
| `config.py` gitignored | Nicht in Unterpaket verschieben |

---

## Empfohlene Reihenfolge

- [ ] Phase 0
- [x] Phase 2a 
- [x] Phase 2b 
- [x] Phase 2c 
- [x] Phase 2d 
- [x] Phase 2e 
- [x] Phase 1
- [x] Phase 3
- [ ] Phase 4 → 5
- [ ] Phase 6
- [ ] Phase 7 (optional)
