🗺️ Projekt-Roadmap & Backlog

Erledigte Punkte → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Offene Bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research-Items
- [ ] Smart Energy App anschauen zum Vergleich
- [ ] Weitere Anbieter mit flexiblen Preisen anschauen
- [ ] Businessplan adaptieren

### Loxberry 4 Installation - Notizen
- [x] Update von bestehendem Loxberry auf 4.0 hat funktioniert
- [x] Installation des Docker Container Plugins hat funktioniert
- [x] Inbetriebnahme des Ernie-Stacks hat funktioniert und Worker / UI laufen!!!

## Feature-Backlog

### Version 1.25.0 — Backtesting mit Hauskonfiguration (UI-Nachzug)

**Basis erledigt** (siehe [Backlog-Erledigt.md](Backlog-Erledigt.md) § Version 1.25.0): Hauskonfigurator, Szenarieneditor, Backtesting-Runner, `cons_data`, Fingerprint, erste Charts/Tests.

**Offen:** Einheitliche Verbrauchs-UI, neuer Backtesting-Seitenaufbau, Abweichungsliste, Chart1/2-Detail (Scope nach Smoketest).

**Ist-Stand Code (Kurz):** `ui/consumption_comparison_panel.py` (nur Hauskonfigurator, Ist vs. Modell, nur KW-Navigation); `ui/backtesting_cons_data.py` (`total_kw`/`baseload_kw`/`pv_kw`); Backtesting-Seite noch mit Szenario-/Monat-Selectbox, Monats-Dataframe, Stundenkosten-Chart; Plausibilität ohne Cockpit-Chart1/2 (`backtesting_plausibility_charts.py`).

#### Getroffene Entscheidungen (2026-07-10)

| Thema | Entscheidung |
|-------|--------------|
| **Datenmodus Verbrauchs-UI** | **Modus A:** Hauskonfigurator = Ist-CSV vs. Modell. Backtesting = nur `cons_data` (historisch). Szenarieneditor = nur modelliertes Hausprofil. Kein Ist-vs-Modell-Vergleich auf Backtesting/Szenarieneditor. |
| **Monatsansicht Verlauf** | Stündlich innerhalb des gewählten Monats; Navigation ←/→ pro Monat. |
| **Wochenansicht Verlauf** | ISO-KW, stündlich (wie heute). |
| **Abweichungsdetail (Ziel)** | Volle Cockpit-Chart1/2 in **24h** und **SA_0–SA_2** — **aber** erst nach Smoketest `sunset_window` und Persistenz-Entscheid (siehe 1.25.e / 1.25.f). |
| **Monatskosten-Tabelle** | Dataframe-Tabelle im Monatsvergleich **entfällt**; Plotly-Monatschart **bleibt**. |
| **Gesamtkosten** | Neue kompakte Jahres-Tabelle (alle Szenarien inkl. Referenz) statt Metrik-Spalten allein. |

#### Offene Klärungen (für spätere Chats)

- [ ] **„Nicht optimierte Jahresverbräuche“** — gemeint vermutlich Referenz/`cons_data` (historisch ohne Optimierung), nicht optimierte Szenarien. Bestätigen?
- [ ] **Testlauf (1 Monat):** Verbrauchs-UI nur auf Testmonat beschränken; Navigation außerhalb disabled/leer?
- [ ] **Szenarieneditor:** Nur modelliertes Hausprofil des zugeordneten Profils (ohne `cons_data`, ohne CSV-Ist)?
- [ ] **PV in Verbrauchs-UI:** `pv_kw` als eigene Spur (Erzeugung) oder nur Verbraucher + Basislast?
- [ ] **Gesamtkosten-Tabelle:** Spalten — Szenario | Jahres-kWh | Jahres-€ | Δ vs. Referenz (weitere Spalten?)

- [ ] Nicht Software-Relevant: Nach Interessenten fragen in loxforum / reddit / ...
  - Habe Admins in loxforum nach der besten Stelle für einen Post gefragt
  - Soll unter "mein Projekt" gepostet werden

---

### Version 1.25.a — Verbrauchs-UI-Kern

Gemeinsame Streamlit-Komponente für Hauskonfigurator, Backtesting und Szenarieneditor.

- [ ] **Drei Modi** in einem Kernmodul (z. B. `ui/consumption_display/`):
  - `csv_validation` — Ist-CSV + Modell (Hauskonfigurator)
  - `cons_data` — `cons_data_hourly.csv` mit `{id}_kw`, `baseload_kw`, optional `pv_kw` (Backtesting)
  - `modeled_profile` — Hausprofil-Modell je Verbraucher (Szenarieneditor)
- [ ] **Monatsübersicht:** je Verbraucher eigener Balken; Summe = Gesamtverbrauch; Basislast als Residuum eigene Spur
- [ ] **Zeitverlauf:** Toggle **Monat | Woche**; ←/→ je nach Modus (Monat = stündlich, Woche = ISO-KW stündlich)
- [ ] **Datenschicht:** `build_modeled_hourly_kw_by_consumer()` in `data/consumption_profiles.py` (Split je Verbraucher + Basislast)
- [ ] **Tests:** Monatsaggregation, Navigation-Grenzen, per-Consumer-Split

**Manuelle Abnahme**

- [ ] Hauskonfigurator + CSV: Monatsbalken Ist vs. Modell; Toggle Monat/Woche; jeder Verbraucher + Basislast sichtbar
- [ ] `cons_data` synthetisch: gestapelte Monatsbalken summieren sich ≈ `total_kw`
- [ ] ←/→ Monat: stündlicher Verlauf; Woche: korrekte ISO-KW-Grenzen

---

### Version 1.25.b — Verbrauchs-UI in drei Seiten

- [ ] **Hauskonfigurator** — `render_consumption_comparison_panel` durch Kern, Modus `csv_validation`
- [ ] **Backtesting** — `render_cons_data_section`: Status/Generierung behalten, Visualisierung an Kern (`cons_data`)
- [ ] **Szenarieneditor** — Abschnitt „Verbrauchsprofil (Modell)“ beim Runtime-Hausprofil, Modus `modeled_profile`

**Manuelle Abnahme**

- [ ] Drei Seiten: gleiches Layout, Navigation, Legenden-Farben
- [ ] Szenarieneditor ohne Ist-Daten; Backtesting ohne Modell-Vergleich

---

### Version 1.25.c — Backtesting-Seitenaufbau

Ziel-Reihenfolge (oben → unten):

1. Verbrauchsdaten (`cons_data`) — Status, Generierung, Verbrauchs-UI
2. Konfigurierte Szenarien + Run-Buttons (wie heute)
3. **Gesamtkosten-Tabelle** (alle Szenarien inkl. Referenz)
4. **Verbrauchs-UI** (Referenz-Jahresverbrauch / nicht optimiert)
5. **Kostenvergleich** — Monatschart je Szenario; **ohne** Monats-Dataframe, **ohne** Stundenkosten-Chart

**Entfernen**

- [ ] `render_backtesting_controls` (Szenario-/Monat-Detailauswahl)
- [ ] `render_backtesting_hourly_chart`
- [ ] `st.dataframe` in `render_backtesting_monthly_table` (Chart behalten)

**Testlauf-Sonderfall:** Caption „Testlauf — nur Monat MM/YYYY“; Navigation auf diesen Monat beschränkt.

**Manuelle Abnahme**

- [ ] Voller Lauf: keine Szenario-/Monat-Selectbox, kein Stundenkosten-Chart
- [ ] Gesamtkosten-Tabelle mit Referenz + Szenarien + Δ
- [ ] Testlauf: Charts/Navigation nur für einen Monat

---

### Version 1.25.d — Abweichungsliste (Kostenvergleich)

- [ ] Einheitliche Liste auffälliger Fälle (Basis: `extract_critical_cases()` — Plausibilität + CBC-Events)
- [ ] Spalten: Fenster, Szenario, Art, Δ kWh (Soll/Ist)
- [ ] Auswahl eines Eintrags → Detailbereich (Platzhalter bis 1.25.f)
- [ ] Referenz-Szenario: keine Abweichungsliste

**Manuelle Abnahme**

- [ ] Lauf mit Abweichungen: sortierte Liste; Auswahl markiert Fenster + Szenario
- [ ] Sauberer Lauf: leere Liste / Info-Hinweis

---

### Version 1.25.e — Smoketest Backtesting `sunset_window`

**Zweck:** Klären, ob Backtesting im Modus `sunset_window` (Jetzt→SA₂) stabil läuft — **Voraussetzung** für die Entscheidung zu Chart1/2-Wiederverwendung (SA_0–SA_2-Modus).

**Hintergrund:** UI startet Backtesting ohne `--horizon-mode` → Standard `fixed_24h` (`simulation/horizon_mode.py`). Cockpit-Chart1/2 mit SA-Zonen setzt funktionierendes `sunset_window`-Backtesting voraus.

- [ ] **CLI-Smoketest** (Greenfield oder Test-Config mit Geo + PV + Batterie + Tarife):
  - `scripts/run_backtesting.py --horizon-mode sunset_window --start-month <M> --end-month <M>` (1 Monat)
  - Lauf endet Exit 0; `backtesting_log.json` enthält `"horizon_mode": "sunset_window"`
  - Plausibilität/CBC ohne unerwartete Abbrüche; Kosten plausibel vs. `fixed_24h`-Referenzlauf
- [ ] **Optional UI:** `--horizon-mode` an `build_backtesting_command` / Run-Controls (nur wenn Smoketest grün)
- [ ] **Ergebnis dokumentieren** (in diesem Kapitel oder Kurznotiz in Erledigt): ✅ stabil / ⚠️ mit Einschränkungen / ❌ blockiert

**Manuelle Abnahme**

- [ ] Smoketest-Protokoll: Kommando, Config-Pfad, Monat, Dauer, Exit-Code, `horizon_mode` im Log
- [ ] Bei Fehler: Log-Auszug + ob Blocker für 1.25.f

---

### Version 1.25.f — Chart1/2-Detail für Abweichungen (Scope nach 1.25.e)

**Abhängigkeit:** Scope und Priorität **nach** Smoketest 1.25.e neu bewerten.

**Technischer Engpass (heute):** `simulation/engine.py` persistiert nur aggregierte Stundenwerte (`sim_cost`, `sim_soc`, …), nicht `chart_rows` + `optimization_matrix` pro Fenster — Cockpit-Chart1/2 brauchen `OptimizationDisplayBundle` (`ui/simulation_results.py`).

| Smoketest-Ergebnis | Empfohlener Scope 1.25.f |
|--------------------|--------------------------|
| ✅ `sunset_window` stabil | **Voll:** 24h + SA_0–SA_2 mit Chart1/2; Fenster-Snapshots persistieren (failed windows + on-demand) |
| ⚠️ `sunset_window` mit Einschränkungen | **24h zuerst** mit Chart1/2; SA_0–SA_2 erst nach Follow-up-Fixes |
| ❌ `sunset_window` blockiert | **Nur 24h** mit Chart1/2; SA_0–SA_2 und Sunset-Zonen zurückstellen; Smoketest-Fix als eigenes Bugfix-Kapitel |

- [ ] **Persistenz:** Fenster-Snapshots (`chart_rows`, `matrix`, `meta`, `horizon_mode`, Szenario-ID) — Sidecar neben `backtesting_log.json` oder JSONL
- [ ] **Adapter:** `build_backtesting_display_bundle(window_anchor, mode=24h\|sunset)` → `OptimizationDisplayBundle`
- [ ] **UI:** Unter Abweichungsliste — `render_optimization_chart1/2`; Toggle 24h | SA_0–SA_2 (disabled wenn Log `fixed_24h` oder Smoketest negativ)
- [ ] **Fallback:** On-demand Re-Simulation eines Fensters (langsamer, weniger Speicher)
- [ ] **Tests:** Bundle-Builder-Fixture; Trace-Namen/Snapshot

**Manuelle Abnahme**

- [ ] Abweichung wählen → Chart1 Energiebilanz (PV, Batterie, Verbraucher-Stack, Zonen soweit Scope)
- [ ] Chart2 Kostenlinien Soll/Ist
- [ ] Toggle 24h ↔ SA_0–SA_2 (wenn im Scope)

**Abhängigkeiten**

```
1.25.a → 1.25.b → 1.25.c → 1.25.d → 1.25.e (Smoketest) → 1.25.f (Scope festlegen)
```

### Version 1.26.0 — Runtime-Entitäten & Tarife (Live)

**Scope:** Live-Prod (`main.py`, Sunset-2-Sunset-UI) nutzt dieselbe Referenz-Auflösung wie Backtesting (1.24). `runtime_settings` enthält nur Auswahl-IDs + Standort/Zeitzone (optional `pv_system_id`). Technische Parameter kommen aus `batteries[]` bzw. `config/tariffs.json`.

**Phasen:** P1 Datenmodell → P2 config.py-Auflösung → P3 Preis-Pipeline Live → P4 UI → P5 Migration/Tests/Doku.

**Abnahme:** Prod-`config.json` mit `battery_id` + Tarif-IDs; Live-Optimierung und UI zeigen aufgelöste Werte; Backtesting-Baseline unverändert kompatibel.

- [ ] **P1 — Datenmodell & Schema**
  - `runtime_settings`: `battery_id` (Pflicht nach Migration), `import_tariff_id`, `export_tariff_id`
  - Flache Batterie-/Tarif-Felder deprecated (Abwärtskompat: ID gewinnt, sonst Legacy-Felder)
  - Import-Tarif-Typ `monthly_table` ergänzen (symmetrisch zu Export)
  - [`config.schema.json`](config/config.schema.json), [`config/tariffs.schema.json`](config/tariffs.schema.json), Beispiel-Configs
- [ ] **P2 — Zentrale Auflösung in config.py**
  - `resolve_runtime_settings()` via bestehende `house_config`-Hilfen
  - `_load_dynamic_params()` / `get_battery_params()` / `get_runtime_settings()` aus aufgelöstem Dict
  - `get_backtesting_scenarios()`: Baseline ebenfalls auflösen (ein Codepfad)
- [ ] **P3 — Preis-Pipeline Live**
  - Bezug: `awattar` (EPEX + `awattar`-Block), `fixed_cent`, `monthly_table`
  - Einspeisung: `fixed`, `monthly_table`, `dynamic_epex` aus Tarif-Auflösung (nicht flache `k_push_cent`)
  - Anpassung: [`data/profile_manager.py`](data/profile_manager.py), [`data/market_prices.py`](data/market_prices.py), [`simulation/engine.py`](simulation/engine.py)
- [ ] **P4 — UI Live-Konfiguration**
  - [`ui/config_forms.py`](ui/config_forms.py): Dropdowns Batterie + Import-/Export-Tarif statt Einzelfelder
  - `update_runtime_settings()` speichert IDs; Anzeige aufgelöster Werte (read-only)
  - Optional gleiches Muster für `pv_system_id` (bereits in 1.24 vorbereitet)
- [ ] **P5 — Migration, Tests, Doku**
  - Prod-Migration: flache Werte → passende `batteries[]`-Einträge + Tarif-IDs (z. B. `home_5kwh`, `fixed_37ct`)
  - Tests in [`tests/test_house_config.py`](tests/test_house_config.py) + Live-Auflösungs-Test
  - Docs: [`docs/konfiguration/ueberblick.md`](docs/konfiguration/ueberblick.md), Sidebar-Hinweis


### Version 1.+1
- [ ] Readme ausführlicher machen mit Motivation / Nutzen
  - Sinnvolle Reihenfolge in der Nutzung beschreiben
  - Weniger technische Hintergründe beschreiben als Hinweise zur Installation und Konfiguration
- [ ] Weiteren Container für Windows machen und als reine Python-Umgebung (wenn das Sinn macht)
- [ ] Ausführung als "Web-App" prüfen

### Version 1.+1
- [ ] **E-Auto-MILP: optionale Nacharbeiten**

### Version 2.0 - Quality-Epic
- [ ] Ausführlicher Code-Review und Refactoring
- [ ] Möglichkeit für Test der Code-Coverage prüfen
- [ ] Möglichkeit zum automatisierten UI-Testing prüfen

### Version 2.+1
- [ ] Backtesting mit Scenarios auf Streamlit Community Cloud zur Verfügung stellen, um Leads zu generieren und evtl. als Affiliate Quelle (Bei Wechsel des Stromtarif-Anbieters oder bei Kontakt mit PV-Erstellern)

### Version 2.+1
- [ ] **SwimSpa Fall B — Folgeprüfung historische Leistung & Loxone-Trennung**
  - Prüfen, ob die historischen SwimSpa-Leistungslogs (`thermal_control.history_logs.power_csv` = `..._SwimSpa_Leistung_...csv`, Quelle `Ernie_Swim-Spa-P_act`) ebenfalls den **Filter-Anteil** enthalten (Fall B). Falls ja: Auswirkung auf die **Thermik-Modell-Kalibrierung** (`heat_loss_kw_per_k` etc.) bewerten — Filter (~0,18 kW) würde als Heizleistung fehlinterpretiert.
  - **Grundsatzfrage:** Sollte die Trennung Heizung/Filter besser **direkt in Loxone** geschehen (separater Heizungs-Leistungsmerker ohne Filter), statt softwareseitig per `subtract_consumer_ids`? Vorteil: konsistente Live- **und** Historien-Daten an der Quelle.
  - Bezug: Fall-B-Korrektur (Live-Ist) bereits umgesetzt; Thermik-Kalibrierung siehe **Thermik P1** (Swim-Spa)

### Version 2.+1
- [ ] **Empfehlungsmodus smarte/adaptive Geräte** (Folge des Empfehlungsmodus manuelle Geräte)
  - Adaptiv bzgl. Laufzeit/Energieverbrauch pro Lauf; smarte Geräte statt manueller Eingabe
  - Adaptionsalgo pflegt `appliances[].default_power_kw` aus den Loxone-Leistungsmerkern (`loxone_power_name`) — bisher nur reserviert, keine Live-Nutzung
  - Geschirrspüler-Leistung ggf. über Hue

### Version 2.+1
- [ ] csv-Datenformat für Verbraucher Jahresbedarf (außer Haus und E-Auto) definieren und Möglichkeit zum Importieren geben (zusätzlich zu Nennwerten). Jahresverlauf aus Nennwerten kann mit gemessenem Verlauf graphisch und summarisch verglichen werden. 
- [ ] Debug-Seite für Loxone-Kommunikation einrichten, bei der die eingelesenen Daten angezeigt werden mit letztem Update, ob Daten an die Loxone erfolgreich versendet wurden (mit Wert und Zeitstempel - wenn silentmode==false)

### Version 2.+1 — Test-Config entkoppeln
- [x] **Stufe 1 — Standard-Test-Config in `conftest.py`**
  - `ENERGY_OPTIMIZER_CONFIG_PATH` → `tests/fixtures/backtesting/config.json` (erzwingen, außer `ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG=1`)
  - `ENERGY_OPTIMIZER_OFFLINE=1` als Test-Default; `config.reinit_config()` beim Conftest-Start
  - Backtesting-Fixture-Config um `chart_color_index` ergänzt
- [x] **Stufe 1b — kaputte Tests reparieren**
  - `test_config_charge_immediate.py`: Inline-`tmp_path`-Config statt impliziter Prod-Werte
  - `test_matched_baseline.py`: E-Auto-Consumer als Inline-Fixture statt `config.get_flexible_consumers()`
- [ ] **Stufe 2 — `activate_test_config()` generalisieren** (aus `activate_backtesting_fixtures` ableiten; zweckgebundene Mini-Configs unter `tests/fixtures/config/`)
- [ ] **Stufe 3 — Test-Typen trennen** (Config-Loader vs. Domain vs. UI-Patch; keine nackten `config.get_*()` ohne Fixture)
- [ ] **Stufe 4 — Marker `requires_live_config`** für NAS/Prod-Integrationsläufe (`ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG=1`; `@requires_loxone` nutzt diesen Schalter bereits)
- [ ] **Stufe 5 (optional) — Config nur an Rändern** (reine Funktionen mit `consumers`/`battery_params` als Parameter)

### Version 2.+1
- [ ] **Debug-Dump Phase 2 — Dump-Formate und Reproduktion schärfen**
  - Ziel: Ein Debug-Dump soll einen Fall später **nachvollziehbar und möglichst reproduzierbar** machen, ohne erneut produktive Dateien zusammensuchen zu müssen
  - Dump-Typen klar trennen:
    - **Chart-Debug-Dump** für UI-/Darstellungsfehler
    - **Prod-Dump-Archiv** für fachliche/optimizerbezogene Fehlfälle
  - Je Dump-Typ festlegen:
    - Pflichtdateien
    - optionale Zusatzdateien
    - Manifest-Felder / Schema
  - Prüfen, ob ein **Replay-/Nachrechen-Pfad** aus einem Dump dokumentiert oder teilautomatisiert werden soll
  - Weitere Inputs nur ergänzen, wenn sie für reale Fehlfälle nachweislich relevant sind


### Version 2.+1 — Epics **Adaption** & **Thermik** (Architektur first)

Empfohlene Reihenfolge: **Adaption P1 → Adaption P2 → Adaption P3 → Thermik P1 → Thermik P2 → Thermik P3 → Adaption P4**

Validierung quer über alle Phasen: **Nachrechnung „Historischer Tag“** (0.+1, Dev-only) und bestehende Thermik-Backtests.

- [ ] **Adaption P1** — Generisches Adaptionsmodell (Skeleton)
  - Gemeinsame Struktur für Parameter-Adaption verschiedener Vorhersagemodelle:
    - Referenzwert (auf den adaptiert werden soll)
    - Veränderliche Parameter (mit Grenzen)
    - Zeithorizont (z. B. 24 h für PV/Gefrierschrank, 1 Jahr für Swim-Spa/Haus)
    - Start-Parameter aus `config.json`; Adaptionshistorie **getrennt**; Live-Parameter nur bei Bedarf korrigieren (Rhythmus am Zeithorizont orientiert)
  - Zielmodelle (später anbinden): PV-Ertrag, Wärmemodelle, Solar-Kollektor

### Version 2.+1
- [ ] **Adaption P2** — PV-Adaption (neuer Ansatz) — erster Pilot auf Adaption P1
  - Ersetzt Sidebar-PV-Tuning (mit UI Sunset-2-Sunset entfernt); siehe `runtime/pv_accuracy_log.csv`
  - Alten `pv_tuner`-Pfad ablösen oder in Adaption P1 integrieren

### Version 2.+1
- [ ] **Adaption P3** — Adaptionsalgorithmus (PV-Pilot)
  - Konkreter Update-Loop auf Adaption P2; Wärmemodelle bleiben weiterhin **linear** (Thermik-Adaption erst in Thermik P3)

### Version 2.+1
- [ ] **Thermik P1** — Isolierte Ein-Knoten-Modelle
  - Variable Wärmepfade (gegen Unendlich); ersetzt den Ein-Pfad-Sonderfall in `optimizer/thermal_model.py`
  - **Swim-Spa:** zweiter Wärmepfad in die Erde (Lookup `bodentemperaturen_nach_monat`):
    - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
  - **Gefrierschrank** (ehem. 0.+1 Prio2) — zweites isoliertes Referenzmodell
  - Abnahme: Kalibrierung/Backtest gegen historische Loxone-CSV-Logs

### Version 2.+1
- [ ] **Thermik P2** — Gekoppelte Ein-Knoten-Modelle
  - Haus ↔ Wärmespeicher ↔ Solaranlage
  - Parameter für Haus aus Energieausweis extrahieren (`C:\Users\joche\Documents\Hausbau\Hausbau_Köhler_Schreyögg\Energieausweis_komplett_EFH-Köhler_Dornbirn-2014.pdf`)
  - Klimaanlage als thermischen Verbraucher vorbereiten

### Version 2.+1
- [ ] **Thermik P3** — Thermik-Parameter-Adaption (auf Adaption P1)
  - `heat_loss_kw_per_k` und weitere lineare Modellparameter; Horizont je Verbraucher (24 h / 1 Jahr)

### Version 2.+1
- [ ] **Adaption P4** — UI Visualisierung Adaptionsalgos (nach Adaption P3 und Thermik P3)

### Version 2.+1
- [ ] Generisches E-Auto-Modell - für bessere Wiederverwendbarkeit

### Version 2.+1
- [ ] Bessere Verbrauchsoptimierung mit Geräten zur Temperaturkontrolle
  - [ ] Wärmepumpe (Prio3) — nur indirekte Steuerung über Anpassung der Solltemperaturen (nach **Thermik P2**)

### Version 2.+1
- [ ] Visualisierung des tatsächlichen Verbraucher-Verhaltens evtl. mit Empfehlungen

### Version 2.+1
- [ ] Konfigurationsseite einfügen zum einfachen Editieren der `config.json` und Szenarien

### Version 2.+1
- [ ] Was-wäre-wenn-Assistenten für Backtesting designen:
  - würde sich Ernie lohnen (mit aWATTar)?
  - würde sich (mehr) Batterie lohnen?
  - Verbraucher abfragen und daraus Verbraucherprofile generieren
- [ ] Erinnerung am Monatsanfang für Einspeisepreis (E-Mail von Loxone!)

### Version 2.+1
- [ ] **Optional: Live-Planungshorizont per `config.json` umschaltbar** (`planning_horizon.mode`: `fixed_24h` | `sunset_window`)
  - Aktuell Live nur `sunset_window` (Schema/Code); Backtesting kennt beide Modi bereits — Live-Verzweigung noch implementieren (`main.py`, `profile_manager`, UI-Chart, aWATTar-Fenster)
  - Modus **`fixed_24h`:** End-SOC-Verhalten **fest im Modus** verankern — wirtschaftlich äquivalent zu bisher `battery_end_soc_equals_start: true` (Start-SOC am Horizontende), **oder** harte Gleichheits-Nebenbedingung durch die bestehende **`battery_wear`-Strafe** einführen, die niedrigere End-SOCs angemessen „bestraft“ (eine Variante wählen, nicht beides parallel)
  - Modus **`sunset_window`:** unverändert **SOC_min am Sonnenaufgang** (hart)
  - Spec ergänzen, Live-Tests für beide Modi

### Version 2.+1 (Wird das noch gebraucht???)
- [ ] **Nachrechnung „Historischer Tag“ ins Backtesting** (Dev-only)
  - Beliebiger Kalendertag aus `cons_data_hourly.csv` + historische Preise; Umsetzung später klären (ersetzt Sidebar-Modus „Historischer Tag“)
- [ ] **Soll-Ist Hinweis-Regeln** — Kategorie „Hinweis“ sobald konkrete unkritische Fälle identifiziert (Follow-up Epic Soll-Ist)
- [ ] **Soll-Ist Nachrechnung (Backtesting)** — Regelwerk batchweise über historische JSONL / Prod-Dumps; Statistik je Kategorie (Follow-up Epic Soll-Ist)


## Packaging & Deployment

Empfohlene Reihenfolge offen: **7e** → **7g**

- [x] **7a–7d** — pyproject, Bootstrap, Build-Pipeline, Streamlit extern ([container.md](docs/einrichtung/container.md))
- [ ] **7e — Prod/Dev-Datensync** — Skript runtime/ + CSVs; dokumentierter Ablauf Dev ↔ Prod
- [ ] **7g — Lokale Dev-Stacks (Staging, ab 1.25)**

  **Scope:** Weitere Container-Stacks auf dem **lokalen Dev-PC** — **nicht** Greenfield (**1.24.c**) und **nicht** pytest-Fixtures (`Version 2.+1 — Test-Config entkoppeln`) und **nicht** Datensync (`7e`). `config/` bleibt bei Image-Updates unangetastet.

  **Phasen:** 7g-a Silent (Prod-Loxone) → 7g-b Simuliert (später).

  **Abnahme:** Silent-Stack liest produktive Loxone-Instanz, schreibt nicht (`loxone_silent_mode: true`); Simuliert-Stack erst nach Loxone-Simulator.

  - [ ] **7g-a — Silent-Stack** (Prod-Loxone, deploy-sicher)
    - Eigener Compose-Ordner: separate `config/` + `runtime/`, abweichende `container_name` und UI-Port
    - `runtime/local_settings.json`: `loxone_silent_mode: true` — Lesezugriff auf **produktive Loxone-Instanz**, keine Schreibzugriffe auf Miniserver/Huawei/Verbraucher
    - Prod-`config.json` als Vorlage oder per `ENERGY_OPTIMIZER_CONFIG_PATH`; Image-Updates (`pull`/`up -d`) überschreiben bestehende `config/` nicht
  - [ ] **7g-b — Simuliert-Stack** (Follow-up, nach Loxone-Simulator)
    - Eigener Stack ohne echte Loxone-Anbindung; vollständig synthetisches „Haus“ (Signale, Verbraucher, ggf. Backtesting-Fixtures)
    - Voraussetzung: Loxone-Simulator verfügbar — bis dahin offen lassen

## Referenz

### Log-Dateien (Review 2026-06)

| Datei | Status | Aktion |
|-------|--------|--------|
| `runtime/optimization_history.jsonl` | **kanonisch** | Produktiv-Historie |
| `runtime/energy_optimizer.log` | **aktiv** | Rotierend 5×5 MB |
| `runtime/optimizer_run_state.json` | **aktiv** | Letzter main-Durchlauf |
| `runtime/live_optimization_debug.json` | **aktiv** | App-24h-Debug |
| `runtime/system_history_log.csv` | **Legacy, nur Lesen** | Archivieren wenn JSONL reicht |
| `runtime/pv_accuracy_log.csv` | **Lesen aktiv, Schreiben aus** | siehe Epic **Adaption P2** |
| `backtesting_log.json` | **nur Dev** | nicht für Prod-NAS |
