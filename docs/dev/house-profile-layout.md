# House profile page — parameter grouping and layout

Status: **proposal** (UI only, no data-model change unless noted). Mockup: canvas "Hausprofil Neuordnung" (claude.ai artifact, private to the maintainer).

Scope: the "Hausprofil" tab of the Hauskonfigurator (`ui/house_config_profile_form.py::render_house_profile_tab` and the modules it calls).

## 1. Problem

The page grew section by section. The render order is historical, not thematic:

- related parameters live in several places (heating in three, absence in four),
- a mandatory field (Netzbereich) sits at the end of "Standort", behind optional PV defaults,
- plant-wide settings (`plant.*`) sit directly under the profile selector and look profile-specific,
- nothing can be collapsed except individual consumers and the CSV import.

## 2. Current render order

| # | Block (heading) | Fields | Code |
|---|---|---|---|
| 1 | Profile selector | Profil, Entfernen | `_render_profile_selector` |
| 2 | Einspeisebegrenzung (Anlage) | export limit on/off, kW (`plant.max_export_power_kw`) | `house_config_plant.render_plant_export_limit` |
| 3 | Netz-Zähler (Anlage / Live) | `plant.grid_meter.at_house_connection`, `single_tariff` | `render_plant_grid_meter_assertions` |
| 4 | *(no heading)* | Bezeichnung, Jahresverbrauch, Personen (+ reference line), Abwesend / Urlaub + EHAL status | `_render_profile_identity` |
| 5 | Standort | lat, lon, Land, time zone, Region, PV default tilt/azimuth, Netzbereich (+ own Arbeitspreis), draft rules | `house_config_profile_thermal._render_location_fields` |
| 6 | *(no heading, under Standort)* | Horizont berücksichtigen + bar editor | `house_config_profile_horizon.render_horizon_section` |
| 7 | Gebäude / Wärmebedarf | Heizung betrachten, area, class, mass, HWB, BGF, setpoint, band, heating limit, H, absent setback (2), solar gains (windows, g, frame), baseload gain | `house_config_profile_house_thermal.render_house_heating_section` |
| 8 | Kühlung | on/off, device, SEER, power, setpoint | `house_config_profile_cooling.render_house_cooling_section` |
| 9 | Verbraucher | one expander per consumer; "Haus Wärme" holds collector, heat source, heating power, storage, heating rod | `_edit_and_sync_consumers`, `house_config_profile_consumers` |
| 10 | *(loose metrics)* | cooling kWh, consumer sum, baseload, warnings | `_render_baseload_preview` |
| 11 | Historische Jahres-Leistungsprofile | import mode, uploads, QC | `house_config_historical_csv` |
| 12 | Gesamt-Lastverhalten | charts; Basislast-Verteilung radio inside the Ist-vs-Modell view | `house_config_historical_modes` |

The auto-save (`_render_house_profile_save`) is called twice, before and after block 11.

## 3. Findings: related parameters that are apart

1. **Heating in three places:** building and comfort (block 7), the heating system inside the "Haus Wärme" consumer expander (block 9), plus the "Heizsysteme" tab. Cooling (block 8) technically hangs on the "Haus Wärme" consumer as well.
2. **Absence in four places:** profile switch (block 4), heating setback (block 7, among comfort fields), "Inaktiv wenn abwesend" per consumer, EV "Prognose, wenn nicht angeschlossen".
3. **Sun / geometry scattered:** PV defaults and horizon under Standort, windows under Gebäude, collector in "Haus Wärme".
4. **Grid / tariff scattered:** the mandatory Netzbereich is last in Standort; the plant-wide export limit and grid meter appear profile-specific.
5. **Consumption balance scattered:** annual kWh and persons at the top, baseload preview after the consumers, historical CSV at the bottom, Basislast-Verteilung hidden in the chart view.
6. **Mixed levels in Gebäude:** physics (area, class, HWB, H), control (setpoint, band, heating limit), absence and gains share one unstructured block.
7. **Consumer form order:**
   - generic: "Läufe pro Woche" comes before "Earnie-Berücksichtigung", although the role decides which fields follow;
   - "Inaktiv wenn abwesend" sits between identity and type fields;
   - "Interner Gewinn" is shown when heating and cooling are off (no effect then);
   - EV: MILP tuning (expert) is inline with the regular fields.

## 4. Proposal

Ordering rule: mandatory and high-impact first, optional and expert last. Every group is an `st.expander`. Mandatory groups start expanded; optional groups start collapsed and show their status in the title (e.g. "Kühlung — aus"). Expander open state is kept per session (same pattern as the consumer expanders: `hc_consumer_exp_open_*`).

**Header (always visible, no expander):** Profil selector · Entfernen · Bezeichnung* · save status.

| Group | Default | Contents (in order) |
|---|---|---|
| **A. Verbrauch & Haushalt** | open, mandatory | Jahresverbrauch*, Personen + reference comparison |
| **B. Standort** | open, mandatory | Land*, Region (Feiertage), lat*, lon*, time zone caption |
| **C. Netzanschluss & Netzentgelt** | open while no Netzbereich | Netzbereich* / own Arbeitspreis + resolved price caption, draft rules; sub-box **"Anlagenweit – gilt für alle Profile"**: export limit, grid meter (Live) |
| **D. Verbraucher** | open | list + "Verbraucher hinzufügen"; directly below: **balance** (consumer sum, cooling, baseload, warnings) |
| **E. Heizung** | collapsed, status in title | switch "Heizung betrachten"; *Gebäude* (area, class, mass, HWB, BGF); *Heizsystem* (heat source, HP type, efficiency, fuel price, heating power, min run time, annual metric) — **moved from "Haus Wärme"**; *Wärmespeicher & Heizstab* (sub-expander); *Regelung* (setpoint, band, heating limit); *Solarthermie* (sub-expander); *Wärmegewinne* (solar gains, baseload gain; sub-expander); *Experte* (H override; sub-expander) |
| **F. Kühlung** | collapsed | switch, device, cooling power, setpoint, SEER |
| **G. Historische Messdaten (CSV)** | collapsed | import mode, uploads, QC, **Basislast-Verteilung** (moved out of the chart view), SE path caption |
| **H. Sonne & Horizont** | collapsed | horizon switch + bar editor; PV default tilt/azimuth (see §5) |
| **I. Abwesenheit** | collapsed | Abwesend / Urlaub + EHAL status; heating setback (only with heating on). Per-consumer flags stay with the consumer. |
| **Gesamt-Lastverhalten** | open | charts (unchanged) |

### Consumer expander order

1. Typ, Bezeichnung (+ ID button), Nennleistung
2. **Generic:** Earnie-Berücksichtigung → Läufe/Woche → Nenndauer → Startzeit → Verschiebung / manual-device fields
3. **EV:** Wallbox & Ladeleistung (wallbox, phases, currents, V2G) → Akku & Ladeplan (capacity, target SOC, efficiency, weekday/weekend, forecast when absent) → sub-expander **Erweitert** (min charge duration, MILP tuning)
4. **Temperatur (RC):** unchanged
5. Historisches Leistungsprofil (CSV)
6. **Betrieb** (last): Inaktiv wenn abwesend, Interner Gewinn (only when heating or cooling is on)

### Open decision: "Haus Wärme" consumer

- **Variant 1 (preferred):** the heating-system fields render in group E. The `thermal_annual` row stays in the data model but is hidden from the consumer list (`_hidden_heating_consumer` already does this when heating is off). Consequence: "Heizung betrachten = on" creates the row itself; `thermal_annual` disappears from the consumer type select. Widget keys (`hc_heat_power_{index}` etc.) are index-based and must be re-keyed to a stable heating key.
- **Variant 2 (lower risk):** "Haus Wärme" stays in the list; group E holds only building, control, gains and expert fields.

Cooling (F) depends on the "Haus Wärme" row in both variants; Variant 1 makes that dependency invisible to the user (switch "Heizung betrachten" once is still required, as today).

## 5. Obsolete or questionable parameters

| Parameter | Finding | Proposal |
|---|---|---|
| `default_pv_tilt` / `default_pv_azimuth` | Only a seed for new PV fields (`ui/planning_pv_form.py`) and the collector, plus a legacy fallback in `collector_surface_from_thermal`. `data/modeled_climate.pv_surface_from_profile` has no production caller (dead code). | **Obsolete candidate:** move to the PV-Felder tab or drop; collector gets its own defaults. Remove `pv_surface_from_profile`. |
| `house_heat_loss_kw_per_k` (H, "0 = auto") | Used, but third way to set the same quantity (class → HWB → H). | Keep, expert sub-expander only. |
| "ID aus Bezeichnung übernehmen" | One-shot migration button for old ids. | Check whether any profile still needs it; else remove. |
| EHAL-Com binding captions (`_live_markers_enabled`) | Docstring calls it legacy; only hint texts in several consumer types. | Reduce to one hint or remove. |
| `absent_mode` on the profile | Operational live switch, not configuration. | Not obsolete; candidate to move to the Cockpit, show status only here. |
| `plant.pv_covers_all_inverters` | Silently popped on grid-meter save (`ui/house_config_plant.py`). | Not a field; move the cleanup to `runtime_store/migration/`. |

## 6. Staging

Decided 2026-11-22: stage 1 before the beta, stage 2 after.

### Stage 1 — reorganise only (no data-flow or behaviour change)

Acceptance: opening a saved profile and leaving the page writes nothing, and every existing AppTest passes unchanged in what it asserts (widget keys stay the same).

- Groups as `st.expander` with a stable `key` (default `on_change="ignore"`, so collapsed content still runs and no widget value is dropped).
- **Variant 2:** "Haus Wärme" stays in the consumer list.
- Render order keeps today's data flow, so it differs from §4 where a later group feeds an earlier one:
  1. header: Profil, Entfernen, Bezeichnung
  2. A Verbrauch & Haushalt
  3. B Standort
  4. C Netzanschluss & Netzentgelt (Netzbereich + plant-wide box)
  5. H Sonne & Horizont — before the consumers, because they read the horizon fields
  6. E Heizung (building, control, gains; sub-headings, H override last)
  7. F Kühlung
  8. D Verbraucher + balance
  9. I Abwesenheit (profile switch + EHAL status only)
  10. G Historische Messdaten (CSV) + Gesamt-Lastverhalten (unchanged module)
- Consumer form: generic role before runs per week; "Inaktiv wenn abwesend" moves to the end, before "Interner Gewinn"; its key position in the saved consumer dict stays the same.
- EV: "Mindest-Ladedauer" and MILP tuning in a nested "Erweitert" expander.
- Unchanged in stage 1: heating setback stays in E (control), "Interner Gewinn" always shown, both auto-save calls, Basislast-Verteilung inside the chart view, PV defaults kept.

### Stage 2 — after the beta

Variant 1 ("Haus Wärme" fields into E), consumers before heating (split state from rendering), absence merged (setback into I), "Interner Gewinn" hidden without heating/cooling (value passed through), one auto-save call, Basislast-Verteilung into G, obsolete parameters (§5), `absent_mode` to the Cockpit.

## 7. Implementation notes

- No JSON change for the regrouping itself; no config migration needed. Variant 1 changes how the `thermal_annual` row is created — still no schema change, but a behaviour change to test (new profile, heating on/off, cooling without heating).
- Render order constraint: `house_heating_state` must be set before consumer forms render (`RuntimeError` otherwise). With D before E, the heating section must compute its state first and render later, or the state must be split from rendering.
- The household reference line already uses a placeholder slot (`household["slot"]`); the same pattern fits the balance box in D and group status titles that need values computed later.
- One auto-save call at the end of the tab.
- AppTests: `tests/test_house_config_*` and Streamlit AppTests locate widgets by key; expanders do not change keys, but moved widgets in Variant 1 do.
- User docs (`docs/konfiguration/`, `docs/user-manual/`) describe the page and must be updated in the same change.
