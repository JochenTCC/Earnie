# Heating-system variants for scenario exploration

Status: **decided (2026-10-31, amended 2026-11-02 and 2026-11-03)**, implementation after the
SUSI P1 dogfooding and before SUSI P2.
Backlog entry: *SUSI P1 follow-up — Heating systems as scenario variants* (Version 2.8).

## Problem

SUSI P1 put the heat source on the `thermal_annual` consumer (`heat_source`, `parts[heating_rod]`).
A scenario selects batteries and PV systems by ID from `components.json` and tariffs from
`tariffs.json`, but selects the house only as a whole (`house_profile_id`). The heating is
therefore a fixed part of the house configuration and cannot be varied in the scenario editor,
although comparing heating variants is a core SUSI use case (P4 annuity, Proto 2 scenario
templates "+ heat pump").

The `thermal_annual` consumer also mixes two concerns:

- **Heat demand of the building:** `living_area_m2`, `building_class`, `hwb_kwh_m2`, `persons`,
  `target_temp_c`, `heating_limit_c`, `building_mass`, `house_tolerance_c`, absent mode.
- **Heat generation:** `heat_source`, `nominal_power_kw` (the electric power of a heat pump,
  unused for fuel sources, see `planning_flex_converters.py`), `min_on_quarterhours`,
  `heat_storage`, `parts[heating_rod]`.

Swapping only `heat_source` is not enough; several generation fields change together.

## Decision

Heating systems become a catalog, following the pattern of batteries and PV systems.

- **Catalog:** `heating_systems[]` in `components.json`. One entry holds `id`, `label`,
  `heat_source`, `nominal_power_kw`, `min_on_quarterhours`, `heat_storage` and `parts`
  (heating rod). The rule "heating rod only with heat storage" stays checkable inside one entry.
- **Reference system:** the `thermal_annual` consumer keeps the building demand and its EHAL
  bindings and gets a mandatory `heating_system_id`: the installed system, which is also the
  system the house's consumption data (`annual_kwh` or measured profiles) refers to. It fixes
  the baseload, and Live plans with it.
- **Scenario names (decided 2026-11-03):** the scenario Earnie runs live is called
  **Ist-Szenario** in the Live optimisation and **Referenz-Szenario** in the Szenarien-Explorer
  (same scenario, today's „Live-Szenario“). It is a **vermessenes Referenz-Szenario** when its
  house profile has measured CSV data. Its heating system is always the reference system, so
  "reference system" and "Referenz-Szenario" mean the same installed state.
- **Scenario selection:** `heating_system_ids: {"<consumer_id>": "<heating_system_id>"}` in the
  scenario `settings` of the **further scenarios** only. A consumer without an entry uses its
  reference system. The scenario editor offers a select box per `thermal_annual` consumer, as
  for batteries. Its choices are the house's own reference system (default, not stored) and the
  **variants**, i.e. the entries that are no house's reference system; the reference system of
  another house is not offered, and a pick of one fails loud on resolution. In the Ist- /
  Referenz-Szenario there is no select box, only a text line naming the reference system
  ("Heizsystem: <label> (Referenzsystem, Änderung im Hauskonfigurator)"), and
  `heating_system_ids` there fails loud when the Ist-Szenario is resolved (Live and
  Szenarien-Explorer; hand-edited JSON). The user keeps the Ist-Szenario in line with the real
  house; Earnie trusts it.
- **Changing the reference system (decided 2026-11-03):** only in the house configurator, and
  only by editing the referenced entry there. The catalog offers no reference system to switch
  to: a variant never becomes a house's reference system, and a house never adopts another
  entry (a user who installs a modeled variant enters its values in the house configurator). A
  change counts when `heat_source.type` of the referenced entry changes (e.g. gas → heat pump),
  compared with the **saved** house file, so a change and its reversal before saving is no
  change. Everything else is calibration and does not count: `heat_pump_type`, efficiency,
  power, storage, rod. When the house has consumption data from the old system, the change
  shows a warning before it is saved, because the data no longer fits the new system:
  - **measured CSV data** (vermessenes Referenz-Szenario): choose between removing the CSV
    data and keeping the heating system;
  - **only `annual_kwh`**: choose between adjusting the annual consumption and keeping the
    heating system. Estimating the electricity difference between two systems automatically is
    a later feature (backlog *Estimate the annual consumption after a heating-system change*).
  No path keeps both the old data and the new system; there is no third option. A new build
  whose `annual_kwh` is already an estimate for the new system gets the same warning and
  chooses "adjust" with the value it has; the German user docs say so. A hand-edited
  `house_profiles.json` gets no warning (Earnie trusts the file).

### Configuration flow

1. The user configures the heating in the house configurator as today. The form creates and
   edits the referenced catalog entry **in place**; the consumer stores only the reference. No
   inline copy on the consumer and no sync between two copies. Being the reference system is
   derived from the consumer's reference only, not from a flag in the entry. An entry is the
   reference system of **at most one house**: saving a house whose referenced entry another
   house also references fails loud (hand-edited JSON), because the in-place edit would move
   the other house's baseload.
2. A new heating-variants editor lists all catalog entries. The reference system of a house is
   shown **read-only** there ("reference system of house X, edit in the house configurator"),
   because changing it changes that house's baseload. It can be copied as the starting point of
   a new variant.
3. Further variants are created and edited only in the variants editor.
4. An entry referenced by a house profile or a scenario cannot be deleted (fail loud, as for a
   battery referenced by a scenario).
5. Deleting a house profile keeps its reference entry in the catalog; without an owner it is an
   ordinary variant from then on (editable, selectable, deletable).

A heat-pump variant is sized for one house's heat load. Selecting it for a different house is
allowed; the SUSI P7 sizing hint later flags a variant that does not fit the house.

## Calculation rule

`annual_kwh` of the house is the electricity consumption of the real house with its installed
heating. Therefore:

1. **Baseload is fixed by the house.** `house_config/baseload.py::compute_baseload_kwh`
   (annual kWh minus Σ `consumer_annual_kwh`) and the measured-data path (total minus modeled
   consumers) always use the **reference system**. So do the house-configurator preview
   (`thermal_annual_kwh_from_archive`, `thermal_annual_fuel_kwh_from_archive`) and the
   over-allocation check (`allocation_diagnostics`).
2. **The scenario swaps only the heat load, after the baseload is resolved.** The scenario's
   heating system enters the thermal profile and the MILP consumer only. Scenario annual
   consumption = baseload + other consumers + electricity of the selected system; a fuel system
   drops the heat-pump share and adds fuel cost.
3. **Order guard.** Applying the scenario's system before the baseload is resolved would
   silently shift the baseload (e.g. by the whole heat-pump consumption for a gas variant). A
   dedicated test pins the order: same house, reference heat pump vs. gas variant → identical
   baseload, different heat load.
4. **Cache key.** `_thermal_year_profiles` in `data/modeled_climate.py` is keyed by
   `(consumer_id, year)`; the key gets the `heating_system_id`, otherwise two scenarios with
   different systems in one process share a profile. The key does not see a parameter
   correction of the same entry, so a `ModeledClimateContext` lives for one run only; a
   long-lived context (Streamlit preview across a save) would need a fingerprint of the
   generation fields in the key.
5. **Measured data without a heat-pump meter.** The modeled profile of the reference system is
   subtracted from `total_profile_csv` and the variant's profile is added. This carries the model
   error of the reference profile; with a separate heat-pump meter the subtraction is exact. The
   scenario results show which of the two applies. The variant itself is always modeled: a
   heat-pump meter CSV measures the reference system, so the variant consumer runs with
   `use_profile_csv` off. A fuel reference system has no electric profile, so the subtraction
   is zero and exact; the variant's heat pump is added on top of the measured total.
6. **Fuel variants and the heating rod.** A fuel variant drops the heat-pump electricity and
   books fuel (`simulation/heat_fuel.py`); its rod is an electric MILP consumer that earns the
   avoided fuel cost per kWh (`heating_rod_fuel_credit_cent_per_kwh`). Beside a heat pump the
   rod competes on efficiency instead. In both cases the rod is capped at the day's heat
   demand (`optimizer/thermal_flex_context.py`).

The calculation functions (`heating_params_from_thermal`, `daily_electric_kwh`,
`house_year_result`) already depend only on their inputs (building, heating system, climate);
they get the resolved system passed in, the core stays unchanged.

House-configurator display (**later**, backlog *Heat demand in kWh_th in the Hauskonfigurator*,
not part of the alignment item): the heat demand in kWh_th as the main figure (nearly
system-independent; only the power limit and storage losses depend on the system), below it
"electricity / fuel with the installed system" as today. Optional: a small table with the annual
demand of every catalog variant. Today only the electricity / fuel figure is shown.

## Heating rod with measured data

The heating rod is not part of the baseload calculation today (`heating_rod` appears only in
`house_config/heat_source.py`, `house_config/planning_flex_converters.py` and
`simulation/heat_fuel.py`). If the real rod runs in the house (e.g. a PV-surplus controller),
its consumption is in the measured total and therefore ends up in the baseload; the MILP then
plans the rod again in the scenario and counts it twice.

**Decided (2026-11-03, replaces the earlier handling):** no historical measured data for the
heating rod, neither a CSV nor a user-entered annual kWh, neither on the consumer nor on a
catalog entry. The heating system must stay freely exchangeable in the scenarios; rod
measurements would tie the measured data to one installed system. The rod keeps no demand of
its own and stays out of `cons_data` (as since `73461c4d`); the MILP alone decides when it
runs. The remaining double count for a house whose real rod ran during the measured period is
accepted and documented in the German user docs, without a runtime hint.

A rod meter for Live (control, visualisation, later balancing) is a separate topic via EHAL
fields of the `heating_rod` part (*SUSI P1 follow-up — Live control of the heating rod*);
those bindings stay on the house consumer, not in the catalog entry.

**Implementation gap:** `d5add969` still has the earlier handling (`heating_rod_profile_csv` /
`heating_rod_annual_kwh` on the consumer and in the serializer, subtracted from the baseload,
double-count hint in `heating_result_hints_by_scenario`, field in the house configurator) and
has no warning on a reference-system change in the house configurator. It also offers every
catalog entry in the scenario select box (including other houses' reference systems), accepts
an entry as the reference system of two houses, and `reject_inline_heating_fields` checks only
`heat_source` / `heat_storage` while inline `parts`, `nominal_power_kw` and
`min_on_quarterhours` on a consumer with `heating_system_id` are overwritten silently. All of
this is handled by the backlog item *Heating-system variants — align code with the decisions of
2026-11-03*. Its rejection of `heating_system_ids` in the Live scenario matches the decision and
stays.

## Migration

Version 2.8 is not released yet (`2.8.0-dev.2`), so the change lands in **data model 5**, the
same 2.8 wizard run as `dm5.heat_source` (SUSI P1) and the planned P2 / P6 fields; users never
see the inline `heat_source` shape. A new step `dm5.heating_systems` runs after
`dm5.heat_source`: it moves `heat_source`, `nominal_power_kw`, `min_on_quarterhours`,
`heat_storage` and `parts` of every `thermal_annual` consumer into a new `components.json`
entry with a generated ID and writes `heating_system_id` on the consumer. Pending detection is
content-based (`step_is_pending` → `detect`), so packs that already ran `dm5.heat_source` during
dogfooding are migrated too. Exception: `migrate_config_dir_unattended(model_bump_only=True)`
(recorder snapshots) runs only steps of a later data model, so a dm5 snapshot with an inline
heat source fails loud in the loader and is migrated once by hand. A pack without
`components.json` gets one that holds only `heating_systems` (the loader defaults the other
arrays). Schemas (`components.schema.json`, `house_profiles.schema.json`,
`backtesting_scenarios.schema.json`) and `share/config/*.example.json` were updated in
`d5add969`; the minimal packs need nothing, `house_profiles.minimal.json` has no
`thermal_annual` consumer. `heating_system_id` is mandatory through the loader, not through the
schema.

## Implementation decisions (2026-11-02)

- **Solar thermal** (`solar_thermal_*`) stays on the consumer (tied to the house roof and
  location); it moves into the heating system only if SUSI variants need "+ solar thermal".
- **Catalog source on load:** the house-profile loader reads `components.json` from the same
  config directory and resolves `heating_system_id` there; the resolved system is placed into
  the normalized consumer (`thermal.heat_source`, `thermal.heat_storage`, `parts`,
  `nominal_power_kw`, `min_on_quarterhours`), so the calculation core reads the same fields as
  before. Saving writes only `heating_system_id`; the loader rejects every one of these five
  generation fields on a raw consumer (fail loud, no silent overwrite by the catalog). The load
  memo is stamped with both files.
- **IDs:** `heating_<profile_id>` for entries written by the migration and by the house
  configurator; a collision gets `_2`, `_3`, … Variants get an ID slugged from their label.
- **Several `thermal_annual` consumers:** not possible, a house profile allows only one
  (`profiles_store`). The scenario editor shows one select box per house; the stored shape stays
  `heating_system_ids: {"<consumer_id>": "<heating_system_id>"}`.

## Docs and tests

- German user docs: `docs/konfiguration/flexible-verbraucher.md` (heat source section),
  scenario editor and components pages under `docs/konfiguration/`.
- Tests: migration step (fixtures before / after, already-migrated dm5 pack with a catalog),
  catalog validation (rod without storage, unknown reference, delete guard, inline generation
  fields rejected on load, entry as reference system of two houses rejected on save), baseload
  order guard, cache key, rod measurement fields rejected on load, rod stays out of
  `cons_data`, `heating_system_ids` in the Ist-Szenario fails loud, another house's reference
  system picked in a scenario fails loud, house-configurator warning on a
  `heat_source.type` change (CSV data / only `annual_kwh` / `heat_pump_type` or parameter
  correction without warning / change and reversal before saving without warning), Streamlit
  AppTest for the variants editor and the scenario select box (variants plus own reference
  system only; text line in the Ist-Szenario); golden masters must stay green (the reference
  system reproduces today's results).
