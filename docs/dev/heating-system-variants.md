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
  `heat_storage`, `parts[heating_rod]`. Since `dm5.heating_power` the catalog stores the
  thermal `heating_power_kw` instead, see [Heating power](#heating-power-2026-11-03).

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

1. The user configures the heating in the house configurator as today, in the section
   „Heizsystem (Referenzsystem: <label>)“ of the „Haus Wärme“ form, below the section
   „Gebäude / Wärmebedarf“. The form creates and edits the referenced catalog entry **in place**; the consumer stores only the reference. No
   inline copy on the consumer and no sync between two copies. Being the reference system is
   derived from the consumer's reference only, not from a flag in the entry. An entry is the
   reference system of **at most one house**: saving a house whose referenced entry another
   house also references fails loud (hand-edited JSON), because the in-place edit would move
   the other house's baseload.
2. A heating-variants editor (Hauskonfigurator area „Heizsysteme“, moved there from the bottom
   of the Szenarienkonfigurator on 2026-11-03) lists all catalog entries. The reference system of a house is
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

House-configurator display (**implemented 2026-11-03**, backlog *Heat demand in kWh_th in the
Hauskonfigurator*): the heat demand in kWh_th as the main figure (nearly system-independent;
only the power limit and storage losses depend on the system), below it "electricity / fuel
with this heating system". The heat is the heat delivered by the heat source, input energy ×
efficiency (`data.heating_need.daily_heat_kwh`,
`data.modeled_climate.thermal_annual_heat_kwh_from_archive`). Not done (optional): a small
table with the annual demand of every catalog variant.

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

**Implemented (2026-11-03, backlog item *Heating-system variants — align code with the
decisions of 2026-11-03*):** the rod measurement fields, their baseload subtraction and the
double-count hint are gone; the loader rejects `heating_rod_profile_csv` /
`heating_rod_annual_kwh` with a German message (`reject_measured_rod_fields`).
`reject_inline_heating_fields` rejects all five `SYSTEM_FIELDS` on a raw consumer.
`save_house_profiles_document` and the house-configurator save reject an entry referenced by
two houses (`assert_reference_systems_unshared`). The scenario select box offers the own
reference system plus variants (`scenario_heating_choices`), resolution rejects another
house's reference system (`apply_scenario_heating_systems(..., foreign_references=…)`), and
the Live scenario shows the reference-system text line. The house-configurator warning on a
`heat_source.type` change lives in `ui/house_config_heating_change.py`
(`reference_heat_source_changes`, `consumption_data_kind`); "remove the CSV data" clears the
house load, battery and grid CSVs and the heating consumer's meter CSV, the PV profile stays.

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

## House-level thermal properties (2026-11-03)

Dog-fooding showed that the building fields do not belong to the heating consumer: they are a
property of the house, the heating only uses them. Decisions (maintainer, 2026-11-03):

- **Data model** (raw `house_profiles.json`, profile level): `heating_enabled` (switch
  „Heizung betrachten“), `thermal` (building block: `living_area_m2`, `hwb_kwh_m2`,
  `building_class`, `building_mass`, `target_temp_c`, `heating_limit_c`, `house_tolerance_c`,
  `house_heat_loss_kw_per_k`, `absent_mode_enabled`, `absent_temp_reduction_c`; SUSI P2 added
  `gross_floor_area_m2` and `thermal.solar_gains`, see [house-gains.md](house-gains.md)) and `persons` (the SUSI P6 hoist, done here). Schema definition
  `house_thermal`. The `thermal_annual` consumer keeps `heating_system_id`, the solar-thermal
  collector, the meter CSV, flex fields and bindings; building fields on it fail loud.
- **Loader** (`house_config/house_thermal.py`, `profiles_store._normalize_profile`): the
  house block plus `persons` is placed into the normalized consumer's `thermal`
  (`consumer_thermal_from_house`), `thermal.absent_mode_enabled` into the consumer's
  `absent_mode_enabled`. Every reader of the thermal block (planner, RC model, Live store,
  baseload, heating need, scenario variants, Szenarien-Explorer) reads the normalized consumer
  as before and needed no change.
- **Switch off:** the normalized profile leaves the `thermal_annual` consumer out of
  `consumers` (not planned; no baseload subtraction, so its consumption stays in the baseload;
  no Live signals) and parks it under `inactive_consumers`. The serializer writes it back after
  the other consumers, `reference_ids_by_profile` and `merge_inline_reference_systems` see it,
  so its reference system stays protected and a save of the loaded document keeps it. A missing
  `heating_enabled` means off (documented schema default) only without a `thermal_annual`
  consumer; with one it is the old file shape and fails loud. A scenario `heating_system_ids`
  pick for a house with the switch off fails loud.
- **One heating consumer per house** (decided): air conditioning is planned as an „inverse
  heat source“ of the same RC model (backlog item), not as a second consumer, and SUSI P2 adds
  its gains to the house block, so both build on `thermal` without a second consumer.
- **Migration** `dm5.house_thermal` (after `dm5.heating_systems`, same data model 5): moves the
  fields and writes `heating_enabled: true` for a house with a `thermal_annual` consumer,
  `false` otherwise; `persons` from the consumer, else the schema default. It keeps the old
  loader semantics (falsy `or default` fields dropped, tolerance / setback clamps, legacy
  `absent_temp_c` converted, nested `thermal` read), so results do not change; two
  `thermal_annual` consumers in one profile block. Recorder snapshots on dm5 from before this
  step fail loud in the loader like those before `dm5.heating_systems` (see Migration).
- **UI:** `ui/house_config_profile_house_thermal.py` renders the section before „Verbraucher“;
  the „Haus Wärme“ form keeps collector, heating system and the consumption estimate (computed
  with the house values). With the switch off the form keeps the consumer row hidden and
  passes it through on save; „Haus Wärme“ is not offered as a type; the heating-system change
  gate is skipped (the heating stays in the baseload, the measured data cannot contradict it).

## Heating power (2026-11-03)

The forms showed „Nennleistung Wärmepumpe (kW, elektrisch)“ and „Mindestlaufzeit“ for every
heat source. Decisions (maintainer, 2026-11-03):

- **One field for every heat source:** a catalog entry stores `heating_power_kw`, the thermal
  heating power of the generator („Heizleistung“ as in SUSI / Heizrechner; it also feeds the
  later SUSI investment and sizing steps P4 / P7). Mandatory and > 0, no default: an entry
  without it fails loud on load. `nominal_power_kw` in a catalog entry fails loud with the
  migration hint.
- **Electric power is derived, not stored:** the loader places `heating_power_kw` and the
  input power `nominal_power_kw = heating_power_kw / efficiency`
  (`house_config.heating_systems.heating_input_power_kw`; JAZ for a heat pump, Nutzungsgrad
  otherwise, rounded to 6 decimals) into the normalized consumer. For heat pump and direct
  electric heating that is the MILP power; for fuel sources it is the fuel power that caps the
  year model's heat (`max_heat = input × efficiency` in `optimizer/thermal_house.py`), as
  before. So the calculation core reads the same fields, and the year model and the MILP stay
  consistent (`heat = electric × JAZ`). Storing a second electric field was rejected: it could
  contradict the heating power.
- **Min-on time only for electric sources:** `min_on_quarterhours` is allowed and shown only
  for heat pump and direct electric heating; on a fuel entry it fails loud.
- **No hidden 3 kW:** the readers of the thermal input power
  (`consumer_input_power_kw`) fail loud instead of falling back to 3 kW. Before, a fuel source
  with `nominal_power_kw` 0 was simulated with 3 kW fuel power.
- **Migration** `dm5.heating_power` (after `dm5.house_thermal`, same data model 5; detection:
  a catalog entry with `nominal_power_kw`): `heating_power_kw = nominal_power_kw × efficiency`
  (stored or default efficiency), so the derived power and all results stay the same. Fuel
  entries lose `min_on_quarterhours`. An entry with power 0 gets no heating power (no question,
  2.8 is unreleased) and fails loud on load until the value is entered. `dm5.heating_systems`
  moves the inline fields with its own frozen field list (`MOVED_FIELDS`).
- **UI:** `render_generation_power_fields` in `ui/house_config_profile_thermal_annual.py` is
  shared by the house configurator and the variants editor: „Heizleistung (kW, thermisch)“,
  for electric sources the derived electric power as a caption and the min-on time.

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
