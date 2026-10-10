# EHAL-Com Binding UX — Draft (epic `Binding`)

**Status:** proposal 2026-10-07; **revised 2026-10-08 (§0 is authoritative; where §1–§8 contradict it, §0 wins)**. Backlog entry: [Backlog.md](Backlog.md) → *Version 2.+1 - Enhance Auto Binding functionality*. Language: English (backlog rule); UI strings German later.

**Terms:** **SB** = smarthome backend (Loxone / Home Assistant / OpenEMS / later MQTT). **EHAL ID** = identifier of a signal on the Earnie side (`ess.ecoflow_delta_3.sens_ess_power`). **SB name** = identifier of the same signal on the SB side (Loxone Merker / VI-VO title, HA `entity_id`). **Kennung** = the entity slug (`ecoflow_delta_3`) that both identifiers embed.

## 0. Revision 2026-10-08 — consequences of push-only

The Loxone read path went push-only (backlog 2.7.o, `backlog/Binding-Push-Only-Conversion.md`) and works. The maintainer then decided:

1. **Writes go push-only too** (backlog **2.7.q**): Earnie publishes `set_*` / enables in `status.json` under their qualified EHAL IDs, the Miniserver VI picks them up. No direct `/dev/sps/io/<name>/<value>` call, no Merker name.
2. **Meter-energy poll (`/all`) is retired.** Each meter gets a second VO that pushes the total energy next to its power VO (2.7.q Q6). The slot-Ist sampler reads the counter from the inbox; ΔkWh logic stays, no averaging or integration of power is added.
3. **Principle:** Earnie defines the signals (qualified IDs); the smarthome backend maps them to its own objects (Loxone: the source in the VO command, the target at the VI output; HA: a generated YAML package). Earnie stores no SB names for Loxone.
4. **Home Assistant: Weg B.** HA uses the same HTTP contract in both directions (HA pushes telemetry with `rest_command`, polls `status.json` for setpoints). Earnie generates the YAML and pre-fills `entity_id`s from today's bindings. The REST pull adapter and the HA mapping chapter stay until parity is proven.
5. **Kennung rename risk accepted** as not worse than before (the Kennung is now part of the wire address, so a rename needs a matching Loxone change; the P6 report lists the affected addresses).

### 0.1 What stays true

- The EHAL-Com page becomes the **signal contract page**: it shows which EHAL fields Earnie needs (and which function needs them), whether the backend delivers / fetches them (match), and offers the export (Loxone VO / VI templates; HA YAML).
- Row: qualified EHAL ID · meaning (with entity) · required by · match status · export. Match status is derived at render time, never persisted: Loxone read = last received (age) / never; Loxone write = last fetched by the Miniserver; HA Weg B likewise; legacy HA pull = mapped `entity_id`. Colour always with a symbol.
- Direction 1 (SB first) and direction 2 (Earnie first) collapse: the contract is always Earnie's; the SB side either already delivers it (green) or gets the export (open). Hybrid installs need no special case.
- What remains of the SB name: the **Loxone import** (typed entities from Merker / EFM names, `greenfield_device_map.json`, prefix + slug). It creates entities, it no longer writes names into bindings.

### 0.2 Effect on the analysis below

| Item | Status |
| --- | --- |
| §1 idea 3 (three-field row with SB name), idea 4 (colours from SB-name existence) | Replaced by the row in §0.1; the SB-name column disappears for Loxone. |
| §1 idea 5 / §7.3 (how does import learn EHAL IDs) | Answered: the ID arrives in the push; unknown IDs go to a discovery list (P4). No signal-catalog file needed. |
| §2 bullet "EHAL ID is already inside Loxone … has no receiver" | Outdated: the receiver exists (2.7.o). |
| F2, F3, F5 (existence needs a scan, state matrix, verification loop) | Largely replaced by "received / fetched" status, which needs no scan. Still relevant for HA pull (legacy) and for the Loxone import. |
| F6 (VO not functional, `sens_*` export = name checklist only) | Obsolete: VO is the read path, export = VO templates. |
| F7 (qualified ID before anything else) | Still the foundation (2.7.n-2). |
| F8, F9 (always-slug suggestions, one naming table both directions) | Obsolete for Loxone reads / writes (no names). The VO title is derived from the qualified ID. Naming grammar only remains for the import. |
| F10 (HA third field not ours to name) | Replaced by Weg B: the HA side is generated from the contract. |
| F11 (bound but missing Merker) | Obsolete after 2.7.q. |
| F12 (export follows need) | Kept: "needed only" from `ehal/functions.py`. |
| F13 (Kennung rename cascade) | Kept, and more concrete: the report lists Loxone VO / VI addresses and HA package entries that deviate after a rename. |
| F14 (import of battery / PV / inverter) | Open, unchanged. |
| F15 (namespace collisions) | Mostly gone (no free-text names). Kennung uniqueness stays. |
| §4 state table | Replaced by §0.1 match status. |
| §5 P0–P6 | Re-scoped in the backlog, see §0.3. |

### 0.3 Phases after the revision

| Phase | New scope |
| --- | --- |
| P0 | (a) done in the pilot; (b) obsolete; (c) open; (d) obsolete after 2.7.q. |
| P1 | Qualified ID + parser = **2.7.n-2**. SB-name grammar dropped. |
| P2 | Signal list + match status; first Loxone slice in **2.7.q Q7**; HA and polish later. |
| P3 | Export of VO / VI templates ("needed only" / "all"); VI generator in 2.7.q Q4. |
| P4 | Import preview, did-you-mean for near-miss names, discovery list of unknown incoming IDs. Signal catalog dropped. |
| P5 | HA Weg B (HTTP contract, backend-neutral receiver `/ehal/telemetry/…`, YAML package pre-filled from bindings, units handled in HA or via a `unit` parameter, add-on can ship the package). Pull adapter and HA mapping chapter retire after parity. |
| P6 | Kennung as editable variable; rename report lists wire addresses. |

### 0.4 Write path (2.7.q) in one picture

Today: direct `GET /dev/sps/io/<Merker>/<value>` **and** a `status.json` mirror, with mixed keys (plant bare fields, `ess.<id>.set_*`, `ev.<id>.Earnie_EAuto_*`, `flex.<id>.Earnie_*_Freigabe`, bare pool titles). After: only `status.json`, keys = qualified IDs (`evcs.<id>.set_evcs_max_current`, `consumer.<id>.set_enable`, …), legacy keys emitted for one version. A dual-run is idempotent because both paths set the same VI input. Open: VI poll latency (30 s) against the immediate direct write; Schreibtest round trip (read-back through a VO echo); silent / Shadow gating of the `status.json` endpoint.

### 0.5 Not overlooked, but to verify

- `ehal/functions.py::_mapped_fields` counts only non-empty binding values; empty-valued push-only Loxone keys would make functions look unavailable (2.7.q Q8).
- Schreibtest, `scripts/verify_loxone_setup.py`, the watchdog and the AlarmClock `SpecialState10` poll still use names or polls (2.7.q Q7).

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

**[Obsolete, see §0.2]** **F6 — "Input/output of the SB" is ambiguous for Loxone.** A name is (a) a VI cmd title (Earnie → Loxone, `set_*`), (b) a VO cmd title (push, `sens_*` — not functional, see §2), or (c) any existing control / EFM designation / Merker. For `sens_*` the green name is usually (c), not an Earnie-pattern name. Export value is therefore highest for `set_*`; for `sens_*` Earnie can only export a name checklist.

**F7 — The EHAL ID is not uniform (see §2).** It cannot become a first-class column, a template parameter or an import key before one qualified form exists. Fix without migrating storage: a function `qualified_ehal_id(entity, field)` + parser as display / exchange form (plant stays bare; `ess.` / `flex.` unchanged; EV / wallbox / inverter get `evcs.{slug}.` / `inv.{slug}.`), storage keys untouched. `status.json` keeps its old keys as aliases for one release (deployed Loxone VI `Check` patterns reference them).

**F8 — "First instance gets the bare name" contradicts stable suggestions.** `Earnie_Verbraucher_Freigabe` for the first, `…_<Slug>_Freigabe` for the second: adding a second entity changes what the first would be called. New suggestions should always contain the slug; bare names stay recognised on import (legacy).

**[Obsolete for Loxone, see §0.2]** **F9 — One naming table must serve both directions.** Extend the device map to explicit `{field → name_prefix, tail}` per entity role (including battery, irregular names). Export: `suggest(entity, field)`. Import: `parse(name)`. Property test: `parse(suggest(x)) == x` for every role field. Today these are two code paths with prose in between.

**[Replaced by Weg B, see §0.2]** **F10 — HA: the third field exists, but is not ours to name.** `entity_id` (plus `friendly_name`, registry `unique_id`) is chosen by the integration → almost always green; yellow only for helper entities (`input_number` / `input_boolean`) for write signals. Direction 1 has no meaning for HA (no EHAL ID lives in HA); the existing propose is the import. Earnie-first for HA overlaps with Add-on 1.0 (MQTT discovery, Earnie-chosen entity ids).

**[Obsolete after 2.7.q, see §0.2]** **F11 — Saving a yellow (missing) name.** The "New Merker?" flow already stores names that return 404 ("mapping active anyway"). Runtime behaviour on write/read of a missing Merker is not specified here — check, and make it one clear log line instead of an error each cycle.

**F12 — Export should follow need, not completeness.** `ehal/functions.py` knows which fields a function needs (unavailable until all are mapped). Offer **minimal** (fields required by enabled functions / `control` level) vs **all**.

**F13 — Kennung as variable: rename is a cascade.** The slug is embedded in EHAL IDs (Pattern B keys), scenario references and Shadow overlay. It is also in **SB names that already exist and do not follow a rename**; after a rename the bound Loxone name deviates from the convention, and a re-import by prefix + slug can create a duplicate for the old slug. History / debug dumps / regression fixtures pinned to ids may break (which files key by id: verify in P0). So: editable Kennung only through an explicit action with dry-run and report; the report lists SB names that now deviate (rename list for the SB). No separate immutable `uid` for now (large model change); revisit if P0 shows history keyed by id.

**F14 — Import cannot create batteries / PV / inverters from names.** Required parameters (capacity, power) are missing. Options: create an *incomplete* stub that blocks planning readiness, or bind only to existing entities by Kennung. Open decision.

**F15 — Namespace collisions.** SB names must be checked against all scanned names (case-insensitive, Loxone matching is case-insensitive in the import) and Kennung uniqueness across entities that share a prefix. `slug_id(existing=…)` guards one list at a time.

## 4. Signal row and sync states *(superseded by §0.1)*

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

## 5. Proposal (epic `Binding`) *(original; re-scoped in §0.3)*

Order: **P0 → P1 → P2 → P3**; P4 after P1; P6 can start now (builds on the uncommitted `entity_id_lock` work) and should land before **Inverter P2** and the Pool nesting; P5 last. Sizes are rough, not measured.

**P0 — Spikes (S).** No product code.
- (a) Loxone Config round trip: import our VI/VO XML, "Als Vorlage speichern", diff; fix the canonical template shape; check what Config accepts for installing generated templates.
- (b) What does `LoxAPP3.json` expose beyond name / uuid / type / room / category (VI Check, VO CmdOn, description)? Decides whether import can read EHAL IDs from Loxone, and whether a Loxone project file / exported template XML is parseable.
- (c) Which persisted files key by entity id (optimization history, run state, Shadow overlay, debug dumps, regression fixtures)? **Done 2026-10-10** — [`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md); **Alias table: yes**.
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
| **2.7.n** (Backlog.md, Version 2.7) | Slice of this epic for 2.7: stable identifiers (**P1** core, **P6** core, `ev.` / `evcs.` namespaces) plus the generic Loxone read path (n-5, gated). The write path is **2.7.q**, which runs first. See §0 and §9. |
| **SB-Identification-Draft** | Only the term "SB"; discovery is independent. |

## 7. Open decisions

*Revised 2026-10-08: decisions 1 and 3 are obsolete (no saved names, no name checklist). Open now: battery / PV / inverter import (stub vs bind-only), HA unit handling on the wire, activation-flag storage for Loxone fields (see backlog Binding and 2.7.q).*

1. **Saved-but-missing names (F11):** allowed with one warning (as today) vs. not saved until probe finds them. Decide after P0d.
2. **Import of batteries / PV / inverters (F14):** incomplete stub vs. bind-only. Decide before P4.
3. **`sens_*` export:** name checklist only, until a VO receiver exists — acceptable? Decide after P0a/b.

**Decided:**
- Epic `Binding` with phases P0–P6 is registered in `roadmap-nomenclature.mdc` (as done for `Inverter`).
- **Kennung is editable** (P6), defaulting from the Bezeichnung. Rename only as an explicit action with cascade dry-run and a report of SB names that now deviate. **P0c done (2026-10-10):** history / runtime state / shadow / ledgers / cons_data keyed by id → **alias table yes** (alias-on-read for history; rewrite-on-rename for small live files; dumps/fixtures re-record) — [`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md). No separate immutable `uid`.
- **Always-slug names (F8):** new name suggestions always contain the Kennung; legacy bare names stay recognised.
- **Two namespaces for wallbox and vehicle:** `evcs.<wallbox>.*` and `ev.<vehicle>.*` (§9).
- **`sens_evcs_connected`** is valid in both namespaces and keeps its name in 2.7.n.

## 8. Not checked

External development documents (`Entwicklungsplan`, HA add-on docs) are not in this checkout. Loxone Config behaviour (template install, project file format, LoxAPP3 content) is unverified until P0.

## 9. Slice for 2.7: item 2.7.n

*Revised 2026-10-08: the write half of the generic path (former n-6) moved into **2.7.q** (push-only via `status.json`); n-5 is conversion only. See §0.*

Principle: **freeze the identifiers now, build the tools later.** An identifier that is baked into deployed Loxone configs, VI templates and bindings is hard to change; table, export and import can be added any time.

**In 2.7.n:** four bugfixes (two fixed directly, two closed by the generic write path), P0c (**done** — alias yes; see [`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md)) / P0d (dropped after push-only), qualified EHAL ID for all entity kinds, stable Kennung (batteries / PV, lock for consumers / EVs), characterization tests, field registry in the role JSON, generic Loxone read and write path. **Not in 2.7.n:** three-column table, colours, export, import hardening, signal catalog, HA parity, multi-EV runtime.

**Several wallboxes and EVs (naming only).** Bindings are already stored per EV consumer and resolved per consumer; only the Pattern B spelling is missing (today a mix in `status.json` `ev.{id}.Earnie_EAuto_Soll_A` and the VO path `ev.{ev_id}.<field>`).

| Namespace | Device | Field kinds (unchanged) |
| --- | --- | --- |
| `evcs.<wallbox>.<kind>` | wallbox (charger) | `sens_evcs_active_power`, `sens_evcs_connected`, `get_evcs_nominal_current`, `set_evcs_max_current`, `set_evcs_mode` |
| `ev.<vehicle>.<kind>` | vehicle | `sens_evcs_soc_act`, `sens_evcs_bat_capacity`, `get_evcs_limit_soc`, `get_evcs_soc_min_immediate`, `get_evcs_ready_by_time` |

**Namespaces for the other consumers (decided).** Named by device type, not by the cryptic `flex.`:

| Entity | Namespace | Example |
| --- | --- | --- |
| Plant (one per house) | none | `sens_grid_power_active`, `sens_temperature_outside` |
| Battery | `ess.<Kennung>.` | `ess.15_kwh_speicher.sens_ess_soc` |
| Heat pump (`thermal_annual`) | `heatpump.<Kennung>.` | `heatpump.waermepumpe.sens_temperature_heat_storage` |
| Pool (`thermal_rc`, and the `pool_filter` entity) | `pool.<Kennung>.` | `pool.pool_swimspa.sens_temperature_water` |
| Every other consumer | `consumer.<Kennung>.` | `consumer.waschmaschine.sens_power_act` |
| Inverter (2.7.l P4) | `inv.<Kennung>.` | |

Rule: a namespace equals the field-name stem where one exists (`ess` ↔ `sens_ess_*`, `evcs` ↔ `sens_evcs_*`, `inv` ↔ `sens_inv_*`); otherwise the device type. `flex.<slug>.*` stays an accepted alias on input (stored bindings, `status.json`, deployed VI check patterns) and is not emitted in new IDs. Renaming the stored keys needs an alias on load and is a separate step.

- Today's single EV consumer `garage` yields both forms from one Kennung (`evcs.garage.set_evcs_max_current`, `ev.garage.sens_evcs_soc_act`); the namespace follows the field kind, storage stays flat.
- Later separate entities carry their own Kennung; the car ↔ wallbox assignment is runtime logic, not part of the names.
- `sens_evcs_connected` is allowed in both namespaces (both devices report "connected"). **Decided:** kept under this name in 2.7.n; a rename to `sens_connected` is possible later but needs an alias on load (about 25 code places plus schema, role JSON, recipes, fixtures and stored bindings).
- Field kinds are not renamed (`sens_evcs_soc_act` says "evcs" but means the vehicle; a rename would break the wire, possible later with an alias).
- Loxone names: `Earnie_Wallbox_<Kennung>_…` for charger kinds, `Earnie_EAuto_<Kennung>_…` for vehicle kinds; existing names (`Earnie_EAuto_Soll_A`) stay valid because bindings store the real name.
- The adapter still uses only the first EV (`_first_ev_loxone_bindings`); multi-EV runtime stays in the backlog item "Enable multiple EV / Wallboxes".

**Generic path, kept safe.** Only transport and conversion become data-driven (unit, factor, sign, clamp per field in the role JSON). The decision logic (which value is written when: `map_ess_setpoints`, sticky refresh, function gating) stays in code. A single writer returns records keyed by qualified ID; the write trace, the `loxone_sent` snapshot and `status.json` are built from them, which removes the two bugs structurally. Safety: characterization tests first (n-4), Shadow would-write comparison (`shadow_writes.jsonl`) old vs new, and a hard gate — if n-5 / n-6 are not ready, n-1 … n-4 ship alone.

## 10. Pilot findings (spike/vo-push-pilot, 2026-10-07)

Observed with the Miniserver and the NAS alpha instance:

- A Virtual Output command is a plain `GET` from the Miniserver without extra headers; the token can only travel as `?t=` in the command (it arrives unchanged).
- The value placeholder in a VO command is `<v>` (`<v.1>` for one decimal); `<v>` arrives with a point and three decimals. The Virtual-Input escape in a VO command is sent as the control character 0x0B.
- Repeat works with unchanged values: exactly every 30 s, the timer restarts after every send (change or repeat); a change is sent immediately.
- **An output reports "On" (value not 0) and "Off" (value 0) separately.** An analog output has no Off command, so nothing is sent at 0 (a stopped wallbox never appears). A digital output sends its Off command once on the edge; the Off state is not repeated.
- Consequence for the design: silence of an analog signal means 0 only while the link is alive. The link is judged from repeating non-zero signals (a constant `heartbeat` VO, or any fresh analog value). A drop to 0 is noticed after the stale limit (3 x repeat, 90 s). Digital signals keep their last explicit value until the next edge.
- Docker bridge: the receiver sees the Docker gateway as peer, not the Miniserver address.
- Exported Config templates differ from the repo drafts (Info element, extra attributes, BOM); the repo templates now follow the export shape.
- Not yet verified: load on the Miniserver with all 40 repeating commands; delivery rate over days; behaviour after an Earnie restart.
- Token in the address: the receiver also accepts `http://host:8541/t/<token>` + command `/ehal/loxone/telemetry/...` (not verified yet whether Loxone joins an address path and a command that way; check with `scripts.pilot_vo_capture`).
