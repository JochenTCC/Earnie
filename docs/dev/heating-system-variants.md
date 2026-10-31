# Heating-system variants for scenario exploration

Status: **decided (2026-10-31)**, implementation after the SUSI P1 dogfooding and before SUSI P2.
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
  bindings and gets a mandatory `heating_system_id`: the system actually installed (or, for a
  new build, the system the user's `annual_kwh` refers to). Live always uses it.
- **Scenario selection:** `heating_system_ids: {"<consumer_id>": "<heating_system_id>"}` in the
  scenario `settings`. A consumer without an entry uses its reference system. The scenario editor
  offers a select box per `thermal_annual` consumer, as for batteries.

### Configuration flow

1. The user configures the heating in the house configurator as today. The form creates and
   edits the referenced catalog entry **in place**; the consumer stores only the reference. No
   inline copy on the consumer and no sync between two copies. Being the reference system is
   derived from the consumer's reference only, not from a flag in the entry.
2. A new heating-variants editor lists all catalog entries. The reference system of a house is
   shown **read-only** there ("reference system of house X, edit in the house configurator"),
   because changing it changes that house's baseload. It can be copied as the starting point of
   a new variant.
3. Further variants are created and edited only in the variants editor.
4. An entry referenced by a house profile or a scenario cannot be deleted (fail loud, as for a
   battery referenced by a scenario).

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
   different systems in one process share a profile.
5. **Measured data without a heat-pump meter.** The modeled profile of the reference system is
   subtracted from `total_profile_csv` and the variant's profile is added. This carries the model
   error of the reference profile; with a separate heat-pump meter the subtraction is exact. The
   scenario results show which of the two applies.

The calculation functions (`heating_params_from_thermal`, `daily_electric_kwh`,
`house_year_result`) already depend only on their inputs (building, heating system, climate);
they get the resolved system passed in, the core stays unchanged.

House-configurator display: the heat demand in kWh_th as the main figure (nearly
system-independent; only the power limit and storage losses depend on the system), below it
"electricity / fuel with the installed system" as today. Optional: a small table with the annual
demand of every catalog variant.

## Heating rod with measured data

The heating rod is not part of the baseload calculation today (`heating_rod` appears only in
`house_config/heat_source.py`, `house_config/planning_flex_converters.py` and
`simulation/heat_fuel.py`). If the real rod runs in the house (e.g. a PV-surplus controller),
its consumption is in the measured total and therefore ends up in the baseload; the MILP then
plans the rod again in the scenario and counts it twice. Decided handling, in this order:

1. **Rod with its own meter:** the measured rod consumption is subtracted from the total before
   the baseload is derived.
2. **No meter, user-entered annual rod consumption:** a new optional field (annual kWh of the
   real rod) on the reference system; this amount is subtracted from the baseload.
3. **Neither:** a visible hint in the scenario results that the rod may be counted twice. No
   silent correction.

Houses without measured data (`profile_spec`) are not affected.

## Migration

Version 2.8 is not released yet (`2.8.0-dev.2`), so the change lands in **data model 5**, the
same 2.8 wizard run as `dm5.heat_source` (SUSI P1) and the planned P2 / P6 fields; users never
see the inline `heat_source` shape. A new step `dm5.heating_systems` runs after
`dm5.heat_source`: it moves `heat_source`, `nominal_power_kw`, `min_on_quarterhours`,
`heat_storage` and `parts` of every `thermal_annual` consumer into a new `components.json`
entry with a generated ID and writes `heating_system_id` on the consumer. Pending detection is
content-based (`step_is_pending` → `detect`), so packs that already ran `dm5.heat_source` during
dogfooding are migrated too. Schemas to update: `components.schema.json`,
`house_profiles.schema.json`, `backtesting_scenarios.schema.json`; example and minimal packs
under `share/config/`.

## Open points for the implementation

- Solar thermal (`solar_thermal_*`): stays on the consumer or moves into the heating system.
  Default: stays (it is tied to the house roof and location); move only if SUSI variants need
  "+ solar thermal".
- ID generation for migrated entries and for entries created by the house configurator.
- Shape of the per-consumer selection in the scenario editor when a house has more than one
  `thermal_annual` consumer.

## Docs and tests

- German user docs: `docs/konfiguration/flexible-verbraucher.md` (heat source section),
  scenario editor and components pages under `docs/konfiguration/`.
- Tests: migration step (fixtures before / after, already-migrated dm5 pack), catalog
  validation (rod without storage, unknown reference, delete guard), baseload order guard,
  cache key, heating-rod handling 1–3, Streamlit AppTest for the variants editor and the
  scenario select box; golden masters must stay green (the reference system reproduces today's
  results).
