🗺️ Projekt-Roadmap & Backlog

## Offene Todos

**Verknüpfung:** urgent-Regel-Review (bis ca. 2026-07-12) ↔ Prod-Dump-`xfail` (Live, Modus A) ↔ PWM/Mindestlademenge E-Auto.

- [ ] **Sunset-Planungshorizont + SOC_min am Sonnenaufgang** (Branch `feature/sunset-planning-horizon`)
  - Spec: [docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)
  - Fenster: Jetzt→SA₁ + SA₁→SA₂; harte SOC-Randbedingung am nächsten Sonnenaufgang; danach frei bis SA₂
  - Ersetzt `battery_end_soc_equals_start` im Live-Betrieb (deprecated)
  - UI Live: sunrise→sunrise; Zonen grau (Vergangenheit) / neutral (jetzt→SA) / grün (Rest); SA₂-Ausblick Phase 2
  - Backtesting: unverändert E-Auto-`ready_by_hour`-Anker, SOC am Fensterende frei, Kette zum nächsten Fenster
  - [x] Phase 1: `data/planning_window.py` + Tests
  - [x] Phase 2: Matrix/Preise/PV generalisieren, MILP SOC-Anker
  - [x] Phase 3: `main.py`, Live-Simulation — **Live-Durchlauf verifiziert 2026-07-04**
  - [x] Phase 4: UI sunrise→sunrise mit Zonenfarben — **verifiziert 2026-07-04**
  - [ ] **SA₂-Ausblick in UI** (Spec Phase 2): erweiterter MILP-Horizont bis SA₂, eigene Darstellung
  - [ ] **Preis-Spiegelung:** statt einzelner Spiegelquelle (gleiche Uhrzeit, bis 7 Tage zurück) ggf. **Mittelung über mehrere vergangene Tage** prüfen — Genauigkeit/Robustheit vs. Einfachheit; Kontext `data/market_prices.py` (`resolve_market_slots`)
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
  - [ ] Einen Adaptionsalgo einbauen, der definierte Parameter selbständig ändert, um Vorhersage zu verbessern. Die Wärmemodelle bleiben weiterhin linear  
- [ ] PWM für E-Auto-Laden nur noch benutzen für Ströme < A_min, ansonsten ersetzen durch Mindestlademenge pro h (Zähler, der runterzählt und bei jedem Ladevorgang wieder geresettet wird → wenn Null, fünf Minuten laden mit Mindest-Strom)
- [ ] Erinnerung am Monatsanfang für Einspeisepreis (E-Mail von Loxone!)
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Gefrierschrank (Prio2)
  - [ ] Wärmepumpe (Prio3) — nur indirekte Steuerung über Anpassung der Solltemperaturen
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
- [ ] Verbrauchshistorie im Live-Modus (nur unzulänglich implementiert)
  - [x] Erster Schritt erledigt
  - [ ] Ist-Verläufe anzeigen (Diskrepanzen erkennen)
  - [ ] Vereinheitlichung mit „Historischer Tag“ (Modus-Umschaltung geloggt vs. optimiert)
- [ ] Empfehlungsmodus Waschmaschine / Geschirrspüler (Laufzeit, Leistung → Startgüte in 6 h)
- [ ] **E-Auto-MILP: optionale Nacharbeiten**
  - **Hybrid-Lieferung / Preset-Rest:** experimentell verworfen (Jahres-Backtest 2025)
- [ ] **Adaptives PV-Tuning wieder aktivieren** (`pv_accuracy_log.csv` / `log_pv_comparison`)
  - Schreiben unterbrochen: `log_pv_comparison()` nicht angebunden → Faktor bleibt bei 1,0
  - Akzeptanz: CSV wächst; Sidebar-Faktor ≠ 1,0 bei Abweichung
- [ ] Generische Modelle für Verbraucher anhand der konkreten Beispiele entwickeln
  - E-Auto-Modell
  - Wärme-Modelle
    - Isolierte Ein-Knoten-Modelle (Gefrierschrank, Swimspa), aber mit variablen Wärmepfaden (gegen Unendlich)
    - Gekoppelte Ein-Knoten-Modelle (Haus <-> Wärmespeicher)

## Erledigte Punkte

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

### Sunset-Planungshorizont Live (2026-07-04)

- [x] **Phasen 1–3:** Fenster `Jetzt→SA₂`, SOC_min am Sonnenaufgang, variable Optimierungsmatrix
  - Spec: [docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)
  - Day-Ahead für variable Fensterlänge (`resolve_market_slots`); aWATTar-Abruf bis SA₂
  - Preis-Spiegelung: gleiche Uhrzeit, bis 7 Tage zurück; aWATTar-Lookback für Spiegelquellen
  - Zeitzonen-Ausrichtung Planungs-Slots ↔ aWATTar (`Europe/Vienna`)
  - Loxone-Verify: fehlende E-Auto-Fertig-Uhrzeit nur **Warnung** (nicht angeschlossen)
- [x] **Phase 4:** UI sunrise→sunrise mit Zonenfarben (grau/neutral/grün), Marker, Navigation
  - `ui/chart_context.py`: Chart-Fenster, Zeilen-Ausrichtung, Kosten-Summe nur über sunrise→sunrise
  - Live-Navigation ←/→; Button **Produktiv-Archiv** für 24h-Historie (Sankey/Countdown dort deaktiviert)
  - Platzhalter-Slots im Chart: NaN-sichere Hilfsfunktionen in `ui/charts.py`
  - Debug-Snapshot: `slot_datetime` (pandas Timestamp) JSON-serialisierbar; Persist nach Chart-Render
  - Sankey **Energiefluss (Live)** unverändert unterhalb der Charts in `app.py`

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

### Log-Dateien (Review 2026-06)

| Datei | Status | Aktion |
|-------|--------|--------|
| `runtime/optimization_history.jsonl` | **kanonisch** | Produktiv-Historie |
| `runtime/energy_optimizer.log` | **aktiv** | Rotierend 5×5 MB |
| `runtime/optimizer_run_state.json` | **aktiv** | Letzter main-Durchlauf |
| `runtime/live_optimization_debug.json` | **aktiv** | App-24h-Debug |
| `runtime/system_history_log.csv` | **Legacy, nur Lesen** | Archivieren wenn JSONL reicht |
| `runtime/pv_accuracy_log.csv` | **Lesen aktiv, Schreiben aus** | siehe Backlog PV-Tuning |
| `backtesting_log.json` | **nur Dev** | nicht für Prod-NAS |

## Packaging & Deployment

Empfohlene Reihenfolge offen: **7e → 7f**

- [x] **7a–7d** — pyproject, Bootstrap, Build-Pipeline, Streamlit extern ([container.md](docs/einrichtung/container.md))
- [ ] **7e — Prod/Dev-Datensync** — Skript runtime/ + CSVs; dokumentierter Ablauf Dev ↔ Prod
- [ ] **7f — Loxberry-Container** — erst nach Loxberry 4; Go/No-Go im README
