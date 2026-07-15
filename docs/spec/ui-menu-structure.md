# Spezifikation: UI-Menüstruktur (Sidebar-Ersatz) + Empfehlungsmodus manuelle Geräte

**Version:** 0.1.0  
**Status:** Geplant (Design abgestimmt 2026-07-07) — Umsetzung offen  
**Bezug:** Backlog `### Version 1.21` (Menüstruktur Z. 15–20 + Empfehlungsmodus Z. 21)  
**Ersetzt:** Sidebar als Steuer-/Parameter-Container (`ui/mode_selector.py` Radio, `ui/config_forms.py`, Sidebar-Controls in `ui/backtesting.py` und `ui/price_forecast.py`)

## 1. Ziel

Die bisherige Single-Page-App (`app.py` + Steuerung komplett in der Sidebar) wird durch eine **native Menüstruktur** ersetzt. Jeder bisherige Modus wird eine eigene Seite; neue Seiten kommen hinzu. Die Sidebar zeigt danach nur noch die **Navigation**, alle Steuer-/Parameter-Widgets liegen im jeweiligen Seiten-Body.

## 2. Scope & Abgrenzung

Backlog-Einträge mit `*` = später, hier nur als **funktionsloses Mockup**.

| Seite | Backlog | Jetzt umgesetzt | Mockup* |
|-------|---------|-----------------|---------|
| Menüstruktur (Sidebar-Ersatz) | Z. 15 | ✅ | |
| Manuelle Geräte + Empfehlungsmodus | Z. 16 + Z. 21 | ✅ | |
| Konfiguration (Roh-JSON-Editor) | Z. 17 | ✅ | |
| Backtesting | Z. 18 | ✅ (Umzug) | Szenarieneditor* |
| Hauskonfigurator | Z. 19 | | ✅ |
| Verbraucheranalyse + Adaptionsalgo | Z. 20 | | ✅ |
| Preis-Prognose (Dev) | bestehend | ✅ (Umzug) | |

**Hinweis zur Scope-Erweiterung:** Der Empfehlungsmodus (Backlog Z. 21) ist im Backlog ein eigener Punkt, wird aber bewusst zusammen mit der Menüstruktur umgesetzt („full_now").

## 3. Abgestimmte Entscheidungen

| Thema | Entscheidung |
|-------|--------------|
| Navigation | `st.navigation` + `st.Page` (nativ, Streamlit 1.58) |
| Manuelle Geräte | inkl. Empfehlungsmodus (Z. 21) jetzt |
| Config-Editor | Roh-JSON-Editor für `config.json` |
| `*`-Punkte | funktionslose Platzhalter-Seiten in der App |
| Dev-/Nebenmodi | als Menüpunkte, weiter per config/Env gegated |
| Startgüte | reine Stromkosten (€) je möglicher Startzeit |
| Loxone-Merker | neue Config-Felder (`Leistung Waschmaschine`, `Leistung Trockner`) |
| Empfehlungshorizont | je Gerät aus Hausprofil (`schedule.start_shift_h` bei `earnie_role: manual`) |
| Geschirrspüler-Leistung | manuelles Eingabefeld in der UI |

## 4. Navigations-Architektur

`app.py` wird zum schlanken Router über `st.navigation`. Bestehende Renderlogik (`live_mode`, `backtesting`, `price_forecast`) wird **wiederverwendet**; nur die Sidebar-Aufrufe wandern in den Seiten-Body.

```text
app.py (Router: st.navigation / st.Page)
└── ui/pages/
    ├── page_cockpit.py           # bestehender S-2-Block (live_mode + sankey + countdown)
    ├── page_devices.py           # Manuelle Geräte + Empfehlungsmodus (Z. 16 + 21)
    ├── page_config.py            # Roh-JSON-Editor für config.json (Z. 17)
    ├── page_backtesting.py       # wrappt ui/backtesting.py, Controls im Body (Z. 18)
    ├── page_price_forecast.py    # wrappt ui/price_forecast.py (Dev, gegated)
    ├── page_scenario_editor.py   # Mockup*
    ├── page_house_config.py      # Mockup*
    └── page_consumer_analysis.py # Mockup*
```

- `ui/mode_selector.py` entfällt als Radio (Modus = Seite). Das Env-Gating (`ENERGY_OPTIMIZER_UI_MODES`, `ui.price_forecast_page_enabled`) bleibt erhalten und steuert nur noch, **welche Seiten registriert** werden.
- Live-Panels (Auto-Refresh, `main_py`-Sync) bleiben an das Cockpit-Fenster SA₀→SA₁ gebunden (unverändert, siehe `ui-sunset2sunset.md`).

## 5. Seiten im Detail

### 5.1 Cockpit (bestehend)

Wrappt den bisherigen Sunset-2-Sunset-Block: `render_optimization_savings_and_chart` + `render_live_power_flow` + `render_countdown_block`. Keine funktionale Änderung, nur Umzug in eine Seite.

### 5.2 Manuelle Geräte + Empfehlungsmodus (Z. 16 + Z. 21)

Pro Gerät (Waschmaschine, Trockner, Geschirrspüler):

1. **Leistung & Laufzeit:** aus Hausprofil (`appliance_recommendation`); optionaler Loxone-Merker in `loxone_inputs.power_name` (noch keine Live-Abfrage).
2. **Empfehlungshorizont:** je Gerät aus Hausprofil (`schedule.start_shift_h` bei `earnie_role: manual`).
3. Über den **Empfehlungshorizont** wird für jeden möglichen Startslot die Stromkosten des Laufs berechnet → **günstigste Startzeit** + **Startgüte** (Kosten in €, plus Ersparnis vs. „sofort starten").
4. Rein **beratend** — kein Loxone-Schaltsignal.

### 5.3 Konfiguration (Z. 17, Roh-JSON-Editor)

- `st.text_area` mit dem Inhalt von `config.json`.
- **Validieren:** `json.loads` + Schema-Check gegen `config/config.schema.json`.
- **Speichern:** atomar schreiben, danach `config.reinit_config()`.
- Bei Fehler klare Meldung statt stiller Übernahme (keine verschleiernden Defaults).
- Optional als Komfort-Ansicht darüber: bestehendes PV/Batterie-Formular aus `ui/config_forms.py`.

### 5.4 Backtesting (Z. 18)

Unverändert; die bisherigen Sidebar-Controls (`render_backtesting_sidebar`) wandern in den Seiten-Body. „Szenarieneditor" als deaktivierter Mockup-Block auf derselben Seite.

### 5.5 Mockup-Seiten (`*`)

Funktionslose Platzhalter mit `st.info("geplant")` und deaktivierten Widgets im geplanten Layout: Szenarieneditor, Hauskonfigurator, Verbraucheranalyse inkl. Adaptionsalgo.

### 5.6 Preis-Prognose (Dev, bestehend)

Umzug in eine eigene Seite; bleibt per `ui.price_forecast_page_enabled` / `ENERGY_OPTIMIZER_UI_MODES` gegated.

## 6. Empfehlungsmodus — Algorithmus

Für ein Gerät mit Leistung `P` (kW) und Laufzeit `d` (in 15-min-Slots):

1. Nächste *h* (Empfehlungshorizont je Gerät) aus der **persistierten Planungsmatrix** im letzten `live_optimization_debug.json` (geschrieben von `main.py`; kein Live-Matrix-Build in der UI).
2. Für jeden möglichen Startslot `s` die Laufkosten über die `d` Slots ab `s` summieren:
   `Kosten(s) = Σ P × slot_dauer_h × Netzpreis`, wobei PV-gedeckter Anteil den Netzbezug (und damit die Kosten) reduziert.
3. **Günstigste Startzeit** = Slot mit minimalen Kosten.
4. **Startgüte** = diese Kosten (€), ergänzt um die Ersparnis gegenüber „sofort starten".

Kernlogik als reine, testbare Funktion in `optimizer/appliance_recommendation.py` (ohne Streamlit-Abhängigkeit).

## 7. Config-Erweiterungen

Neue Felder in `config/config.schema.json` und `config/config.example.json`:

- Loxone-Merkernamen: `Leistung Waschmaschine`, `Leistung Trockner`.
- Geräte-Block (`appliances` o. ä.) mit den drei manuellen Geräten (Anzeigename, Leistungsquelle: Loxone-Merker vs. manuell).

Konkretes Schema wird in Schritt 3 festgelegt.

## 8. Datei-Plan

| Datei | Art | Inhalt |
|-------|-----|--------|
| `app.py` | Umbau | Router mit `st.navigation`; Seiten je nach Gating registrieren |
| `ui/pages/page_cockpit.py` | neu | wrappt bestehenden S-2-Block |
| `ui/pages/page_devices.py` | neu | Manuelle Geräte + Empfehlungsmodus |
| `optimizer/appliance_recommendation.py` | neu | reine Startzeit-/Kosten-Logik (testbar) |
| `ui/pages/page_config.py` | neu | Roh-JSON-Editor + Validierung/Schema-Check |
| `ui/pages/page_backtesting.py` | neu | wrappt `ui/backtesting.py`, Controls im Body |
| `ui/pages/page_price_forecast.py` | neu | wrappt `ui/price_forecast.py` |
| `ui/pages/page_scenario_editor.py` | neu | Mockup* |
| `ui/pages/page_house_config.py` | neu | Mockup* |
| `ui/pages/page_consumer_analysis.py` | neu | Mockup* |
| `ui/backtesting.py`, `ui/price_forecast.py` | anpassen | Sidebar-Controls → Body |
| `config/config.schema.json`, `config/config.example.json` | ergänzen | neue Merker-Felder + Geräte-Block |
| `tests/…` | neu | Unit-Tests für `appliance_recommendation` + Seiten-Registry |
| `backlog/Backlog.md`, `version.py` | Abschluss | Punkte nach Erledigt, Bump auf `1.21.0` |

Struktur-Regeln beachten: je Datei ≤ 400 LOC (UI), Funktionen ≤ 40 LOC, pro Schritt 1–3 Dateien.

## 9. Umsetzungsreihenfolge (Schritte)

Jeder Schritt bleibt für sich lauffähig.

1. **Schritt 1 — Navigations-Gerüst:** `app.py` → Router, `ui/pages/`, bestehende Modi (Cockpit, Backtesting, Preis-Prognose Dev) 1:1 als Seiten; Env-Gating bleibt. Sidebar-Ersatz steht.
2. **Schritt 2 — Konfiguration:** Roh-JSON-Editor (`page_config.py`).
3. **Schritt 3 — Empfehlungsmodus:** erst `optimizer/appliance_recommendation.py` + Tests, dann `page_devices.py` + Config-Erweiterungen.
4. **Schritt 4 — Mockup-Seiten:** Szenarieneditor*, Hauskonfigurator*, Verbraucheranalyse*.
5. **Schritt 5 — Abschluss:** Backlog-Sync + Version-Bump `1.21.0`.

## 10. Versionierung

`### Version 1.21` ist ein Feature-Block → beim Abschluss **MINOR-Bump auf `1.21.0`** (aktuell `1.20.0`), PATCH = 0. Da „full_now" auch Z. 21 einschließt, werden **beide** Backlog-Punkte (Menüstruktur + Empfehlungsmodus) gemeinsam nach `Backlog-Erledigt.md` verschoben.

## 11. Später (`*`, nicht Teil dieser Umsetzung)

- Szenarieneditor (Backtesting), Hauskonfigurator, Verbraucheranalyse inkl. Adaptionsalgo — hier nur Mockups.
- Empfehlungsmodus für smarte Geräte; adaptiv bzgl. Laufzeit/Energieverbrauch pro Lauf; Geschirrspüler-Leistung ggf. über Hue.

## Änderungshistorie

| Datum | Version | Inhalt |
|-------|---------|--------|
| 2026-07-07 | 0.1.0 | Erstfassung: Design abgestimmt (Navigation, Seiten, Empfehlungsmodus, Schritte) |
