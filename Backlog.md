🗺️ Projekt-Roadmap & Backlog

Erledigte Punkte → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Offene Bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research-Items

## Feature-Backlog

### Version 0.+1
- [x] Entladesperre besser visualisieren (Farbe des Plots ändern?)
- [x] Einen "Rauf-Runter"-Balken für Energie-Gewinnung und Verbrauch anstatt Batterie-BAlken und Verbraucherbalken. *(Basis umgesetzt: `ui/chart_flow_balance.py`, `ui/flow_balance_allocate.py` — Follow-ups unten)*
- [x] **Chart 1 Rauf/Runter — Farbpalette Netz & Batterie** (neuer Chat)
  - **Netz** kräftig und gedämpft: **Blau** statt Rot (visuelles Gegenstück zu PV-Gelb)
  - Daraus abgeleitet: gedämpfte Flüsse für Netzbezug, Netz-Laden, Einspeisung ins Netz (falls abweichend von PV/Batterie)
  - Batterie-Flüsse (laden/entladen → Last vs. Einspeisung) farblich an die neue Zuordnung anpassen; Legenden/Hover konsistent
  - Dateien: `ui/chart_flow_balance.py`, `docs/ui/charts.md`, ggf. Netz-Linie `ui/charts.py` (`_COLOR_GRID_POWER`)
  - Tests/Szenarien A–H in `scripts/flow_balance_test_data.py` + `tests/test_chart_flow_balance.py` anpassen
- [ ] **Chart 1 Rauf/Runter — PV-Überschuss & volle Batterie** (neuer Chat)
  - Bei deutlichem PV-Überschuss und **keinem** (mehr) Ladebedarf (Batterie voll / SoC-Limit): **kein** Segment „Batterie laden (PV)“ — Überschuss als **Einspeisung (PV)** (gelb gedämpft)
  - Ursache vermutlich in `ui/flow_balance_allocate.py` (`allocate_slot_flows`): `charge_from_pv` begrenzen auf tatsächlich mögliche Ladung (nicht nur geplante `battery_charge` aus der Zeile)
  - Klären: SoC aus `Simulierter SoC (%)` / Batterieparameter vs. reine Bilanz aus Zeilenwerten; Randfall Szenario E (Überschuss ohne negatives `Netzbezug`)
  - Regression: neues Szenario „volle Batterie + PV-Überschuss“; Streamlit-Produktivdaten neutral/grau prüfen
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
- [ ] Debug-Dump einführen, in den alle relevanten Daten (inkl. config.json etc. ) abgelegt werden, damit später reproduzierbar gedebuggt werden kann.
- [ ] **E-Auto-MILP: optionale Nacharbeiten**

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
