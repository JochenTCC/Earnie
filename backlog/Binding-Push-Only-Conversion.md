# Push-only migration of the Loxone binding — handover and procedure

**Purpose:** entry point for a new session (Cursor). Describes the starting point, the decisions, the pilot findings and the procedure for switching the binding **entity by entity** from "read Loxone Merker (poll)" to "Loxone sends via Virtual Output (push)". **State: 2026-10-07. Nothing of the push-only read path has been built yet** — the pilot is observation only.

(The file name is German for historical reasons; the content is English because backlog files are English.)

**Starter prompt (paste into the new chat):**

> Read `backlog/Binding-Push-Only-Umstellung.md` (and the project rules in `.cursor/rules/*.mdc`; `CLAUDE.md` summarises the essentials). We migrate the Loxone binding to push-only entity by entity (pilot branch `spike/vo-push-pilot`). Start with section 8 (work packages) and ask me about the open decisions in section 9 before you change the read path.

---

## 1. Goal and context

- **Today:** Earnie reads every Loxone signal one by one with `GET /jdev/sps/io/<Merker name>` (polling). The mapping "EHAL field → Merker name" is stored in `ehal_bindings`. A new field needs changes in about 15 places, and the naming convention is not consistent.
- **Goal (epic `Binding`, backlog 2.7.n):** freeze the identifiers (qualified EHAL IDs); Loxone sends its values through a **Virtual Output** with the **EHAL ID in the path** to Earnie. Earnie then no longer needs Merker names to read.
- **Decision for this migration:** **push-only** (no permanent poll fallback), **entity by entity**, Earnie runs in **loud mode** (setpoints are written!). Writing stays unchanged (direct `/dev/sps/io/<name>/<value>` plus the `status.json` mirror).
- Related documents: `backlog/EHAL-Binding-UX-Draft.md` (analysis, §9 slice 2.7.n, §10 pilot findings), `backlog/Binding-Walkthrough-Ist.md` / `-Soll.md` (read/write path, German), backlog item **2.7.n** and epic **Binding** in `backlog/Backlog.md`.

## 2. State of repositories and environments

| What | State |
|---|---|
| Pilot branch | `spike/vo-push-pilot` in the main folder `…\Energy-Optimizer`. Commit `054ab475` "spike(vo-push): pilot telemetry inbox, qualified IDs, VO <v> templates (v2.7.0-dev.20)" on `main@0006af86` contains the whole pilot (see section 5). A later commit on the same branch adds the `/t/<token>` address prefix and this document. Uncommitted in the working tree: only `version.py` (dev.21, the maintainer's own bump). |
| Fix branch | `fix/status-json-powerstation-keys`, commit `b5a658d2`, separate worktree `…\Energy-Optimizer-statusfix`. **Not merged** and **not part of** the pilot branch. Fixes: powerstation values overwrote the house battery's flat keys in `status.json` (now `ess.<id>.<field>`). Possible merge conflicts in `backlog/Backlog-Bugfixes.md` (both branches change it). |
| NAS "alpha" | `192.168.178.35`, daemon port **8541** (`8501` is Streamlit!). Config: `P:\earnie-alpha\earnie_env\config`, runtime: `P:\earnie-alpha\earnie_env\runtime` (`loxone_push_inbox.json`, `earnie.log`). Runs in **loud mode**. Pilot receiver active; the token is in the instance's `.env` (`EARNIE_PILOT_PUSH_TOKEN`, **not in this file**). Check whether the container from `054ab475` already runs there (visible when `consumer.` / `heatpump.` / `pool.` IDs arrive). |
| Greenfield (dev PC) | Host port 8542 → container 8541; placeholder Loxone, no poll comparison. |
| Loxone | VO templates are in `Documents\Loxone\Loxone Config\Templates\VirtualOut\` (8 files `VO_Pilot_*.xml`) and as a copy with `Pilot-VO-Signalliste.csv` in `Documents\Loxone\pilot_vo_alpha\`. All 40 commands (39 signals + heartbeat) are inserted and wired; the inbox receives 40 signals or assumes them to be 0. Open: check the **Off** command of the digital signals, wire the heartbeat constant. |
| Old stash | `stash@{0}: wip before research/live-price-prognosis` (belongs to the repo, do not touch; an accidental `git stash pop` once applied it in a worktree, cleaned up). |

## 3. What the pilot showed about Loxone

| Observation | Consequence |
|---|---|
| A VO command is a plain `GET` from the Miniserver, **without headers**. | The token can only travel as `?t=` in the command (or in the address, see decision 8). |
| The value placeholder in a VO command is **`<v>`** (`<v.1>` = one decimal); `\v` is sent as the control character 0x0B (`\v` is only valid in a Virtual **Input**). `<v>` yields a decimal point and three decimals. | All telemetry templates use `<v>`. |
| Repeat runs exactly every 30 s, also with an unchanged value; the timer restarts after every send; changes are sent immediately. | Freshness criterion 3 × 30 s = 90 s. |
| An output reports "On" (value ≠ 0) and "Off" (value = 0) separately. **Analog: no Off command** → nothing is sent at 0. **Digital:** Off is sent once on the edge, **not repeated**. | Silence of an analog signal = 0, **provided the link is alive**. Digital values hold until the next edge. A drop to 0 is noticed only after 90 s. |
| The Docker receiver sees the Docker gateway (`172.28.0.1`) as peer, not the Miniserver. | The peer column is only a hint. |
| Templates exported by Config have a fixed structure (`Info` element, `HintText`, `CmdAnswer`, `SourceVal…`, BOM, tabs). | Repo templates and the generator follow this structure. |
| `LoxAPP3.json` contains visible controls only, no VO/VI commands and no description fields (only the `hasControlNotes` flag). | EHAL IDs cannot be read from the structure file. Whether the notes text of the meters is exported anywhere is open (test later: read it fresh). |

## 4. Decisions (binding)

- **Qualified EHAL IDs** `<namespace>.<Kennung>.<field>`, plant without namespace: `ess` (battery), `evcs` (wallbox), `ev` (vehicle), `inv` (inverter, reserved), `heatpump` (`thermal_annual`), `pool` (`thermal_rc` and the entity `pool_filter`), `consumer` (all others). `flex.` stays only as a readable alias for stored bindings. Storage unchanged (no migration).
- `sens_evcs_connected` is valid in both EV namespaces and is **not** renamed.
- New name suggestions **always** contain the Kennung. The **Kennung is editable** (rename only with a dry run; alias table if spike P0c requires it).
- The pilot is observational: nothing from the inbox feeds the optimizer yet. This document describes the step that changes that.
- Bindings are **not** touched: switching is a source decision per entity, not a data model change (bindings keep the Merker names for rollback and for the name ↔ EHAL ID mapping).

## 5. Code map (all in commit `054ab475` unless noted)

| File | Role |
|---|---|
| `ehal/qualified_ids.py` | Namespaces, consumer → namespace mapping, `is_digital_id`, `DIGITAL_KINDS`. |
| `ehal/push_signals.py` | `Signal`, `read_signals_from_docs(house, components)` (bound read fields → qualified ID, VO title `Push_…`), `heartbeat_signal()`. |
| `runtime_store/loxone_push_inbox.py` | Inbox (`runtime/loxone_push_inbox.json`), `record_push`, `link_alive`, `derive_state` (OK / 0 held / 0 assumed / digital held / unknown …), `expected_repeat_s` (`EARNIE_PILOT_PUSH_REPEAT_S`, default 30). |
| `integrations/loxone_request_http.py` | Daemon HTTP on 8541: endpoint `GET /ehal/loxone/telemetry/<ID>/<value>`; **off** while `EARNIE_PILOT_PUSH_TOKEN` is unset; the token comes as header `X-Earnie-Token`, as **address prefix** `/t/<token>` before the path (device address `http://host:8541/t/<token>`, command without `?t=`; added in the later commit) or as `?t=` (checked in this order, the first one present must match); accepts only `sens_` / `get_` IDs and `heartbeat`. |
| `ui/loxone_push_inbox_ui.py` | EHAL-Com section "Push-Inbox": derived state, link, expected signals from the bindings, comparison with the poll value. |
| `scripts/pilot_vo_template_gen.py` | Generates `VO_Pilot_*.xml` from the bindings of a config (`--config-dir`, `--host`, `--port`, `--env-file` / placeholder token, `--out-dir`). Digital: On `…/1`, Off `…/0`; analog: no Off. Option `--token-in-address` puts the token into the VO device address instead of every command (later commit). |
| `scripts/pilot_vo_capture.py` | Small listener that shows what a VO really sends. |
| `share/loxone/templates/VirtualIn|VirtualOut/*.xml` | Repo templates in the Config export structure. |
| Tests | `tests/test_qualified_ids.py`, `test_loxone_push_inbox.py`, `test_loxone_push_inbox_ui.py`, `test_pilot_vo_template_gen.py`, `test_loxone_vo_template_shape.py`. |

Today's read path (target of the migration): `integrations/loxone_client.py::fetch_loxone_generic_value` (one value per call), `integrations/loxone_adapter.py::LoxoneAdapter.read_telemetry` (plant), `ehal_live.read_ess_soc_by_id` (SoC per battery), `integrations/loxone_live_power.py` (consumer meters, EV), heat/pool readings. Details: `backlog/Binding-Walkthrough-Ist.md`.

## 6. Target picture: push-only per entity

**Source per entity** (switch `poll | push`, default `poll`). For an entity set to `push`:

1. Every bound `sens_*` / `get_*` quantity comes from the inbox, no longer from the poll. The Merker name ↔ qualified ID mapping comes from the binding list (`read_signals_from_docs`: `old_name` ↔ `ehal_id`).
2. **Not pushable**, therefore still poll or unchanged: `get_evcs_ready_by_time` (AlarmClock, `SpecialState10`), meter energy via `/all` (`sens_*_energy`).
3. **Freshness:** a value is valid if younger than 3 × repeat interval (90 s). After a start the inbox knows nothing for up to 30 s → **start-up window** (proposal: wait up to 40 s for the heartbeat before the first run reads).
4. **Zero rule (proposal, to be confirmed)**, only for quantities where 0 is plausible:

   | Field kind | Silence while the link is alive | Silence while the link is dead |
   |---|---|---|
   | Powers (`sens_*_power*`, `sens_power_act`, `sens_evcs_active_power`, `sens_grid_power_active`, `sens_pv_production_active`) | 0 | read error |
   | Activity / digital (`sens_heating_active`, `sens_filter_active`, `sens_absent_mode`, `sens_evcs_connected`) | last value holds until the edge; never sent = 0 | read error |
   | SoC, capacity, limits (`get_*`), temperatures | **do not** assume 0 → read error | read error |

5. **Read errors** behave as today: required fields (`sens_ess_soc`, grid, PV, battery power) → abort the run and log (`LoxoneAdapterError`), optional fields are omitted. The dead-man fallback in the Loxone program stays unchanged.
6. **Link** = a fresh repeating non-zero signal (heartbeat or an analog measurement). Heartbeat VO: `Push_Earnie_Heartbeat`, a non-zero constant at the input.
7. **Spot check** also in push-only operation (proposal): every 15 minutes one single poll, only for comparison (log on deviation), never for decisions. Otherwise there is no cross-check after switching.
8. **Rollback at any time:** set the entity back to `poll`. The bindings (Merker names) stay.

## 7. Procedure entity by entity

**Order by rising risk** (signal counts from `Pilot-VO-Signalliste.csv`):

| Stage | Entity | Signals | Risk | Why here |
|---|---|---|---|---|
| 1 | Consumer meters (`consumer.*`) | 5 | low | the optimizer falls back to its setpoints when a value is missing; only chart and base-load effect |
| 2 | Heat pump power (`heatpump.*.sens_power_act`) | 1 | low | like stage 1 |
| 3 | Plant edge: `sens_temperature_outside`, `sens_absent_mode`, `get_grid_export_power_limit` | 3 | low–medium | outside temperature feeds the thermal models |
| 4 | Pool and filter (`pool.*`) | 9 | medium | thermal decisions, digital fields |
| 5 | Heat pump temperatures (`heatpump.*.sens_temperature_*`) | 2 | medium | RC state |
| 6 | EV (`evcs.*`, `ev.*`) | 7 | medium–high | charging decisions for the vehicle |
| 7 | Battery Delta 3 (`ess.ecoflow_delta_3.*`) | 4 | high | powerstation planning, SoC per battery |
| 8 | Battery 15 kWh (`ess.15_kwh_speicher.*`) | 6 | high | main storage |
| 9 | Plant grid and PV (`sens_grid_power_active`, `sens_pv_production_active`) | 2 | highest | required fields, start and live state |

(The entity names come from the NAS alpha config; adapt for another config.)

**Per-stage checklist:**

1. **Preconditions:** all VOs of the stage wired; the inbox shows `OK` or a plausible `0 assumed` for **all** signals of the stage for **at least 48 h**; the "Abweichung" column against the poll consistently `gleich` (except known dead time); no `Unbekannt` states; link `aktiv`; heartbeat runs; digital signals have On and Off set.
2. **Cross-check period:** for stages 7 to 9 additionally test a daemon restart (values back within ≤ 40 s) and a link loss (briefly disconnect the Miniserver, check the behaviour from section 6).
3. **Switch:** set the entity to `push` (location of the switch: see section 9, decision 2); restart the daemon if the switch is only read at start.
4. **Check (30–60 min after switching):** log for read errors and aborts; EHAL-Com live read (value source `Push` visible); compare setpoints and decisions with the previous day; spot-check log.
5. **Observe:** at least 24 h before the next stage starts. For stages 7 to 9 over a day and a night (PV = 0 at night, battery idle).
6. **Roll back if any of these applies:** read errors accumulate, the link breaks, values deviate from the spot check, setpoints look implausible → entity back to `poll`, analyse the cause in the inbox, **only then** continue.

**Completion:** when all stages run, remove the Merker names from the bindings and tackle the generic read/write path (2.7.n-5/-6, field registry in the role JSON). That is a separate step.

## 8. Work packages (still to build)

Prerequisite before any change to the read path: **characterization tests** (backlog 2.7.n-4) as a safety net — pin today's read behaviour (conversions kW → W, clamps, required / optional fields, error cases). Run tests only through the wrapper: `.venv\Scripts\python.exe -m scripts.run_pytest …`.

| WP | Content | Files / notes |
|---|---|---|
| WP1 | **Read API of the inbox inside the daemon:** `read_push_value(ehal_id)` → (value, state) with an in-process cache (the listener and the read path run in the same process `main.py`; the JSON file is only for the UI) | `runtime_store/loxone_push_inbox.py` |
| WP2 | **Source switch per entity** (`poll` / `push`), default `poll`; mapping entity → IDs; Merker name → ID reverse list | new small config layer; location see section 9 |
| WP3 | **Interception in the read path**: for entities on `push` take the WP1 value instead of HTTP; **no** change to the adapters if the reverse list hooks into `fetch_loxone_generic_value` | `integrations/loxone_client.py`; exclude AlarmClock and `/all` reads |
| WP4 | **Zero rule per field kind** (table in section 6) + a test per row; read-error semantics (required field → abort) | new pure function next to `derive_state`; tests like `test_loxone_push_inbox.py` |
| WP5 | **Start-up window and link:** wait for the heartbeat before the first run (upper bound), log lines on link loss, status in EHAL-Com | `main.py` loop, `ui/loxone_push_inbox_ui.py` |
| WP6 | **Spot-check comparison** (poll only for comparison, log) | read layer + log |
| WP7 | **EHAL-Com:** show the source per entity and (later) switch it; live read shows "source: push/poll" | `ui/loxone_debug*.py`, mapping pages |
| WP8 | **Docs:** `docs/ui/ehal-com.md`, `docs/referenz/loxone-signals.md` (German, `german-user-docs.mdc`); backlog: a separate item for the push-only read path (follow-ups are separate items, not new epic phases); epic phases in `roadmap-nomenclature.mdc` if needed | see the rules in `.cursor/rules/` |
| WP9 | **Delivery:** build the container from the branch, roll out on NAS alpha; merge the fix branch before or together with it (otherwise the `status.json` overwrite effect stays) | the pre-commit hook runs the full suite (7–8 min); change the version only after approval |

## 9. Open decisions (clarify before building)

1. **Confirm the zero rule** (table in section 6; above all: may temperatures and limits count as read errors on silence?).
2. **Where does the source switch live?** Proposal: `config.json` → `ehal.loxone_push.entities` (list of entity IDs, e.g. `plant`, `battery:ecoflow_delta_3`, `consumer:trockner`), later a switch in EHAL-Com. Alternative: `runtime/local_settings.json` (changeable without restart, but not versioned).
3. **Push-only really without any fallback?** For required fields (SoC, grid, PV, battery power) the run aborts on silence. Alternative: last known value for up to N minutes. The request was push-only; the safety nets (dead man in Loxone, abort on read error) are the substitute.
4. **Spot check** in push-only operation: yes / no, interval.
5. **Start-up window:** upper bound (proposal 40 s) and behaviour afterwards.
6. **Merge the fix branch first?** And how the two branches (`054ab475` and later, `b5a658d2`) are merged into `main`.
7. **Digital commands:** check whether Config took over the Off command from the template (otherwise add it by hand).
8. **Token in the address instead of in every command** (`--token-in-address`; the receiver supports it, see `integrations/loxone_request_http.py::split_token_prefix`): **first check whether Loxone joins address and command that way.** Test with the capture script: `python -m scripts.pilot_vo_capture --port 8599`, a VO with address `http://<PC-IP>:8599/t/abc` and command `/ehal/loxone/telemetry/sens_ess_soc/<v>`; the capture must show `/t/abc/ehal/loxone/telemetry/sens_ess_soc/<value>`. If the path part of the address does not come along, `?t=` stays in the command (still supported).

## 10. Risks

- **Dead time on a drop to 0:** analog signals (wallbox, battery idle, PV at night) are recognised as 0 only after 90 s; until then the optimizer sees the last value. Can be shortened (factor < 3) at the cost of false zeros when a repeat is late.
- **Loud mode:** errors in the read path act on real setpoints. Hence characterization tests first, small stages, rollback per entity.
- **Miniserver load:** 40 commands × 30 s ≈ 1.3 requests/s permanently; long-term behaviour not measured.
- **Daemon restart:** values are missing for up to 30 s; hence the start-up window.
- **Token:** it sits in clear text in the VO templates and in the Config program (LAN only). **The current pilot token is compromised**: it appears in a chat and (as a test value) in commit `054ab475` on `spike/vo-push-pilot`. In the pilot this is uncritical (observation only); **it must be replaced before push-only operation**, because then anyone on the LAN with the token can feed values into the optimization. Set a new token in the instance's `.env`, regenerate the templates (`--env-file`) and replace it in Config — with `--token-in-address` only in the 8 VO device addresses instead of all 40 commands (see section 9, decision 8). **Do not push** the branch while `054ab475` is unchanged in it (or clean the history first). Never write a real token into tests or docs.
- **Digital signals:** the On repeat is not verified; Off only as an edge.

## 11. Working notes for the new session

- Project rules: `.cursor/rules/*.mdc` (in Cursor: reply in English, `english-chat.mdc`; backlog and specs in English; user docs in German); `CLAUDE.md` summarises the essentials. Never change `version.py` without explicit approval.
- Windows PowerShell 5.x: no `&&` / `||` (`powershell-shell.mdc`). Set the UTF-8 environment (`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`) and run tests only through the wrapper (`scripts.run_pytest`). The pre-commit hook runs the full suite in 7–8 minutes; when committing from a git worktree without its own `.venv`, put the path of the existing venv in front of `PATH`.
- Prepare fixes for `main` in a **worktree** (`git worktree add ../<name> -b <branch> main`), not in the pilot branch.
- **Never `git stash pop` without a preceding `stash push`** (an old stash is in the repo).
- Template generator (example, placeholder token):
  `python -m scripts.pilot_vo_template_gen --config-dir <earnie_env\config> --host <Earnie IP> --port 8541 --out-dir <folder>` (with `--env-file <.env>` the real token is inserted; do not commit the output).
- Accesses to the NAS share of the alpha instance (inbox, log, config) have been **read-only** so far; the Miniserver itself was never contacted by the assistant sessions. Avoid fetching `status.json` by hand: it overwrites the "last call from the Miniserver" display.
- The file `capture.jsonl` in the repo root is a pilot recording (do not commit it); it may be deleted.
