## Feature: HA-Loxone-Bridge-Builder (standalone HA ↔ Loxone bridge, YAML + XML codegen)

**Context:** Originally proposed as an Earnie/EHAL mapping feature, but reframed: this is a **standalone tool** for setting up bidirectional sync between Home Assistant and a Loxone Miniserver. It borrows patterns already proven in Earnie's Loxone integration (name-matching heuristics, the Virtual-HTTP write endpoint, structure scanning, the VO template shape) but has **no runtime dependency on Earnie/EHAL** — it targets any HA+Loxone setup, not just Earnie users.

### POC: EcoFlow Delta 3 (2026-10-14)

**Why now:** the bridge in `docs/einrichtung/ecoflow-delta3-loxone.md` (steps 5/6, variant A) lets the Miniserver write its own Virtual Inputs (`Delta3_Grid_ByPass`, `Delta3_P_ChargeLimit`) and mirrors them to HA via PyLoxone. The inputs get overwritten by a foreign value in between ([Backlog-Bugfixes.md](Backlog-Bugfixes.md), "Miniserver self-write of a Virtual Input is overwritten by HA"). The POC replaces that path with a single writer per value.

**Delivered (code + tests, live acceptance pending):**

- Location `tools/ha_loxone_bridge/` (zero imports from `ehal/`, `config.py`, `house_config/`, `integrations/`, … — enforced by a test). CLI: `python -m tools.ha_loxone_bridge --mapping <file.json> --out-dir <dir>`.
- **Mapping file = JSON**, not YAML: PyYAML is not a declared dependency of this repo. Example: `tools/ha_loxone_bridge/examples/delta3.mapping.json`. Validation fails loud (unknown keys, duplicate names / webhook ids, unsupported domains, `CHANGE_ME` webhook ids unless `--allow-placeholder`).
- **HA → Loxone** (numeric `sensor` / `number` / `input_number`): `rest_command` `GET http://<Miniserver>/jdev/sps/io/<VI>/<value>` (Basic Auth from `secrets.yaml`) + automation on state change, HA start and optional `time_pattern` refresh; guarded by `is_number`.
- **Derived sensors** (template, e.g. net ESS power = out − in) with an `availability` template instead of `float(0)` defaults, so a missing input never pushes a fake 0.
- **Loxone → HA via webhook** (no PyLoxone, no mirrored Virtual Input): generated Loxone `VirtualOut` template (Config export shape, BOM, `<v>` placeholder) pointing at `http://<HA>[:port]` (port omitted for 80; `CmdSep=";"`, CRLF — checked against the operator's Config export 2026-10-14), one command per point calling `/api/webhook/<id>?v=<v>`. Webhook automation (`GET`, `local_only` configurable, default `true`) for `number` / `input_number` (clamp + step rounding) and `switch` / `input_boolean` (digital VO, On `?v=1` / Off `?v=0`; `v ≥ 0.5` → on; **missing On counts as Off**: `mode: restart`, every On restarts an `off_after_seconds` timer, default 3 × `repeat_seconds` like Earnie's push freshness; on timeout → off + `system_log` warning; HA start trigger runs the timer right away). Writes only when the target differs from the current state, so the VO repeat (default 30 s, resync after HA restart) does not hammer the EcoFlow cloud.
- Output: one HA **package** file (`rest_command:` + `template:` + `automation:` with stable `id`s), `VO_HA_Bridge.xml`, German `Checkliste.md` (no webhook ids in it).
- Tests: `tests/test_ha_loxone_bridge.py` (parses the package as YAML, evaluates the generated Jinja expressions, checks the VO template shape).
- User doc (German): `docs/einrichtung/ha-loxone-bridge.md`.

**Open for the POC:**

- Live acceptance on the operator's HA + Miniserver (charge limit and bypass follow the Loxone logic for ≥ 24 h, no foreign values). Then close the bugfix item and rewrite steps 5/6 of the EcoFlow guide around the generator.
- ~~Verify digital VO repeat~~ **Verified 2026-10-14 (live, Delta 3 bypass via webhook):** a digital VO repeats "On" every Repeat interval (tested 10 s) but sends "Off" once on the edge only. A lost Off call (HA restarting) would leave the bypass on (battery island, no recharge). Hence HA treats a missing On as Off (operator decision 2026-10-14, same rule as Earnie's push inbox; a two-command On-only variant was rejected). `?v=` in the VO command combined with the device address works.
- ~~Live-test the off timer~~ **Verified 2026-10-14:** single `?v=1` from the browser while the Loxone output is Off → bypass on, back off after 30 s by the timer.
- Analog VO sends nothing at value 0 (no Off command). Irrelevant for the Delta 3 charge limit (min 100 W), relevant for other numeric points.

### Goal (v1 scope, after the POC)

A generator that scans both sides, proposes a point mapping, and outputs **ready-to-paste Home Assistant YAML** plus the Loxone Virtual Output template. Output is text/files only — nothing is written into a running HA instance or Miniserver.

### Non-Goals (v1)

- No import of `ehal/`, `config.py`, `house_config/`, or any other Earnie runtime module — must stay decoupled so it can be extracted into its own repo later without rework
- No direct write into Home Assistant (no Config API calls, no automation-registry writes) — the deliverable is copy-paste YAML, nothing more
- Non-numeric domains only as far as the POC needs them: `switch` / `input_boolean` for Loxone → HA. No covers / scenes / selects yet
- Not a persistently running service — a one-shot generator, rerun manually when the setup changes
- Not an Earnie onboarding feature. Version **2.6.b** / **2.6.e** propose HA entities for a fixed EHAL field list inside Earnie. This tool proposes arbitrary HA↔Loxone pairs and emits YAML. No shared matcher module.
- No PyLoxone dependency on any generated path (decision 2026-10-14, after the Delta 3 self-write bug).

### Direction split

- **Loxone → HA:** Loxone Virtual Output → HA webhook automation (POC). Reading Loxone values through the native Loxone integration in HA is **not** used for setpoints (mirrored Virtual Inputs caused the Delta 3 bug).
- **HA → Loxone:** for each confirmed mapping, a `rest_command:` entry plus a triggering `automation:` that writes the current HA entity value to Loxone via `GET http://<host>/jdev/sps/io/{name}/{value}` (Basic Auth) whenever the HA entity changes.

### Architecture sketch

- Decoupled location in this repo: `tools/ha_loxone_bridge/` — zero imports from `ehal/`, `config.py`, `house_config/` (POC: done)
- **Loxone-side scan (later):** parse `LoxAPP3.json`, extract numeric/analog controls (standalone reimplementation of the relevant parts of `integrations/loxone_structure.py` — no EHAL types)
- **HA-side scan (later):** `GET /api/states`, filter to supported domains — reuses the domain-filter idea from `integrations/ha_adapter.py::list_mappable_entities()`, reimplemented standalone
- **Matching (later):** generic name-similarity scorer (token overlap / Levenshtein on normalized names) — **not** Earnie's fixed EHAL `_HINTS` dictionary, since there is no fixed target vocabulary here; must work for arbitrary user naming conventions
- **Mapping file:** one JSON file as the source of truth (one row per point), human-editable, re-runnable/diffable so re-scans don't clobber confirmed rows (POC: hand-written, no scan)
- **Codegen:** HA package file + Loxone VO template + checklist (POC: done)

### Reuse table (pattern reuse, not code import)

| Concept | Earnie source | Adaptation for the standalone tool |
|---|---|---|
| Loxone HTTP write endpoint | `integrations/loxone_writes.py` (`/dev/sps/io/{name}/{value}`, HTTP Basic Auth) | Same URL/auth pattern (as `/jdev/…`, like the EcoFlow guide), reimplemented as the target of a generated HA `rest_command:`, not a Python call |
| Loxone VO template shape | `scripts/pilot_vo_template_gen.py`, `share/loxone/templates/VirtualOut/` | Same export structure (BOM, `Info`, attribute order, `<v>`), reimplemented in `tools/ha_loxone_bridge/loxone_xml.py` |
| Loxone structure scan | `integrations/loxone_structure.py` | Reimplemented standalone (LoxAPP3 parse only, no EHAL types, no probe-against-device-map) |
| HA entity scan / domain filter | `integrations/ha_adapter.py::list_mappable_entities()` | Reimplemented standalone |
| Name-matching heuristic idea | `integrations/loxone_ehal_mapping.py::heuristic_propose()` | Generalized to generic string-similarity instead of a fixed EHAL-field hint dictionary |
| HITL mapping review UX | `ui/ehal_loxone_mapping.py` / `ui/ehal_ha_mapping.py` | Pattern reused for a simple CLI review step (print proposals, accept/edit/reject) — no Streamlit/web dependency required for v1 |

### Open Questions

- CLI-only review for v1, or a minimal interactive prompt loop per proposed mapping row?
- Credentials: POC leaves `!secret` references (`loxone_user` / `loxone_pass`) for the user to fill in `secrets.yaml`; the tool never sees them. Keep that for v1?
- Webhook ids: POC requires them in the mapping file (generator refuses `CHANGE_ME`). Generate them on first run and write them back into the mapping instead?
- Packages only, or also per-automation paste fragments for HA setups without `packages:`?

### Deferred (explicitly out of scope, kept for later planning)

- Loxone-side plain Virtual Input templates (Loxone Config offers no template export for them; the checklist lists the inputs to create by hand)
- **Option: HA → Loxone as pull via Virtual HTTP Inputs** (like Earnie's `status.json`; discussed 2026-10-14, parked). Loxone cannot send the HA bearer token, so HA would have to publish an unauthenticated JSON, e.g. a file in `config/www/` (served at `/local/…`) written by an automation via `shell_command`, or a Node-RED endpoint. Pros: no Loxone credentials in HA, automatic resync after a Miniserver reboot, VI HTTP templates generatable (export shape known from `VI_Earnie_*_v2.xml`). Cons: values readable without auth, up to one poll interval latency, file-write workaround; check `/local/` caching first. Revisit if Loxone credentials in HA or the re-push after Miniserver reboots become a problem.
- Further non-numeric domains (covers, scenes, selects)
- Direct write into a running HA instance via its Config API
- Heartbeat / dead-man-fallback automation generation
- Extraction into its own standalone repository
