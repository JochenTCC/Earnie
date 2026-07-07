🗺️ Projekt-Roadmap & Backlog

Erledigte Punkte → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Offene Bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research-Items
- [ ] Smart Energy App anschauen zum Vergleich
- [ ] Weitere Anbieter mit flexiblen Preisen anschauen
- [ ] Businessplan adaptieren

## Feature-Backlog

### Version 1.21

Design & Detaildesign: [docs/spec/ui-menu-structure.md](docs/spec/ui-menu-structure.md).
Entscheidungen: `st.navigation`+`st.Page`; Config-Editor = Roh-JSON; `*`-Punkte nur Mockup; Dev-Modi bleiben gegated; Startgüte = Stromkosten (€); Horizont fest 6 h.
Abschluss: MINOR-Bump auf **1.21.0**; beide Punkte (Menüstruktur + Empfehlungsmodus) gemeinsam nach `Backlog-Erledigt.md`.

- [x] **Menüstruktur als Sidebar-Ersatz** (`st.navigation` + `st.Page`)
  - [x] Schritt 1 — Navigations-Gerüst: `app.py` → Router, `ui/pages/`; bestehende Modi (Cockpit, Backtesting, Preis-Prognose Dev) 1:1 als Seiten; Env-Gating bleibt
  - [x] Schritt 2 — Subpage Konfiguration: Roh-JSON-Editor für `config.json` (Validierung + Schema-Check, dann `config.reinit_config()`)
  - [x] Schritt 4 — Mockup-Seiten (funktionslos): Szenarieneditor*, Hauskonfigurator*, Verbraucheranalyse inkl. Adaptionsalgo* (zusätzlich „Manuelle Geräte" als Mockup-Menüpunkt bis Empfehlungsmodus)
  - [x] Backtesting- und Preis-Prognose-Controls von Sidebar in den Seiten-Body verschieben
- [ ] **Empfehlungsmodus manuelle Geräte** (Waschmaschine / Trockner / Geschirrspüler; Laufzeit + Leistung → Ranking der Startzeiten (je Stunde - sortiert ) in den nächsten  6 h)
  - [ ] Schritt 3a — `optimizer/appliance_recommendation.py` (reine Kosten-/Startzeit-Logik) + Tests
  - [ ] Schritt 3b — `ui/pages/page_devices.py`: Leistung Waschmaschine/Trockner aus Loxone-Merkern, Geschirrspüler manuelles Eingabefeld; Startgüte = Stromkosten (€); rein beratend
  - [ ] Config: neue Felder für Loxone-Merker `Leistung Waschmaschine` / `Leistung Trockner` (+ Schema/Example, Geräte-Block)
  - später*: smarte Geräte; adaptiv bzgl. Laufzeit/Energieverbrauch pro Lauf; Geschirrspüler-Leistung ggf. über Hue
- [ ] Schritt 5 — Abschluss: Backlog-Sync + Version-Bump 1.21.0


### Version 1.22
- [ ] **E-Auto-MILP: optionale Nacharbeiten**
- [ ] Neuen Loxberry aufsetzen bzw. produktiv-Loxberry auf 4 upgraden
- [ ] **7f — Loxberry-Container** — erst nach Loxberry 4; Go/No-Go im README
- [ ] Readme ausführlicher machen mit Motivation / Nutzen
- [ ] Nach Interessenten fragen in loxforum / reddit / ...

### Version 2.0
- [ ] Ausführlicher Code-Review und Refactoring

### Version 2.+1
- [ ] **SwimSpa Fall B — Folgeprüfung historische Leistung & Loxone-Trennung**
  - Prüfen, ob die historischen SwimSpa-Leistungslogs (`thermal_control.history_logs.power_csv` = `..._SwimSpa_Leistung_...csv`, Quelle `Ernie_Swim-Spa-P_act`) ebenfalls den **Filter-Anteil** enthalten (Fall B). Falls ja: Auswirkung auf die **Thermik-Modell-Kalibrierung** (`heat_loss_kw_per_k` etc.) bewerten — Filter (~0,18 kW) würde als Heizleistung fehlinterpretiert.
  - **Grundsatzfrage:** Sollte die Trennung Heizung/Filter besser **direkt in Loxone** geschehen (separater Heizungs-Leistungsmerker ohne Filter), statt softwareseitig per `subtract_consumer_ids`? Vorteil: konsistente Live- **und** Historien-Daten an der Quelle.
  - Bezug: Fall-B-Korrektur (Live-Ist) bereits umgesetzt; Thermik-Kalibrierung siehe **Thermik P1** (Swim-Spa)

### Version 2.+1
- [ ] **Nachrechnung „Historischer Tag“ ins Backtesting** (Dev-only)
  - Beliebiger Kalendertag aus `cons_data_hourly.csv` + historische Preise; Umsetzung später klären (ersetzt Sidebar-Modus „Historischer Tag“)
- [ ] **Soll-Ist Hinweis-Regeln** — Kategorie „Hinweis“ sobald konkrete unkritische Fälle identifiziert (Follow-up Epic Soll-Ist)
- [ ] **Soll-Ist Nachrechnung (Backtesting)** — Regelwerk batchweise über historische JSONL / Prod-Dumps; Statistik je Kategorie (Follow-up Epic Soll-Ist)

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


## Packaging & Deployment

Empfohlene Reihenfolge offen: **7e → 7f**

- [x] **7a–7d** — pyproject, Bootstrap, Build-Pipeline, Streamlit extern ([container.md](docs/einrichtung/container.md))
- [ ] **7e — Prod/Dev-Datensync** — Skript runtime/ + CSVs; dokumentierter Ablauf Dev ↔ Prod

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
