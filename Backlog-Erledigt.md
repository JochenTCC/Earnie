# Erledigte Punkte

Archiv abgeschlossener Arbeiten. Offene Todos → [Backlog.md](Backlog.md) · Bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

### Version 1.25.0 — Backtesting mit Hauskonfiguration (2026-07-10)

- [x] **Hauskonfigurator** — optionales Jahres-Gesamt-Verbrauchs-CSV (Format-Check: Monatsbalken + Stundenverlauf)
- [x] **Szenarieneditor** — Subpage unter Konfiguration; Hauskonfigurator nur Verbraucher + PV; Batterie/Tarife im Szenario-Editor; Default-Scenario Runtime (Pflicht vor Backtesting/Betrieb); weitere Szenarien mit anderen Batterien/Tarifen
- [x] **Backtesting aus Konfiguration** — Daten aus Hauskonfiguration + Szenarien; Lauf einlesen wenn Fingerprint passt, sonst Neu-Berechnen
- [x] **Verbrauchsdaten (`cons_data_hourly.csv`)** — Visualisierung, synthetische Generierung (`scripts.generate_cons_data`), Match-Status Verbraucher-IDs, Backtesting-Start ohne gültige Datei deaktiviert
- [x] **cons_data-Plot** — Navigation wie Jahres-CSV; Spaltenverläufe `total_kw` / `baseload_kw` / `pv_kw`
- [x] **Backtesting-Runner** — Testlauf (ein Monat), Fortschrittsbalken (`--progress-file`), gruppierte Szenario-Balken im Monatskostenvergleich
- [x] **Sidecar-Pfade** — `tariffs.json` / `house_profiles.json` / `backtesting_scenarios.json` neben per-ENV gesetzter `config.json` (`persist_paths`)
- [x] **Fingerprint** — Tarif-Specs und aWATTar-Pricing-Block im Szenario-Fingerprint; Export-Tarif-Alias `awattar_sunny_float` → `dynamic_epex`
- [x] **Tests** — `test_backtesting_cons_data`, `test_backtesting_charts`, `test_backtesting_plausibility_charts`, `test_backtesting_ui_helpers`, `test_persist_paths_sidecars`

**Manuelle Abnahme (Greenfield, Streamlit :8511 oder Container :8502)**

- [x] Greenfield zurückgesetzt; nur Hauskonfigurator + Konfiguration sichtbar; Sidebar zeigt fehlende Schritte
- [x] **Hauskonfigurator** — thermisches Hausprofil + PV-Anlage speichern; optional Jahres-CSV hochladen → Monatsbalken und Stundenverlauf (Ist vs. Modell)
- [x] **Szenarieneditor** erscheint nach Hausprofil + PV — Batterie anlegen, Runtime speichern (Batterie, Tarife, Hausprofil, Geo)
- [x] **Backtesting** erscheint nach vollständigem Runtime-Szenario — konfigurierte Szenarien werden angezeigt
- [x] **Verbrauchsdaten (`cons_data_hourly.csv`)** — ohne gültige Datei: Abschnitt mit Hinweis, Button **Backtesting starten** deaktiviert
- [x] Button **Verbrauchsdaten generieren (synthetisch)** — `runtime/cons_data_hourly.csv` + `.meta.json` mit Datenzeilen
- [x] Monatsbalken und KW-Stundenverlauf (Ist vs. Modell) im Verbrauchsdaten-Abschnitt
- [x] Match-Status Verbraucher-IDs — passt zur aktuellen Config (grün) bzw. Warnung bei Abweichung oder fehlender Meta-Datei
- [x] Button **Backtesting starten** — Lauf endet erfolgreich; Kosten, Monate, Plausibilität und Stundenchart sichtbar
- [x] Nach Änderung an Runtime/Szenario — Warnung „Lauf passt nicht zur Konfiguration“ + **Neu berechnen**
- [x] PR #4 mergen

### Bugfix natives Filterfenster Log-Spam (main.py) (2026-07-09)

- [x] **`filter_contexts` einmal pro Lauf** — `main.py` löst vor `get_consumer_remaining_kwh` auf und reicht durch an MILP, Restziel-Anpassung und `calculate_optimization_savings`
- [x] **Horizont-Simulation** — `simulate_horizon` / `_simulate_single_hour_optimizer` / `calculate_optimization_savings` akzeptieren vorgefertigte `filter_contexts`; kein erneutes Loxone-Lesen pro MILP-Stunde
- [x] **Logging** — INFO „natives Filterfenster Start=…“ nur noch bei `resolve_filter_context`, nicht bei jedem indirekten Aufruf
- [x] **CBC-Log-Spam** — `record_cbc_event` loggt bei aktiver Sammlung (`begin_cbc_event_collection`) nicht mehr pro Slot; `simulate_horizon` fasst am Ende als eine INFO-Zeile zusammen (`summarize_cbc_events`); Live-MILP in `main.py` unverändert auf INFO
- [x] **Tests** — `TestFilterContextCaching` in `tests/test_filter_context.py`; CBC-Suppression/Summary in `tests/test_cbc_events.py`

### Bugfix UI-Bugs 1.23.1 (2026-07-09)

- [x] **Ranking-Tabelle mobil kompakt** — 3 Spalten (Checkbox vor Uhrzeit, Güte, Delta); Kostenspalte entfernt (`ui/pages/page_devices.py`)
- [x] **Legende Cockpit Chart 1/2** — Variante A (unified collapsible): `showlegend=False`, `margin.b` ≈ 55, HTML-`<details>` auf allen Viewports (`ui/chart_legend_mobile.py`, `ui/charts.py`)
- [x] **Nennleistung/Laufzeit bei aktivem Plan** — Eingabefelder und Speichern-Button deaktiviert mit Hinweistext
- [x] **SOC-BL-Ziel Brücke an Zonengrenzen** — `bridge_left=(index > 0)` in `add_baseline_soc_traces`
- [x] **Preiskurve durchgängig** — Einzel-Trace statt segmentierter HV-Linien (`add_price_on_soc_axis_trace`)
- [x] **Manuelle Verbraucher Schraffur** — stabile Muster pro `appliance_id` (`manual_appliance_pattern_shape` in `ui/chart_colors.py`)

### Bugfix Mobile Legende Cockpit (Chart 1/2) (2026-07-09)

- [x] **Mobile Legende Cockpit (Chart 1/2)** — Plotly-Legende unter 768px per CSS aus; farbiges `<details>` als Ersatz (nur mobil sichtbar). Desktop: nur Plotly-Legende, kein Expander (`ui/chart_legend_mobile.py`). Prod-Abnahme bestätigt.

### Bugfix Sankey SwimSpa/Filter Fall B (Gesamtzähler) (2026-07-09)

- [x] **Sankey + Chart 1 SwimSpa/Filter (Gesamtzähler Fall B)** — Fix **v1.24.1**: Sankey/Live-UI laden Flex-Leistung bei veraltetem `optimizer_run_state` (>120 s) mit `filter_contexts` + `slot_datetime` (`fetch_live_flex_kw_for_ui` in `data/live_consumption.py`); Filter-Inferenz wie in `main.py`. Prod-Abnahme: natives Fenster 10–14 — zwei Sankey-Ströme (SwimSpa + SwimSpa Filter), Filterleistung korrekt zugeordnet, keine irreführende Soll-Ist-Mismatch-Farbe bei Soll 0. Referenz-Dumps: `chart_debug_20260708_114712`, `chart_debug_20260709_120500`.

### Version 1.24.g — monthly_float Einspeisetarif (OeMAG-Referenzkurve) (2026-07-09)

- [x] **Schema** — Export-Typ `monthly_float` in `tariffs.schema.json`; `oemag_monthly_feed_in_rates` + `monthly_float_reference_cent_kwh` in `backtesting_scenarios.schema.json`
- [x] **Pricing-Pipeline** — `data/monthly_float_rates.py` (OeMAG-Skalierung); `tariff_pricing.export_cent_kwh`; `get_backtesting_feed_in_settings()` baut skalierte Monatstabelle zur Laufzeit
- [x] **Katalog & Konverter** — `tools/convert_dach_tariffs.py` aus `einspeisetarife_dach_erweitert.json`; 5 `monthly_float`-Export-Tarife in `config/tariffs.json`
- [x] **OeMAG-Referenzdaten** — 12 Monate Jul 2025–Jun 2026 in `backtesting_scenarios.example.json`; `fixed_monthly_feed_in_rates` (aWATTar-SUNNY) unverändert
- [x] **Tests & Doku** — `tests/test_monthly_float_rates.py`; Erweiterung `test_tariff_pricing` / `test_house_config`; `docs/konfiguration/preise.md`

### Version 1.24.f — DACH-Tarifkatalog & Preismodell (Backtesting) (2026-07-09)

- [x] **P1 — Schema & Preisfunktionen** — `tariffs.schema.json` (DACH-Typen + `catalog_as_of`); `house_config/tariffs_store.py` (`_import_tariff_spec`, `_export_tariff_spec`, Szenario-Specs); `data/tariff_pricing.py` (`import_cent_kwh` / `export_cent_kwh`, Legacy `awattar`/`dynamic_epex`)
- [x] **P2 — Backtesting-Pipeline & Marktzonen** — `data/data_loader.py` (AT / `DE-LU` / CH); tariff-aware Pricing in `simulation/engine.py`, `data/backtesting_prices.py`, `data/feed_in_prices.py`
- [x] **P3 — DACH-Konverter & Katalog** — `tools/convert_dach_tariffs.py`; `config/tariffs.json` mit 44 Tarifen (`catalog_as_of=2026`)
- [x] **P4 — UI Planung** — `ui/planning_tariff_form.py`, `ui/pages/page_scenario_editor.py` (Typ-Labels, Land/Währung/Notes, `catalog_as_of`, DE-Netzentgelt-Override)
- [x] **P5 — Tests & Doku** — `tests/test_tariff_pricing.py`, Erweiterung `tests/test_house_config.py`; `docs/konfiguration/preise.md`

### Version 1.24.e — Planungs-Editoren & Hauskonfigurator-UX (2026-07-09)

- [x] **P1 — Config-Drift** — `should_show_config_drift()` unterdrückt Hinweis während `needs_planning_onboarding()`; leere `flexible_consumers` werden in der Drift-Prüfung ignoriert
- [x] **P2 — Hauskonfigurator UX** — Auto-IDs (`house_config/id_slug.py`); Typ-Label „Haus Wärme“; Gebäudeklassen mit HWB; optionales `hwb_kwh_m2`
- [x] **P3 — Planungs-Konfiguration** — Tabs PV/Batterie/Tarife im Hauskonfigurator; Bootstrap `tariffs.json` aus `tariffs.example.json`; Tarifwahl → `runtime_settings.import/export_tariff_id` (kein Tarif-Editor)
- [x] **P4 — Tests & Doku** — `tests/test_planning_editors.py`; Anpassungen Setup/Navigation/Drift; [`greenfield-dev-stack.md`](docs/einrichtung/greenfield-dev-stack.md)

### Version 1.24.d — Greenfield-Onboarding (minimale Config + UI-Freischaltung) (2026-07-09)

- [x] **P1 — Minimal-Bootstrap** — `config.minimal.json` + leere Vorlagen für `house_profiles`, `tariffs`, `backtesting_scenarios`; Bootstrap nutzt Minimal- statt Example-Dateien; `config.example.json` bleibt Referenz
- [x] **P2 — Laufzeit-UI-Gating** — `ui/setup_readiness.py`, `ui/setup_progress.py`, `ui/navigation.py`: nach Loxone-Setup nur Hauskonfigurator + Konfiguration bis Planung vollständig
- [x] **P3 — Backtesting-Freischaltung** — Freischaltung bei thermischem Hausprofil + PV + Batterie + Import-/Export-Tarif; Szenarieneditor vorerst gesperrt (Follow-up)
- [x] **Tests + Doku** — `tests/test_setup_readiness.py`, `tests/test_navigation_setup.py`; [`greenfield-dev-stack.md`](docs/einrichtung/greenfield-dev-stack.md)

### Version 1.24.c — Greenfield Dev-Stack (2026-07-09)

- [x] **P1 — Greenfield-Compose** — `docker-compose-greenfield.yml` mit `greenfield/config` + `greenfield/runtime`, Container `ernie-greenfield-*`, UI-Port **8502**, Loxone-Verify aus
- [x] **P2 — Abnahme-Hilfen** — Checkliste in [`docs/einrichtung/greenfield-dev-stack.md`](docs/einrichtung/greenfield-dev-stack.md); Smoke-Test `tests/test_greenfield_bootstrap.py` (ohne Fixture-Snapshot `tests/fixtures/greenfield/`)
- [x] **Follow-up beim Durchspielen** — `Dockerfile`: `share/config/` um Tarife-, Hausprofile- und Backtesting-Szenario-Vorlagen ergänzt (Bootstrap auf leerem Volume)

### Version 1.24.0 — Hauskonfigurator UX & E-Auto-Profil (2026-07-09)

- [x] **P1 — Datenmodell `ev`** — Typ `ev` in `house_profiles.schema.json` und `house_config/profiles_store.py`; Planungs-Subset aus Live-`eauto` ohne `loxone`; `house_profiles.example.json` mit E-Auto als `ev`
- [x] **P2 — UI Neu/Entfernen** — `ui/house_config_profile_form.py` (Tab in `page_house_config.py`): `st.session_state`-Verbraucherliste, „Verbraucher hinzufügen“ / „Entfernen“, Typ-Dropdown inkl. „E-Auto“ mit bedingten Feldern
- [x] **P3 — Jahres- und Stundenprofil** — `house_config/ev_profile.py` (`estimate_ev_annual_kwh`, `ev_hourly_kw_for_day`); `baseload.py` und `data/consumption_profiles.py` mit fensterbasiertem `ev`-Zweig
- [x] **P4 — Tests** — `tests/test_house_config.py`: Normalisierung, Jahres-kWh, Stundenprofil nur im Ladezeitfenster, `build_hourly_kw_profile`
- [x] **P5 — Tariflisten-Stand in der UI** — mit **1.24.f** umgesetzt (`catalog_as_of` in `planning_tariff_form.py` und `page_scenario_editor.py`)

### Version 1.24.b — LOC-Refactoring Top-3 (2026-07-09)

- [x] **Epic 1 — `optimizer/milp.py`** (~991 → ~170) — `milp_consumers.py`, `milp_horizon.py`, `milp_result.py`; `_derive_control_from_milp` → `optimizer/battery.py`; Re-Exports für Tests
- [x] **Epic 2 — `config.py`** (~1543 → ~720) — Paket `settings/` (`json_io`, `flexible_consumers`, `appliances`, `scenarios`, `system_settings`); `config.py` als Orchestrator-Fassade
- [x] **Epic 3 — `ui/charts.py`** (~2822 → ~400) — `chart_slot_axis`, `chart_trace_segments`, `chart_soc`, `chart_cumulative`, `chart_decorations`, `chart_consumer_stack`; dünne Fassade + Re-Exports

### Version 1.24.a — Hauskonfigurator und Szenarien (2026-07-09)

- [x] **P1 — Batterie & PV als Entitäten** — `batteries[]` / `pv_systems[]` in `config.json`; Szenario wählt je eine ID; Abwärtskompatibel zu flachen `runtime_settings`
- [x] **P2 — Stromtarife** — `config/tariffs.json` mit Import-/Export-Tarifen; Szenario-Referenzen `import_tariff_id` / `export_tariff_id`
- [x] **P3 — Verbraucher & Grundlast** — `config/house_profiles.json`; generisch, thermisch, Grundlast mit 5-%-Untergrenze
- [x] **P4 — Zusammengesetztes Szenario** — `backtesting_scenarios.json`; Auflösung in `config.py` für `simulation/engine.py`
- [x] **P5 — UI** — Hauskonfigurator (`page_house_config.py`) und Szenarieneditor (`page_scenario_editor.py`)

### Bugfix Chart 1 PV-Linie = Ist (forecast_pv nach Overlay) (2026-07-08)

- [x] **`forecast_pv_kw` vor Live-Overlay loggen** — `main.py` speichert Forecast.Solar-Wert, nicht `consumption_snapshot.pv_kw`; Chart-Linie vs. Ist-Balken unterscheidbar
- [x] **NaN-`PV-Ist` in MILP-Zeilen** — Flow-Balance fällt auf Prognose zurück (`chart_flow_balance.py`)

### UI S-2 — Chart 1 PV-Linie durchgängig (2026-07-08)

- [x] **PV-Prognose-Linie durchgängig** — eine gelbe Linie (`CHART_PV_LINE_COLOR`) über grau/neutral/grün; Overlay „PV-Prognose (Log)“ entfernt
- [x] **Datenmodell** — `PV-Prognose (kW)` = Prognose; `PV-Ist (kW)` nur für Flow-Balance-Balken im Log
- [x] Tests + `docs/ui/charts.md`

### Manuelle Geräte — Chart 1 Cockpit (Follow-up Phase 5) (2026-07-08)

- [x] **Eigene benannte Spuren im Chart-1-Flex-Stack** — geplante Geräte aus `appliance_schedules.json` als Flex-Balken (Waschmaschine, Trockner, …), nicht nur in `expected_p_act`/`Grundlast`; `apply_appliance_schedules_to_chart_rows` + `_finalize_chart_rows_for_display`
- [x] **Gemeinsame Farbe, gerätespezifischer Hover** — `COLOR_MANUAL_APPLIANCE` / `flex_bar_chart_color`; Stack-Reihenfolge in `ordered_active_consumers_for_stack`
- [x] **Live-Cache bei Plan-Checkbox** — `invalidate_live_optimization_cache()` auf „Manuelle Geräte“ nach Speichern/Löschen des Plans

### Version 1.23 — Manuelle Geräte, Verbraucheranalyse & Charts (2026-07-08)

- [x] **Appliance-Parameter in config.json** — `update_appliance_defaults()`, Save-Form auf „Manuelle Geräte“
- [x] **Sterne-Schwellen** — kombinierte k_act-/Prozent-Regel; Config-Block `appliance_recommendation` + UI-Expander
- [x] **PV Ist + Prognose im grauen Bereich** — Spalte `PV-Prognose-Log (kW)`, gedämpfte Chart-Spur
- [x] **Mobile Legende** — CSS + Expander unter Chart 1/2 (`ui/chart_legend_mobile.py`)
- [x] **Planung manuelle Geräte → Optimierung** — `appliance_schedules.json`, Matrix-Injektion auf `expected_p_act`, Checkbox in Empfehlungstabelle (sofortige Übernahme); SMB-Fallback beim Schreiben
- [x] **Verbraucheranalyse Swimspa** — Temperatur Ist/Soll + Filter autonom/Ernie (`page_consumer_analysis.py`)
- [x] **Version 1.23.0** — Minor-Bump

### Bugfix Chart 1 SoC laufende Stunde vor Jetzt + BL-Ziel (2026-07-08)

- [x] **Chart 1: SoC vor Jetzt ohne MILP-Konstante** — Rampe erster MILP-Viertelstunde → Jetzt aus Log-Hochrechnung (`_current_hour_soc_ramp_before_now`, `_soc_from_history_extrapolation`); Test `test_soc_intra_hour_ramp_before_now_replaces_flat_milp_head`
- [x] **Chart 1: SoC BL Ziel nicht im grauen Bereich** — BL-Ziel-Spur nur ab Log-Grenze, ohne Brücke ins Graue; Test `test_baseline_soc_trace_starts_at_history_boundary_not_in_gray`
- [x] **Chart 1: BL-Ziel und SoC treffen sich an Jetzt** — gemeinsamer Anker `soc_at_now` aus Log-Daten; Test `test_baseline_soc_meets_optimized_soc_at_now`
- [x] **Live-Abnahme bestätigt**
- [x] **Version 1.22.5** — Patch-Bump

### Bugfix Ersparnis Manuelle Geräte (2026-07-08)

- [x] **Delta zu bestem Zeitpunkt statt Ersparnis** — Spalte/Caption „Delta zu bestem Zeitpunkt (€)“ (`Kosten − günstigste`); Vorzeichen `+`/`-`; rot bei positiv, grün bei negativ (`ui/pages/page_devices.py`, `tests/test_page_devices_display.py`)
- [x] **Nennleistung immer editierbar** — `number_input` für alle `power_source`; `default_power_kw` aus Config nur als Vorbelegung/Hinweis-Caption
- [x] **Version 1.22.2** — Patch-Bump

### Bugfix charging_context timezone-aware Live (2026-07-08)

- [x] **Streamlit TypeError naive/aware datetime** — `_align_like` in `optimizer/charging_context.py`; Config-Fenster (`car_available_from_hour`, Loxone-FertigUm) an timezone-aware Matrix-Slots angeglichen; Tests timezone-aware Horizont
- [x] **Version 1.22.1** — Patch-Bump

### Loxberry-Container Multi-Arch (2026-07-08)

- [x] **7f — Loxberry-Container** — Multi-Arch-Build (`--target all`) via buildx; `docker-compose-loxberry.yml`; Go/No-Go in README und `container.md`; Dockerfile plattformneutral
- [x] **Version 1.22.0** — Minor-Bump

### Bugfix Chart 1 SoC laufende Stunde (2026-07-08)

- [x] **Chart 1: SoC nach Jetzt bis Stundenende extrapolieren** — keine horizontale Treppe im neutralen MILP-Bereich der laufenden Stunde; Rampe Jetzt → `_soc_tail_y_from_row` (`ui/charts.py`, `chart_now` durchgereicht); Live-Abnahme bestätigt; Test `test_soc_intra_hour_ramp_replaces_flat_milp_tail`
- [x] **Version 1.21.5** — Patch-Bump

### Bugfix Versionsanzeige Sidebar (2026-07-08)

- [x] **Versionsanzeige ganz oben in der Sidebar** statt im Cockpit-Titel — `app.py` (`_render_sidebar_version`), `version`-Parameter aus `render_page_title_with_help` entfernt
- [x] **Version 1.21.1** — Patch-Bump

### Bugfix Chart 2 grau/neutral-Brücke (2026-07-08)

- [x] **Chart 2: Kosten und Verbrauch an grau|neutral-Grenze verbunden** — Prognose-Kurven kumulieren ab Ist-Summe (`_bridged_forecast_cumulative_series` in `ui/charts.py`); Kennzahlen BL Ziel / Optimiert / Ersparnis unverändert Horizont SA₀→SA₂; Tests `test_bridged_forecast_cumulative_continues_from_history`, `test_chart2_prognose_bridges_at_history_boundary`
- [x] **Version 1.21.4** — Patch-Bump

### UI-Menüstruktur & Empfehlungsmodus manuelle Geräte (2026-07-07)

Spec: [docs/spec/ui-menu-structure.md](docs/spec/ui-menu-structure.md). `### Version 1.21`-Feature-Block gemeinsam abgeschlossen.

- [x] **Menüstruktur als Sidebar-Ersatz** (`st.navigation` + `st.Page`) — `app.py` als Router, `ui/pages/`; bestehende Modi (Cockpit, Backtesting, Preis-Prognose Dev) als Seiten (Env-Gating erhalten); Roh-JSON-Config-Editor (`page_config.py`); Mockup-Seiten (Szenarieneditor, Hauskonfigurator, Verbraucheranalyse); Backtesting-/Preis-Prognose-Controls in den Seiten-Body verschoben
- [x] **Empfehlungsmodus manuelle Geräte** — `optimizer/appliance_recommendation.py` (reine Startzeit-/Kostenlogik: Ranking der Startstunden im 6-h-Horizont nach Netzbezugskosten, 1–5 Sterne linear, Ersparnis vs. sofort) + Tests
- [x] **`ui/pages/page_devices.py`** — pro Gerät (Waschmaschine, Trockner, Geschirrspüler) Nennleistung + Laufzeit → Startzeit-Empfehlung; rein beratend, kein Loxone-Schaltsignal
- [x] **Config `appliances`-Block** — `config.get_appliances()` + Normalisierung, Schema + `config.example.json`; `default_power_kw` als Nennleistung für die Kostenbewertung (bei `power_source=loxone` Pflicht), `loxone_power_name` reserviert für späteren Adaptionsalgo
- [x] **Version 1.21.0** — Minor-Bump

### Swimspa Filternutzung optimieren (2026-07-07)

Spec: [docs/spec/swimspa-filter.md](docs/spec/swimspa-filter.md). Ziel: kostenoptimale **ergänzende** Filterlaufzeit; `Sollstunden` (Schulden in h) langfristig → 0; nativer Duty-Cycle unabhängig.

- [x] **Code Phasen 1–4** — `loxone_remaining_hours`, `filter_context`/MILP-Sperrung, Schema/`config.example.json`/Doku, Live-Parser + `verify_swimspa_filter_live` / `patch_swimspa_filter_config`
- [x] **Live-Abnahme (Nutzer)** — Prod-`config.json` gepatcht; Formate `filter1hour` und `Sollstunden` am Miniserver bestätigt
- [x] **Deviation-Regeln SwimSpa-Filter (S8–S10)** — `swimspa_filter_should_run_missing`, `swimspa_filter_runs_unexpectedly` (nur außerhalb nativem Fenster), `swimspa_filter_over_nominal`; neue Prädikate `power_ist_without_soll`, `slot_outside_native_filter_window`, `ist_power_above_nominal`; natives Fenster als `filter_contexts` in `optimization_history.jsonl` mitgeloggt
- [x] **Ist-Leistung Heizen/Filtern getrennt geprüft + Fall B korrigiert** — getrennte Loxone-Merker/Keys/Charts bestätigt; Heizungszähler `Ernie_Swim-Spa-P_act` misst inkl. Filter → `subtract_consumer_ids` zieht Filter-Anteil vom Heizungs-Ist ab (kein Doppelzählen in `flex_sum_kw`/`baseload_kw`); `patch_swimspa_filter_config` idempotent erweitert. Follow-up (historische Logs / Loxone-Trennung) als eigener 1.+1-Punkt
- [x] **Version 1.20.0** — Minor-Bump

### Chart 1 Prognose-Sättigung PV & Grundlast (2026-07-07)

- [x] **Chart 1: Prognose-Sättigung auch für PV und Grundlast reduziert** — Zonenlogik aus den Flex-Verbrauchern auf `PV` und `Grundlast` erweitert; Historie bleibt voll gesättigt, neutraler und grüner Bereich nutzen denselben Sättigungsfaktor wie Flex; Regressionstests für Farbableitung und zonenspezifische Buckets ergänzt
- [x] **Version 1.19.0** — Minor-Bump

### Debug-Dump Vorarbeit (2026-07-07)

- [x] **Reproduzierbare Repro-Inputs für Debug-Dumps zentralisiert** — gemeinsame Sammlung in `runtime_store/debug_dump_inputs.py`; `chart_debug_capture` und `archive_prod_dump` sichern jetzt aktive `config.json`, `deviation_rules.json`, optionale `local_settings.json`, relevante Env-Overrides und aufgelöste Pfade
- [x] **Explizit konfigurierte Zusatzdateien in Dumps aufgenommen** — Preisprognose-Modell (`forecast_model_path`) und `cons_data_hourly.csv` werden bei vorhandener aktiver Referenz mitarchiviert; fokussierte Tests für ZIP- und Prod-Dump-Archiv ergänzt

### Verbraucher-Farben P1 — NAS-Deploy Cleanup (2026-07-07)

- [x] **Temporären lokalen `chart_color_index`-Test zurückgenommen** — lokale `config/config.json` entfernt; NAS-Pfad `ENERGY_OPTIMIZER_CONFIG_PATH=\\DS-KO-DO-2\docker\energy_optimizer\config\config.json` wieder maßgeblich, lokaler Override nicht mehr aktiv

### Verbraucher-Farben P2 — Zonenabhängige Sättigung (2026-07-07)

- [x] **P2 — Zonenabhängige Sättigung (nur Chart-1-Flex-Balken)** — History volle Palette; neutral + Forecast gemeinsam `CONSUMER_CHART_SATURATION_MUTED` (0,6); Slot → Zone via `chart_zone_kind_for_slot_start`; Flex-Farbe pro Slot/Bucket; Legende Vollfarbe (`legendonly`); Sankey unverändert; Tests und `docs/ui/charts.md`
- [x] **Version 1.18.0** — Minor-Bump

### Verbraucher-Farben P1 — 8er-Palette & chart_color_index (2026-07-07)

- [x] **P1 — Feste 8er-Palette & `chart_color_index`** — `CONSUMER_PALETTE` (H 260→40, S=90, L=50); `color_from_hsl()` mit optionalem Alpha; Grundfarben als `_HSL_*` + `_ALPHA_*`; `consumer_chart_color()` zentral für Chart 1 (`chart_flow_balance`) und Sankey; `chart_color` entfernt, Schema/`config.example.json` mit Indizes SwimSpa=0, E-Auto=2, Wärmepumpe=7; Tests und `docs/ui/charts.md`

### Chart-Farben zentralisieren (2026-07-07)

- [x] **Phase 1–4 `ui/chart_colors.py`** — Single Source für Zonen, Energiebilanz-Balken, Chart-1-Linien/Overlays, Chart-2-Kosten, Sankey, Flex-Palette, Legacy-Steuerbefehl-Balken; `chart_flow_balance`, `charts`, `sankey`, `sankey_produktiv`, `planning_window` nur noch Konsumenten
- [x] **Version 1.17.3** — Patch-Bump

### Bugfix Chart 1 Zonen & Balken-X (2026-07-07)

- [x] **Balken in grüner Zone SA₀→SA₁ unsichtbar** — `ChartSlotAxis.at()` ignorierte `slice(start, end)`; Extrapolations-Balken landeten am Chart-Anfang statt in der grünen Zone (`ui/charts.py`); Regressionstests
- [x] **Zonenfarben grau/grün zentral & kontrastreicher** — `ui/chart_colors.py` mit `hsl`, `blend_hsl`, `rgba_from_hsl`, `CHART_ZONE_HISTORY_FILL`, `CHART_ZONE_FORECAST_FILL`; Forecast bewusst Gelb-Grün (H≠120) statt Material-Grün; Anbindung `data/planning_window.py`
- [x] **Version 1.17.2** — Patch-Bump (zwei Bugfixes)

### Chart 1 Rauf/Runter-Energiebilanz (2026-07-06)

- [x] **Entladesperre besser visualisieren** — gelb-schwarzes Streifenband unter SoC (`ui/charts.py`)
- [x] **Rauf/Runter-Balken** statt Batterie-/Verbraucher-Balken — Basis `ui/chart_flow_balance.py`, `ui/flow_balance_allocate.py`
- [x] **Farbpalette Netz & Batterie** — Netz blau, Batterie-Flüsse gedämpft (HSL in `ui/chart_colors.py`); Szenarien A–I, `docs/ui/charts.md`
- [x] **PV-Überschuss & volle Batterie** — SoC-Rand-Korrektur (MILP); Szenario I; Produktiv-Log: Ist-`battery_kw` aus `consumption_snapshot` → `Ist Batterie-Leistung (kW)` (`runtime_store/history_timeline.py`)
- [x] **Netz- und Grundlast-Linien entfernt** — Darstellung nur noch über Rauf/Runter-Balken (`ui/charts.py`)
- [x] **SoC-Verlauf** — gemeinsame Farbe optimiert + „SoC BL Ziel“ über `_HSL_SOC` in `ui/chart_colors.py`
- [x] **Version 1.17.0** — Minor-Bump nach abgeschlossenem Version-0.+1-Block Chart 1

### UI S-2 Cold-Start & Preisprognose-Logging (2026-07-06)

- [x] **Initiales Rendering UI (SA-2-SA)** — Cold-Start ~112 s → ~7 s: Archive-EU-Feature-Abruf für Zukunfts-Slots übersprungen (`_archive_covers_slot_range` in `data/price_forecast_live.py`); JSONL-In-Memory-Cache in `runtime_store/optimization_history.py`
- [x] **Terminal-Warnung EU-Features (Open-Meteo 400)** — `print()` durch `logging` ersetzt; erwarteter Live-Fall nur `logger.debug`, API-Fehler als kompaktes `logger.warning` ohne volle URL

### Preis-Prognose (EU-Wetter & Erzeugung) Epic abgeschlossen (2026-07-06)

- [x] **Preis-Prognose (EU-Wetter & Erzeugung):** Korrelationsmodell für grüne Zone (kein Day-Ahead bis SA₂) statt Spiegelung — Wind + Solar auf EU-Ebene; Spec [price-forecast-renewables.md](docs/spec/price-forecast-renewables.md)
- [x] **Phase 0:** Scope festgelegt (AT Day-Ahead, EU-Länder, OLS, Akzeptanz)
- [x] **Phase 1:** Dataset-Pipeline `data/eu_market_features.py`, `scripts/build_price_training_dataset.py`, `data/cache/price_training_*.csv`
- [x] **Phase 2:** OLS + Walk-forward; **extended** (+ EU-Last/Residuallast) via `enrich_price_training_dataset` + `compare_price_forecast_features`; Bias-Korrektur (Nicht-Peak P90)
- [x] **Phase 3:** UI-Eval (`ui/price_forecast.py`); Live in `resolve_market_slots` (`data/price_forecast_live.py`, `data/profile_manager.py`); `config.market_prices.missing_price_strategy` (`mirror` \| `forecast`, Default **forecast**)
- [x] **Jahresvergleich 2025:** `run_price_strategy_backtests` (333 Fenster, `sunset_window`, alle Szenarien); Bericht `backtesting_logs/price_strategy_compare/comparison.md` — Prognose vs. Spiegelung marginal (±0,1–0,6 %), Go-Live mit `forecast`
- [x] **Rollierende Bias-Rekalibrierung** — zurückgestellt; statische P90-Bias-Korrektur beim Training bleibt für Live aktiv

### Preis-Prognose Backtesting Jahresvergleich (2026-07-06)

- [x] **Backtesting Jahresvergleich (Infrastruktur):** Grüne Zone im `sunset_window` — Day-Ahead-Cutoff, Spiegelung vs. OLS (`data/backtesting_prices.py`, `resolve_market_slots` forecast); `--price-strategy` / `--output-dir` in `run_backtesting`; Orchestrator `run_price_strategy_backtests` + `compare_price_strategy_backtests`; Tests

### Preis-Prognose UI per config.json (2026-07-06)

- [x] **Extra-UI-Seite für Preismodell über config.json aktivierbar** — `ui.price_forecast_page_enabled` (Standard: `false`); ohne `ENERGY_OPTIMIZER_UI_MODES` nur Sunset-2-Sunset + Backtesting, Preis-Prognose (Dev) optional per Config; Env-Variable hat weiterhin Vorrang (`ui/mode_selector.py`, `config.py`, Schema/Beispiel, Tests `tests/test_mode_selector.py`)

### Bugfixes: Test-Fixtures & Wärmepumpe (2026-07-06)

- [x] **Testdaten für frisches Checkout ausführbar** — Prod-Dump-Fixtures ergänzt (`.gitignore`-Ausnahmen, `scripts/complete_prod_dump_fixtures.py`), thermische CSV-Fixtures (`tests/fixtures/thermal/`), Smoke-Tests auf `tests/fixtures/historical/cons_data_hourly.csv`; **551 passed** (Commit `71a4764`)
- [x] **Wärmepumpe in `config.json` wiederhergestellt** — Eintrag `flexible_consumers[id=waermepumpe]` aus Produktiv-Backup (`config_back.json`, Commit `3b7fa1c`): `Ernie_WP_Freigabe`, `Ernie_WP_P_act`, historisches Tagesziel, `chart_color` `#ff9800`; auch `config.example.json`
- [x] **Soll-Ist Hinweis: Wärmepumpe nicht angesprungen** — Regel `waermepumpe_enable_no_start` (Kategorie Hinweis), Doku/Szenario S5, Seed-Skript und Tests

### Chart 1 gestapelte Flex-Verbraucher (2026-07-06)

- [x] **Chart 1: variable Flex-Verbraucher als gestapelter Negativ-Balken** — ein Balken pro Slot (gleiche X-Position wie Batterie, `barmode=overlay`, Stapelung per `base`); Sortierung nach Horizont-Energie SA₀…SA₂, Cache bis nächster SA₀; Farben via `flexible_consumers.chart_color` in `config.json`; Tests `tests/test_chart_consumer_stack.py` (`ui/charts.py`, `config.py`)
- [x] **Version 1.15.0** — Minor-Bump nach abgeschlossenem Version-0.+1-Punkt; Regel `.cursor/rules/versioning.mdc` (Minor vs. Patch)

### UI S-2 Nav & Hilfe-Icons Mobile (2026-07-06)

- [x] **Kompakte S-2-Navigation** — `←` / `Heute` / Kalender-Icon / `→` in `st.container(horizontal=True)`; Datumsauswahl im Popover (nur SA₀-Tage mit Log); `Heute` und Zyklus-Logik in `ui/s2_navigation.py`, `ui/chart_context.py`, `ui/history_navigation.py`
- [x] **Mini-Hilfe-Icons** — Material-Icon + tertiary-Popover statt `?`-Button; horizontales Layout ohne Extra-Zeile auf Mobile; CSS in `ui/styles.py` (`inject_help_hint_css`); `ui/help_hint.py`, `ui/countdown.py`

### Entladesperre: Netz-Trickelladen (2026-07-06)

- [x] **Bugfix: SOC stieg bei Halten aus dem Netz (05.07. ~22–23 Uhr)** — Prod-Log (`runtime-prod/runtime.zip`): PV=0, `battery_plan_kw=0`, gemessen ~0,2 kW Laden + Netzbezug; Ursache `target_soc_percent=100` bei Huawei-Steuerbefehl 1; Fix: bei `MODE_ENTLADESPERRE` `target_soc = current_soc` (`optimizer/milp.py`); Test `test_entladesperre_target_soc_matches_current_soc`

### Migration-Skript entfernt (2026-07-05)

- [x] **`scripts.migrate_persist_layout` gelöscht** — Einmal-Migration config/ + runtime/ nicht mehr nötig; Skript, Test, `ernie-migrate-layout`-Entrypoint und Doku-Hinweise entfernt

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
