# EHAL-Com Binding UX — Draft (epic `Binding`)

**Status:** proposal 2026-10-07, not approved. Backlog entry: [Backlog.md](Backlog.md) → *Version 2.+1 - Enhance Auto Binding functionality*. Language: English (backlog rule); UI strings German later.

**Terms:** **SB** = smarthome backend (Loxone / Home Assistant / OpenEMS / later MQTT). **EHAL ID** = identifier of a signal on the Earnie side (`ess.ecoflow_delta_3.sens_ess_power`). **SB name** = identifier of the same signal on the SB side (Loxone Merker / VI-VO title, HA `entity_id`). **Kennung** = the entity slug (`ecoflow_delta_3`) that both identifiers embed.

## 1. Ideas (restated)

1. **SB first (import):** SB user defines SB names and EHAL IDs; Earnie imports, matches against existing entities or generates them.
2. **Earnie first (export):** Earnie defines the signals, proposes SB names, exports them (Loxone: temporary VI/VO templates for Config).
3. **Three-field row** per mapping: EHAL ID · meaning (backend independent) · SB name.
4. **Colour by state:** green = identifier exists on its side, yellow = Earnie suggestion that could be exported. Partial export of all yellow signals for Loxone.
5. **Open:** how does import learn the EHAL IDs?
6. **Entity identity:** users think in *Bezeichnung*, Earnie in `id`. Make the identifier a user-visible variable, Earnie guards uniqueness.

## 2. Code facts (read 2026-10-07)

- **Import derives everything from the Merker name.** `integrations/greenfield_match.py` matches exact names and `prefix + slug + tail` against `share/loxone/greenfield_device_map.json`; the EHAL field is implied by the tail, the entity id by the slug token. This is why consumers work well and why a typo silently drops or mis-files a signal. Re-import merges onto existing consumers by id / thermal singleton / alias tokens (`_find_merge_target`).
- **No battery group in the device map.** `prefix_groups` has heat pump, EV, wallbox, consumer, pool, pool filter. `Earnie_Batterie_<Slug>_…` (decision of 2.7.m) is only documented. Nothing generates or parses it; batteries live in `components.json` with required parameters, so import cannot create them from names.
- **Suggested names exist as data, not as code.** `share/loxone/recipes/*.json` carry `suggested_name` per field (single instance). The multi-instance rule (slug infix) is prose. Irregular names (`Earnie_LadeLeistungs-Limit`, `Earnie_Netzleistung`, `Earnie_Steuerbefehl`) do not fit a `prefix_slug_tail` shape.
- **The EHAL ID is not uniform.** Plant: bare field (`sens_grid_power_active`). Battery / flex: Pattern B (`ess.{slug}.*`, `flex.{slug}.*`). EV, pool, heat storage: bare field on the consumer, shown as `{id}:{field}` in Live. `status.json` keys are a third scheme (`ev.{id}.Earnie_EAuto_Soll_A`, `flex.{id}.Earnie_Verbraucher_Freigabe`, bare `Earnie_Pool_*` titles, bare plant fields; `integrations/loxone_status_json.py`). The VO path in the templates is a fourth (`flex.{hk_id}.sens_power_act`).
- **The EHAL ID is already inside Loxone** for VI/VO: VI `Check="flex.{hk_id}.Earnie_Verbraucher_Freigabe":\v`, VO `CmdOn=/ehal/loxone/telemetry/flex.{hk_id}.sens_power_act/\v`. But `/ehal/loxone/telemetry/*` **has no receiver** (`integrations/loxone_request_http.py` serves only `alive`, `status.json`, `request_optimize`). Core reads `sens_*` by polling `/jdev/sps/io/{Name}`; the VO XMLs are placeholders / a name catalog.
- **Templates are unvalidated drafts** (`share/loxone/templates/README.md`: "hand-authored draft … validate in Config, then re-export"). Installing one is manual: copy to the Config template folder, restart Config, replace `EARNIE_HOST`, `{hk_id}`, Titles.
- **HA:** `list_mappable_entities()` returns `entity_id`, `friendly_name`, unit, device class from `/api/states`; the entity ids are chosen by the integration, not by Earnie. Propose (2.6.b/e) already works against these.
- **Entity id handling:** ids come from `slug_id(label)` in four separate UI paths (consumers, batteries, PV, scenarios). Uncommitted work (`house_config/entity_id_lock.py`, `clean_entity_ids.py`, `scripts/clean_entity_ids_once.py`) lets battery / PV ids follow the Bezeichnung until the first intentional change, then locks them, and batch-cleans `…_copy_N` ids including scenario references and Pattern B keys. Consumers / EVs are not covered. Bugfix "NAS alpha: `ess.15_kwh_speicher_copy_3.*`" is a symptom.

## 3. Findings — consistency, gaps, contradictions

**F1 — The three fields are a view, not new data.** Meaning is a pure function of the field kind (`_field_label`, role JSON labels; already in the dropdown caption). Field 3 is the stored binding. Cheap, no data-model change. The meaning column should include the entity ("EcoFlow Delta 3 — Batterieleistung"), because the same generic text repeats per entity.

**F2 — "Exists on the respective side" means two different things.** The EHAL ID exists iff the Earnie entity exists. In the per-entity table it is therefore always green; it is only yellow in the import preview ("entity would be created"). The SB name exists iff the scan finds it. Both together give a state matrix (§4) that merges direction 1 and 2 into one table. Green/yellow alone is not enough; two more states are needed: **red** (bound, but gone from the SB — dangling) and **grey** (not scanned yet — never show green without a scan). Colour must be paired with a symbol (accessibility).

**F3 — Existence needs a fresh scan.** HA auto-scans once per session; Loxone needs a button press. Without an automatic scan on page entry (with TTL) the colours lie.

**F4 — Direction 1 and 2 are not alternatives.** Realistic installs are hybrid: some signals are existing objects with arbitrary names (EFM meters, own Merker → green), the rest is suggested (yellow). The same table serves both; only the starting point differs.

**F5 — Direction 2 is not automatically less error-prone.** The error moves into the manual step in Config (renaming, wiring a Merker). Templates make `set_*` exact, but `sens_*` names need a Merker that the user wires to a real source. Needed: verification loop "export → create in Config → probe → yellow turns green" and a drift check.

**F6 — "Input/output of the SB" is ambiguous for Loxone.** A name is (a) a VI cmd title (Earnie → Loxone, `set_*`), (b) a VO cmd title (push, `sens_*` — not functional, see §2), or (c) any existing control / EFM designation / Merker. For `sens_*` the green name is usually (c), not an Earnie-pattern name. Export value is therefore highest for `set_*`; for `sens_*` Earnie can only export a name checklist.

**F7 — The EHAL ID is not uniform (see §2).** It cannot become a first-class column, a template parameter or an import key before one qualified form exists. Fix without migrating storage: a function `qualified_ehal_id(entity, field)` + parser as display / exchange form (plant stays bare; `ess.` / `flex.` unchanged; EV / wallbox / inverter get `evcs.{slug}.` / `inv.{slug}.`), storage keys untouched. `status.json` keeps its old keys as aliases for one release (deployed Loxone VI `Check` patterns reference them).

**F8 — "First instance gets the bare name" contradicts stable suggestions.** `Earnie_Verbraucher_Freigabe` for the first, `…_<Slug>_Freigabe` for the second: adding a second entity changes what the first would be called. New suggestions should always contain the slug; bare names stay recognised on import (legacy).

**F9 — One naming table must serve both directions.** Extend the device map to explicit `{field → name_prefix, tail}` per entity role (including battery, irregular names). Export: `suggest(entity, field)`. Import: `parse(name)`. Property test: `parse(suggest(x)) == x` for every role field. Today these are two code paths with prose in between.

**F10 — HA: the third field exists, but is not ours to name.** `entity_id` (plus `friendly_name`, registry `unique_id`) is chosen by the integration → almost always green; yellow only for helper entities (`input_number` / `input_boolean`) for write signals. Direction 1 has no meaning for HA (no EHAL ID lives in HA); the existing propose is the import. Earnie-first for HA overlaps with Add-on 1.0 (MQTT discovery, Earnie-chosen entity ids).

**F11 — Saving a yellow (missing) name.** The "New Merker?" flow already stores names that return 404 ("mapping active anyway"). Runtime behaviour on write/read of a missing Merker is not specified here — check, and make it one clear log line instead of an error each cycle.

**F12 — Export should follow need, not completeness.** `ehal/functions.py` knows which fields a function needs (unavailable until all are mapped). Offer **minimal** (fields required by enabled functions / `control` level) vs **all**.

**F13 — Kennung as variable: rename is a cascade.** The slug is embedded in EHAL IDs (Pattern B keys), scenario references and Shadow overlay. It is also in **SB names that already exist and do not follow a rename**; after a rename the bound Loxone name deviates from the convention, and a re-import by prefix + slug can create a duplicate for the old slug. History / debug dumps / regression fixtures pinned to ids may break (which files key by id: verify in P0). So: editable Kennung only through an explicit action with dry-run and report; the report lists SB names that now deviate (rename list for the SB). No separate immutable `uid` for now (large model change); revisit if P0 shows history keyed by id.

**F14 — Import cannot create batteries / PV / inverters from names.** Required parameters (capacity, power) are missing. Options: create an *incomplete* stub that blocks planning readiness, or bind only to existing entities by Kennung. Open decision.

**F15 — Namespace collisions.** SB names must be checked against all scanned names (case-insensitive, Loxone matching is case-insensitive in the import) and Kennung uniqueness across entities that share a prefix. `slug_id(existing=…)` guards one list at a time.

## 4. Signal row and sync states

One row = qualified EHAL ID · meaning · SB name · state (derived at render time from a scan; never persisted).

| EHAL ID (Earnie) | SB name | State | Action |
| --- | --- | --- | --- |
| entity exists | exists | green ✓ | bound, verified |
| entity exists | suggested, missing | yellow ◌ | export candidate (Earnie → SB) |
| entity missing (import preview) | exists | yellow ◌ (on the ID) | import candidate (SB → Earnie), entity would be created |
| entity exists | bound, gone from SB | red ✕ | dangling binding — fix or remove |
| entity exists | not scanned | grey ? | scan first |
| entity exists | unmapped, no suggestion | neutral | map by hand |

User-typed unknown names are yellow too (same state: not in the SB yet, exportable); origin only as tooltip.

## 5. Proposal (epic `Binding`)

Order: **P0 → P1 → P2 → P3**; P4 after P1; P6 can start now (builds on the uncommitted `entity_id_lock` work) and should land before **Inverter P2** and the Pool nesting; P5 last. Sizes are rough, not measured.

**P0 — Spikes (S).** No product code.
- (a) Loxone Config round trip: import our VI/VO XML, "Als Vorlage speichern", diff; fix the canonical template shape; check what Config accepts for installing generated templates.
- (b) What does `LoxAPP3.json` expose beyond name / uuid / type / room / category (VI Check, VO CmdOn, description)? Decides whether import can read EHAL IDs from Loxone, and whether a Loxone project file / exported template XML is parseable.
- (c) Which persisted files key by entity id (optimization history, run state, Shadow overlay, debug dumps, regression fixtures)? Decides the rename cascade scope.
- (d) Runtime behaviour for a bound but missing Merker (F11).

**P1 — Naming grammar + qualified EHAL ID (M).** `qualified_ehal_id` + parser for all entity kinds (storage unchanged). Device map → bidirectional `{field → prefix, tail}` incl. battery group and irregular names. `suggest_sb_name` (Loxone, slug always included) / `parse_sb_name`. Optional `suggest_ha_helper_id` for `set_*`. `status.json` dual-emits qualified + legacy keys. Tests: round trip, uniqueness against scanned names, every role field covered.

**P2 — Three-column table + sync states (M).** Both backends, entity-centric as today. Row: qualified ID · meaning (with entity) · SB name select + state chip. Streamlit cannot colour selectbox options: colour via `:green[]` / `:orange[]` badges next to the select, emoji prefix in `format_func`. Auto-scan on entry with TTL, "Prüfen" button, per-entity counter (n ✓ / m ◌ / k ✕) in the entity picker. "Vorschläge übernehmen" fills empty fields with suggestions after one bulk confirmation (replaces the per-field "New Merker?" dialog for suggestions). Shadow-safe (view only).

**P3 — Loxone export of yellow signals (M–L, needs P0a + P1).** Generator on recipes + verified templates: VI XML for `set_*`, name checklist (CSV / Markdown) for `sens_*`, VO only once a receiver exists. Real Titles and Check / path from the qualified IDs, `EARNIE_HOST:port` from settings (editable; container IP caveat, see smarthome-backend docs). Minimal vs all (F12). Download ZIP + 3-step README. After install: "Prüfen" turns yellow → green. Supersedes the existing "Earnie → Loxone template XML" item; removes the manual `{hk_id}` / Title replacement from the Loxone docs.

**P4 — Import hardening + signal catalog (M, after P1).**
- Did-you-mean validator for `Earnie_*` names with unknown tail / typo (parse table + edit distance); import report: matched / near-miss with suggestion / ignored.
- Preview before creating entities (list of new entities with bindings, Bezeichnung / Kennung editable) instead of silent `apply_typed_matches`.
- **Signal catalog file** (CSV / YAML: `ehal_id; meaning; sb_name; direction; unit`): exportable from the table (direction 2) and importable (direction 1), backend independent, strict validation against the EHAL field registry. This is the answer to "how does import learn EHAL IDs" that does not depend on Loxone internals; the SB user / integrator maintains it.
- Depending on P0b: parse VI/VO template XML, or implement the `/ehal/loxone/telemetry/` receiver and list unknown incoming IDs as an inbox.
- Batteries / PV / inverters: stub vs bind-only (F14).

**P5 — HA parity (S–M).** Column 3 = `entity_id` with `friendly_name` hint; red state for vanished entities; helper proposals for `set_*` only. Helper YAML export only if wanted (copy-paste, no write into HA — same decision as the Bridge-Builder draft). Align with Add-on 1.0 `unique_id` scheme.

**P6 — Kennung as editable variable (M–L).** Field "Kennung" next to Bezeichnung on every entity form (consumer, EV, battery, PV; inverter / wallbox from the start), prefilled from the label, live uniqueness check, lock semantics as in `entity_id_lock`. Explicit "Kennung ändern" with cascade dry-run (scenario refs, Pattern B keys, Shadow overlay, per P0c) and a report of SB names that now deviate. Generalise `clean_entity_ids` to `rename_entity_id(kind, old, new)` with `--config-dir` / `--dry-run`, same config-dir list as the **2.7.l** one-off script. Unify the four `slug_id` UI paths.

## 6. Overlaps in the backlog

| Item | Effect |
| --- | --- |
| Same chapter: "Earnie → Loxone template XML (…multiple batteries after 2.7.c)" | Absorbed by **P3**; "after 2.7.c" is obsolete (2.7.c is done). |
| **2.7.l Inverter** P2 / P4 (EHAL role `inverter`, EHAL-Com rows, built-in inverter `owned_by`) | New entity kind must plug into P1 grammar and P2 table from the start; do P1 before Inverter P4. Built-in inverter slug vs battery rename → P6 cascade. P1 migration one-off and P6 share the config-dir list. |
| Multi-EV / Wallboxes (2.+1) | EV fields are not Pattern B today; the qualified ID in P1 must cover `evcs.{slug}` and a separate wallbox entity. |
| Nested data models / **Pool nesting**, "Move Loxone markers to data model" | Pool-Filter merge changes `flex.pool_filter.*` and `Earnie_Pool_Filter_*`; the bare-title special cases in `loxone_status_json.py` are exactly what P1 removes. Land P6 rename cascade before the merge. |
| **HA-Loxone-Bridge-Builder** (research) | Stays decoupled by its own decision (no shared code with Earnie). Its deferred "Loxone VI/VO XML" is not the P3 generator. |
| **Add-on Version 1.0** (MQTT discovery) and "EHAL adaptation for MQTT" | Earnie-first for HA / MQTT: entity id / `unique_id` / topic = qualified ID (+ stable Kennung). MQTT is the easiest third backend for the same table. |
| **2.7.m** (archived) | Defined `Earnie_Batterie_<Slug>_…` and per-battery bindings; no generator / parser followed → P1. |
| **2.7.i** Regression, HouseSim | Fixtures pin ids: rename cascade must keep them valid or re-record; HA golden maps stay valid (propose unchanged). |
| Bugfix "NAS alpha `ess.15_kwh_speicher_copy_3.*`" | Symptom of dirty ids (uncommitted id-lock work) plus a physical powerstation without own Merker; **P2** red / yellow states make this visible. |
| **SB-Identification-Draft** | Only the term "SB"; discovery is independent. |

## 7. Open decisions

1. **Kennung semantics (P6):** editable variable with cascade (proposed) vs. keeping `id` immutable and only displaying it. Interpretation of "Variable" here: editable, defaulting from the Bezeichnung.
2. **Saved-but-missing names (F11):** allowed with one warning (as today) vs. not saved until probe finds them.
3. **Import of batteries / PV / inverters (F14):** incomplete stub vs. bind-only.
4. **Always-slug names (F8):** confirm; legacy bare names stay readable.
5. **`sens_*` export:** name checklist only, until a VO receiver exists — acceptable?
6. **Epic name `Binding`** and phases to be added to `roadmap-nomenclature.mdc` on approval (as done for `Inverter`).

## 8. Not checked

External development documents (`Entwicklungsplan`, HA add-on docs) are not in this checkout. Loxone Config behaviour (template install, project file format, LoxAPP3 content) is unverified until P0.
