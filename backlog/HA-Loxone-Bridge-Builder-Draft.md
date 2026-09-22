## Feature: HA-Loxone-Bridge-Builder (standalone numeric-value bridge, YAML codegen)

**Context:** Originally proposed as an Earnie/EHAL mapping feature, but reframed: this is a **standalone tool** for setting up bidirectional numeric-value sync between Home Assistant and a Loxone Miniserver. It borrows patterns already proven in Earnie's Loxone integration (name-matching heuristics, the Virtual-HTTP write endpoint, structure scanning) but has **no runtime dependency on Earnie/EHAL** — it targets any HA+Loxone setup, not just Earnie users.

### Goal (v1 scope, as decided)

A generator that scans both sides, proposes a numeric point mapping, and outputs **ready-to-paste Home Assistant YAML** (`rest_command:` + `automation:`) for the HA → Loxone write direction. Output is text/files only — nothing is written into a running HA instance.

### Non-Goals (v1)

- No import of `ehal/`, `config.py`, `house_config/`, or any other Earnie runtime module — must stay decoupled so it can be extracted into its own repo later without rework
- No direct write into Home Assistant (no Config API calls, no automation-registry writes) — the deliverable is copy-paste YAML, nothing more
- No non-numeric domains (switches/covers/scenes/selects) — numeric points only (sensors, `number`, `input_number` on the HA side; analog Merker/Virtual Inputs on the Loxone side)
- No Loxone-side Virtual-In/Out XML generation yet — deferred to a later phase
- Not a persistently running service — a one-shot generator, rerun manually when the setup changes
- Not an Earnie onboarding feature. Version **2.6.b** / **2.6.e** propose HA entities for a fixed EHAL field list inside Earnie. This tool proposes arbitrary numeric HA↔Loxone pairs and emits YAML. No shared matcher module.

### Direction split

- **Loxone → HA:** out of scope for codegen. The native Loxone integration in HA already covers this read direction; the tool only needs the Loxone-side numeric point names as input for the matching step.
- **HA → Loxone:** the actual deliverable. For each confirmed mapping, generate a `rest_command:` entry plus a triggering `automation:` that writes the current HA entity value to Loxone via `GET http://<host>/dev/sps/io/{name}/{value}` (Basic Auth) whenever the HA entity changes.

### Architecture sketch

- New, decoupled location in this repo: `tools/ha_loxone_bridge/` — zero imports from `ehal/`, `config.py`, `house_config/`
- **Loxone-side scan:** parse `LoxAPP3.json`, extract numeric/analog controls (standalone reimplementation of the relevant parts of `integrations/loxone_structure.py` — no EHAL types)
- **HA-side scan:** `GET /api/states`, filter to numeric-ish domains (`sensor`, `number`, `input_number`) — reuses the domain-filter idea from `integrations/ha_adapter.py::list_mappable_entities()`, reimplemented standalone
- **Matching:** generic name-similarity scorer (token overlap / Levenshtein on normalized names) — **not** Earnie's fixed EHAL `_HINTS` dictionary, since there is no fixed target vocabulary here; must work for arbitrary user naming conventions
- **Mapping file:** one YAML file as the source of truth (Loxone name ↔ HA entity_id, per row), human-editable, re-runnable/diffable so re-scans don't clobber confirmed rows
- **Codegen:** template-based rendering of the mapping file into one `rest_command:` + `automation:` YAML block per row, bundled as a single package-style file meant to be pasted into `configuration.yaml` (or a HA `packages/` file)

### Reuse table (pattern reuse, not code import)

| Concept | Earnie source | Adaptation for the standalone tool |
|---|---|---|
| Loxone HTTP write endpoint | `integrations/loxone_writes.py` (`/dev/sps/io/{name}/{value}`, HTTP Basic Auth) | Same URL/auth pattern, reimplemented as the target of a generated HA `rest_command:`, not a Python call |
| Loxone structure scan | `integrations/loxone_structure.py` | Reimplemented standalone (LoxAPP3 parse only, no EHAL types, no probe-against-device-map) |
| HA entity scan / domain filter | `integrations/ha_adapter.py::list_mappable_entities()` | Reimplemented standalone, filtered to numeric domains only |
| Name-matching heuristic idea | `integrations/loxone_ehal_mapping.py::heuristic_propose()` | Generalized to generic string-similarity instead of a fixed EHAL-field hint dictionary |
| HITL mapping review UX | `ui/ehal_loxone_mapping.py` / `ui/ehal_ha_mapping.py` | Pattern reused for a simple CLI review step (print proposals, accept/edit/reject) — no Streamlit/web dependency required for v1 |

### Open Questions

- CLI-only review for v1, or a minimal interactive prompt loop per proposed mapping row?
- How to handle Loxone Basic-Auth credentials in the generated YAML — leave a `secrets.yaml` placeholder for the user to fill in, or prompt for them and inject directly (never persisted by the tool either way)?
- Confirm target repo location `tools/ha_loxone_bridge/` vs. another decoupled top-level folder

### Deferred (explicitly out of scope for this draft, kept for later planning)

- Loxone-side Virtual-In/Out XML template generation (auto-filled, ready to import into Loxone Config)
- Non-numeric domains (switches, covers, scenes, selects)
- Direct write into a running HA instance via its Config API
- Heartbeat / dead-man-fallback automation generation
- Extraction into its own standalone repository
