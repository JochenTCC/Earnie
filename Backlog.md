🗺️ Projekt-Roadmap & Backlog

## Offene Todos
- [ ] **E-Auto-MILP: Phase 2–4** (Preset, Live Umschaltung, Tie-Break; Stand 2026-07-03)
  - **Basis:** Phase 1 erledigt — Backtesting (`logged_day`) ohne kontinuierliches `p[t]` im Solver, feste `P_nom × on[t]` (`optimizer/eauto_milp.py`, siehe Erledigte).
  - **Offene Phasen** (jeweils einzeln verifizieren):
    2. [ ] **Preset** für `remaining_kwh ≤ P_nom` im Backtesting — günstigste eligible Stunde, `p = clamp(remaining_kwh, P_min, P_nom)`; adressiert Kleinst-Restmengen (0,3–1,5 kWh) und 30 Plausibilitäts-Warnungen durch `P_nom`-Überlieferung.
    3. [ ] **Live Umschaltung Modus A↔B** nach Config-Schwelle (Vorschlag: `> 2×P_min` → Modus A mit `power_setpoint`; darunter binär wie Backtesting); inkl. PV-Follow / Sofortladen in Modus A.
    4. [ ] **Tie-Break ε₁/ε₂** in `_add_milp_objective` — **ε₁·Σ `on[t]`**, **ε₂·Σ `t·on[t]`** (E-Auto); Config-Pflichtparameter, `ε ≪ min(k_act)`; vor allem Modus A, Nachmessung ob nach Phase 1 noch nötig.
  - **Modus B im Code (Phase 1):** MILP mit `P_nom × on[t]` für alle Restmengen; Preset/`P_min`-Sonderfälle fehlen noch (Phase 2).
  - **Config (kein stiller Default):** Schwellwert Live A↔B, ε₁, ε₂ — Fehler wenn fehlend.
  - **Hinweis:** Backtesting-Einsparungen gelten mit vereinfachtem E-Auto-Modell, nicht 1:1 Live-Prognose.
  - **Später optional:** eligible-Stunden vorfiltern; lexikographisch zweistufig; SOC-/Netz-Straffaktoren; Degenerations-Erkennung → strict überspringen.
  - **Verknüpfung:** urgent-Regel-Review; Prod-Dump-`xfail` (Live, unabhängig von Phase 1); PWM/Mindestlademenge E-Auto (Live-Ausgabe Modus A).
- [ ] Batterieschädigung als Straffaktor in Optimierung einführen (lineares Amortisationsmodell, Angenommene Zyklenzahl 6000 - Gesamtkosten für Batterie (5 kWh) 1500€ --> Ein Hub = 1500/6000€)
- [ ] **End-SOC-Randbedingung im Live-Modus reviewen** (`battery_end_soc_equals_start`)
  - Aktuell testweise deaktiviert; prüfen, ob `SOC Ende == SOC Start` am 24h-Horizont für Live sinnvoll bleibt oder angepasst werden soll
  - Kontext: CBC-Hänger im Backtesting durch E-Auto Phase 1 behoben; Randbedingung selbst unabhängig davon prüfen
  - Offen: `end_soc_equals_start` wird in `_scenario_to_battery_params()` noch nicht an Backtesting-Szenarien durchgereicht
- [ ] PWM für E-Auto-Laden nur noch benutzen für Ströme < A_min, ansonsten ersetzen durch Mindestlademenge pro h (Zähler, der runterzählt und bei jedem Ladevorgang wieder geresettet wird -> Wenn Null, dann fünf Minuten laden mit Mindest-Strom)
- [ ] Erinnerung am Monatsanfang für Einspeisepreis (E-Mail von Loxone!)
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Gefrierschrank (Prio2)
  - [ ] Wärmepumpe (Prio3) - Nur indirekte Steuerung über Anpassung der Solltemperaturen
- [ ] Nutzung des Swim-Spa Filters reviewen (läuft derzeit ständig?)
  - Es gibt ein Signal "Ernie_Swimspa_Filter_Sollstunden", das angibt, wie lange der Filter laufen soll in den nächsten 24 Stunden
  - Es gibt ein Steuersignal "Ernie_Filter_Freigabe", mit dem der Filter ein- und ausgeschaltet werden kann
  - Ernie muss dafür sorgen, dass die Sollstunden in den nächsten 24 wieder auf Null kommen
  - Der Filter braucht eine bestimmte Leistung
  - In Loxone werden die Laufzeiten auf- und runter-integriert
- [ ] **urgent-Regel auf Notwendigkeit prüfen** (Review bis ca. **2026-07-12**, zwei Wochen nach Einführung der Observability)
  - Auswertung: `urgent_rule_observability` in `energy_optimizer.log` und `optimization_history.jsonl` (`role`: `redundant` / `nachholen` / `nur_urgent_fenster`)
  - Akzeptanz: Wenn durchgehend nur `redundant` → Nebenbedingung entfernen (reicht Gesamt-Deadline + Kostenminimierung); sonst behalten und kurz begründen
- [ ] **Prod-Dump-Regression: urgent-Nebenbedingung infeasible** (Stand 2026-07-03, Commit `a743318`)
  - Fixture: `eauto_urgent_deferred_cheap_hours_2026-06-28` (~7,99 kWh Rest bei `remaining_kwh_at_correction`)
  - **Symptom (Live, Modus A):** MILP mit `include_urgent_deadline_constraint=True` → CBC **Infeasible**; ohne urgent → **Optimal** (~6,59 kWh in günstigen Stunden). Unverändert nach E-Auto Phase 1 (betrifft nur Backtesting).
  - **Betroffene Tests** (`@pytest.mark.xfail` in `tests/test_prod_dump_regression.py`):
    - `test_prod_dump_milp_prefers_cheap_hours_after_urgent_fix`
    - `test_prod_dump_urgent_rule_redundant_vs_deadline_only`
  - **Nächster Schritt:** Live urgent + `power_setpoint` prüfen (ggf. nach Phase 3); `xfail` entfernen wenn feasible.
- [ ] Verbrauchshistorie anzeigbar Machen im Live Modus (ist nur unzulänglich implementiert)
  - [x] Erster Schritt ist erledigt
  - [ ] Es muss noch ein Weg gefunden werden, wie die tatsächlichen Verläufe angezeigt werden können, um Diskrepanzen zu erkennen
  - [ ] Der neue Modus muss noch mit dem alten Verfahren (Historischer Tag) vereinheitlicht werden. Eine Idee wäre, den Betriebsmodus links zu entfernen und bei Offline-Anzeige zwischen geloggten und neu optimierten Daten umschalten zu können - dann könnte ein Vergleich früherer Optimierungen mit aktueller angeschaut werden - ähnlich wie Vergleich Soll <> Ist
- [ ] Empfehlungsmodus für Waschmaschine und Geschirrspüler (Input: Laufzeit, mittlere Leistung / Output: Zeithorizont 6h: Güte des Startzeitpunkts)
- [ ] **Adaptives PV-Tuning wieder aktivieren** (`pv_accuracy_log.csv` / `log_pv_comparison`)
  - Lesen + Anwenden des Korrekturfaktors läuft noch (`calculate_tuning_factor`, `pv_forecast`, Sidebar)
  - Schreiben ist unterbrochen: `log_pv_comparison()` wird nirgends aufgerufen → Faktor bleibt praktisch bei 1,0
  - `get_pv_delta_and_update()` (Zähler-Delta) nutzen, aber Regel für Vergleich mit Prognose klären (15-Min-Takt vs. Stunden-kW)
  - Akzeptanz: CSV wächst wieder; Sidebar-Faktor ≠ 1,0 bei messbarer Abweichung; Synology-Mount für Log ggf. zurück in Compose
     
## Erledigte Punkte

### Backtesting & CBC (2026-07-03)
- [x] **E-Auto-MILP Modus B im Backtesting (Phase 1)** — Commit `c8a20c9`
  - `optimizer/eauto_milp.py` (`milp_uses_power_setpoint`, `milp_binary_charge_kw`); `optimizer/milp.py`: bei `logged_day` kein `consumer_p` für E-Auto, Lieferung/Bilanz über feste `P_nom × on[t]` (`consumer_milp_charge_kw`).
  - Tests: `tests/test_eauto_milp_mode.py`; `tests/test_milp_variable_power.py` bereinigt.
  - **Ursache der CBC-Hänger:** Symmetrie/Entartung bei E-Auto + `use_time_window` + `power_setpoint`; `gapRel=10 %` lieferte dieselben Kosten.
  - **Ergebnis:** Benchmark `2025-09-28` (hour-offset **1392**) strict ~445 s → ~0,05 s; `bench_cbc_gaps` 24h strict Minuten → ~0,8 s (gleiche Kosten); Jahres-Backtest 2025: **`strict_slow` 758 → 0**, Laufzeit ~357 s (4 Worker), Plausibilität **303/333** unverändert, 10 kWh dynamisch **774,13 €** (+461,87 €).
  - Diagnose: `scripts/bench_cbc_gaps.py`, `scripts/analyze_benchmark_window.py`, `backtesting_cbc_events.jsonl`.
- [x] **UTF-8 für Backtesting-Logs** — Commits `c8a20c9`, `a292adc`
  - `logger_config.configure_utf8_stdio`, `attach_utf8_log_file`; `scripts/run_backtesting --log-file`; `scripts/bootstrap_runtime.py`; `.vscode/settings.json` (Windows-Terminal `PYTHONUTF8`).
- [x] **CBC-Performance: zweistufiger Solver**
  - `optimizer/cbc_solver.py`: Strict mit Timeout (**3 s**), Fallback auf `gapRel=10 %`; Log bei fehlender Optimalität (`INFO` in `run_backtesting`).
  - Config: `cbc_gap_rel`, `cbc_strict_time_limit_sec` in `backtesting_scenarios.json` (+ Schema); Env-Overrides für Benchmarks (`ENERGY_OPTIMIZER_CBC_*`, `ENERGY_OPTIMIZER_CBC_STRICT=1`).
  - `optimizer/milp.py` nutzt `solve_with_strict_fallback` statt barem `PULP_CBC_CMD`.
- [x] **CBC-Gap-Diagnose & Benchmark-Tag** (Vorarbeit zu Phase 1)
  - `scripts/bench_cbc_gaps.py`, `scripts/analyze_benchmark_window.py` — siehe Phase-1-Ergebnis oben.
- [x] **Backtesting urgent / Zeitfenster (Vorarbeit)**
  - `optimizer/milp.py`: urgent-Nebenbedingung für `consumption_mode == "logged_day"` aus; Live: einfache `urgent_charging_indices`-Logik.
  - `use_time_window` bleibt `True` im historischen Pfad; Smoke-Test `tests/test_backtesting_smoke.py`.
- [x] **`run_backtesting` parallelisiert**
  - `--workers N` (Standard 1): Szenarien parallel via `ProcessPoolExecutor` (SoC-Kette bleibt pro Szenario sequentiell).
  - Beispiel: `python -m scripts.run_backtesting --start-month 8 --end-month 8 --workers 4` (~71 s für Aug 2025).
- [x] **Dynamische Einspeise (Awattar SUNNY Spot)**
  - `data/feed_in_prices.py`: `EPEX − fee_factor×|EPEX| + fix`; Config `awattar.feed_in_fee_factor`, `feed_in_mode` in Szenarien.
  - Vorzeichen in Kostenformel geprüft (Export bei negativem EPEX = Kosten, nicht Erlös).
  - **MILP-Zielfunktion:** stündliches `k_push_act` aus Matrix (`k_push_act_for_matrix_row`) — Abrechnung und Optimierung konsistent.
  - August 2025 Backtest: Runtime **4,39 €** vs. dynamisch **4,47 €** (vor MILP-Fix ~15 € Abstand durch falsches flat `k_push=6,4` im Solver).

- [x] Lineare Programmireung in optimizer.py einbauen (forecast_pv und forecast_consumption berücksichtigen)
- [x] Deployment auf Synology NAS einrichten
- [x] Aktuellen Ladezustand in Sankey-Diagramm verschieben (oben rausnehmen)
- [x] Versionsnummer einführen und anzeigen (Github-Release-Nr?)
- [x] Umgang mit historischen Verbrauchsdaten nochmal prüfen (wie funktioniert das genau, wie sollte mit Großverbrauchern umgegangen werden, wie gehen neue Daten ein) 
- [x] E-Auto / Swim-Spa / Wärmepumpe in die Optimierung mit reinnehmen mit Empfehlung, wann der beste Startzeitpunkt wäre bzw. autonomes Starten. 
- [x] Fiktive Simulation der historischen Daten mit einer größeren Batterie
- [x] Zulässigen Maximalstrom für E-Auto Laden für Ernie bereitstellen
- [x] Optimierung von main.py wird in App nicht richtig übernommen (kleinen Zeitversatz einbauen?) 
- [x] Vergangene Optimierungen anzeigbar Machen im Live Modus (debugging) 
- [x] Testsuite für 24h-Optimierung mit historischen Daten aufbauen
- [x] Dateistruktur aufräumen
- [x] Dateigrößen prüfen und ggf. refaktorieren
- [x] Ladeenergie für E-Auto anpassen (ist derzeit zu klein)
- [x] Ansicht Produktiv-Durchlauf wird nicht korrekt aktualisiert
- [x] Bei E-Auto wahrscheinliche Abwesenheite implementieren
- [x] Prüfen, ob ältere Programm-Logs noch benötigt werden *(2026-06: siehe unten)*
- [x] Steuersignale von main.py scheinen in Loxone wieder auf andere Werte gesetzt zu werden - Debug-Tool erstellen und Verhalten prüfen.
  — Da hat wohl eine alte noch laufende Instant von main.py regelmäßig dazwischengefunkt.
- [x] Chart für Ersparnis separat unter die anderen Zeitverläufe (kleiner?) packen. Vielleicht gemeinsam mit den stündlichen Kosten.  
  - die Balken müssen bei Einspeisung noch richtig dargestellt werden.
- [x] Simulation hat immer ein 24h-Zeithorizont - wenn nötig, mit gespiegelten Kosten des Vortags
- [x] "Silent-Modus" einführen, damit Tests in der Dev-Umgebung laufen können, während Produktiv-Variante läuft
- [x] Kostenchart fix skalieren (nicht flexibel)
- [x] Möglichkeit prüfen, ob variable Leistung bei E-Auto möglich und sinnvoll wäre
- [x] Prüfen, ob sich PV-Überschuss-Modus bei E-Auto sinnvoll einsetzen lässt. --> Ja ist möglich und sinnvoll
- [x] PV_Follow Modus in Loxone implementieren und beides testen
- [x] Zusätzliche Balken im Chart einfügen, die eingespeiste Energie anzeigen (ist als Linienverlau implementiert)
- [x] Kommunikation mit Bew-Meldern (Hue) prüfen (war ein Programmierfehler in loxone_publish)
- [x] Logik und UI für E-Auto verbessern
  - [x]Logik zum Zurücksetzen des Rest-SOC ist in Loxone implementiert - muss aber noch getestet werden. Rest-SOC wird beim Abstecken des Autos zurückgesetzt (auf 10%)
  - [x] Optimierung ausserplanmäßig anstoßen, wenn E-Auto angeschlossen wurde? --> umgesetzt (event_trigger in main.py)
  - [x] Ernie darüber Bescheid geben, wenn E-Auto SOFORT LADEN umgeschalten wird (als Event) und zur Berücksichtigung in der Optimierung
- [x] Ergebnisse des Produktivlaufs in Sankey-Diagramm integrieren und getrennte Anzeige entfernen.
- [x] Anzeige Plausibilität entfernen
- [x] Verhalten fehlerhaft, wenn kein Ladewecker aktiv und Auto nicht angehängt ist 29.06.
- [x] E-Auto wurde am 29.06. nicht richtig aufgeladen - Verhalten prüfen
- [x] Einspeisepotenzial aufzeichnen, um Trends zu erkennen 
- [x] Optional den stündlichen Einspeisepreis von Awattar berücksichtigen und Potenzial-Simulation durchführen *(erweitert 2026-07-03: dynamisches `feed_in_mode`, Backtesting-Szenario, siehe oben)*
- [x] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [x] Generell: Temperaturregelung bleibt eine "interne Logik"
  - [x] Generell: Ernie soll ein Prognose-Modell für Energiebedarf erstellen (mit der Zeit) - Einfaches Knotenmodell mit angenommener Wärmekapazität und Wärmeleitfähigkeit nach aussen.
  - [x] Generell: Folgende Temperaturen werden zur Verfügung gestellt: Soll- / Ist-Temperatur / Umgebungstemperatur (für Prognosemodell) / Erlaubte Differenz (bzw. Min- / Max Temp)
  - [x] Swim-Spa (Prio1) Hat großes Potenzial, da derzeit oft Energie vorgesehen wird, die gar nicht gebraucht wird - kann aber auch andersrum sein
    - [x] Für Temperaturvorhersage des Pools werden auch Außentemp-Vorhersagen benötigt


### Log-Dateien (Review 2026-06)

| Datei | Status | Aktion |
|-------|--------|--------|
| `runtime/optimization_history.jsonl` | **kanonisch** | Produktiv-Historie (main + App-Panel) |
| `runtime/energy_optimizer.log` | **aktiv** | Python-Logging (rotierend, 5×5 MB) |
| `runtime/optimizer_run_state.json` | **aktiv** | Letzter main-Durchlauf für App |
| `runtime/live_optimization_debug.json` | **aktiv** | App-24h-Debug-Snapshot |
| `runtime/system_history_log.csv` | **Legacy, nur Lesen** | Schreiben in main.py entfernt; App liest alte Einträge noch mit |
| `runtime/pv_accuracy_log.csv` | **Lesen aktiv, Schreiben aus** | `log_pv_comparison` in main anbinden (siehe Backlog) |
| `backtesting_log.json` | **nur Dev** | Backtesting-Modus, nicht für Prod-NAS |

Offen: Legacy-CSV irgendwann archivieren und `_load_legacy_csv_history` entfernen, wenn JSONL die komplette Historie abdeckt.

## Packaging & Deployment

Ziel: reproduzierbares Build/Deploy und weniger manuelle Schritte — ohne Änderungen an der Optimierungslogik.

Empfohlene Reihenfolge: 7b → 7c → 7a → 7d → 7e → 7f

- [x] **7b — Container-Bootstrap automatisieren**
  - Entrypoint + `scripts/bootstrap_runtime` (legt fehlende Dateien an, überschreibt nie)
  - Persistenz unter `config/` und `runtime/` (vereinfachte Compose-Mounts)
  - Config-Drift-Hinweise (`config/config.example.json` vs. Anwender-config, kein Auto-Merge)
  - Migration: `scripts/migrate_persist_layout.py`; Doku: [docs/einrichtung/container.md](docs/einrichtung/container.md)
  - Akzeptanz: frischer Container startet ohne manuelles Anlegen von Dateien
- [x] **7c — Build-Pipeline vereinheitlichen**
  - Kanonisch: `python -m scripts.build_container` / `build-container.ps1` (linux/amd64, Tags latest + Version)
  - Synology-Compose mit 7b abgeglichen; Deploy per `pull` + `up`
  - Doku: [docs/einrichtung/container.md](docs/einrichtung/container.md), [README.md](README.md)
- [x] **7a — Projekt-Metadaten (`pyproject.toml`)**
  - Version aus `version.py` (`[tool.setuptools.dynamic]`)
  - Abhängigkeiten in `pyproject.toml`; `requirements.txt` → `pip install .`
  - `[project.scripts]`: ernie-bootstrap, ernie-build-image, ernie-verify-loxone, …
  - Akzeptanz: `pip install -e .[dev]`, `pytest` grün
- [x] **7d — Streamlit extern bereitstellen**
  - Separater Service/Port im Compose (`optimizer-worker` + `optimizer-ui`)
  - Synology Reverse Proxy (HTTPS, Let's Encrypt) → `127.0.0.1:8501`; WebSocket-Header in der DSM
  - Fritzbox: 80 + 443 → NAS (8501 nur intern); Doku: [docs/einrichtung/container.md](docs/einrichtung/container.md)
  - Akzeptanz: App von außerhalb des NAS erreichbar (Netzwerk/VPN vorausgesetzt)
- [ ] **7e — Prod/Dev-Datensync**
  - Skript für `runtime/`, relevante CSVs, optional config-Template hin und zurück
  - Akzeptanz: dokumentierter Ablauf Dev ↔ Produktiv ohne Copy-Paste
- [ ] **7f — Loxberry-Container evaluieren (erst wenn auf Loxberry 4 umgestellt wurde) **
  - Erst nach 7b/7c; separates Compose oder Anleitung
  - Akzeptanz: Go/No-Go mit kurzer Notiz im README
