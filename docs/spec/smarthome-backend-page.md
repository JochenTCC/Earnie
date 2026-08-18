# Smarthome Backend (SB) page — development plan

**Status:** Drafted 2026-08-18, implemented same day (M1–M6 done). Backlog item: [`backlog/Backlog.md`](../../backlog/Backlog.md) § Version 2.5.0 ("Create 'Smarthome Backend' page (SB)"). See §5 for deviations from the original plan discovered during implementation.
**Related:** Detection design draft [`backlog/SB-Identification-Draft.md`](../../backlog/SB-Identification-Draft.md); EHAL spec [`docs/spec/ehal.md`](ehal.md); UI mode doc [`docs/ui/betriebsmodi.md`](../ui/betriebsmodi.md).

## 1. Goal

Today the EHAL backend (Loxone / Home Assistant / OpenEMS) is picked manually on the EHAL-Com page (`ui/ehal_connection.py:42` `render_backend_selector()`), and Loxone import lives on the Hauskonfigurator (HK) page (`ui/ehal_greenfield_import.py`). There is no discovery, no unified "which backend am I talking to" onboarding step, and no explicit UI state for "no backend configured yet".

The SB page becomes the single place where a `live_environment` install:
1. Detects candidate backends on the LAN (passive first, active scan only opt-in).
2. Lets the user pick one when several are found, or shows a hint (with a clear list of disabled functionality) when none are found.
3. Collects credentials and persists them.
4. Verifies the connection and, on success, unlocks the other live pages (Optimierer-Dienst, EHAL-Com, Analyse Verbrauch & Kosten — the `live_environment` set in `ui/navigation.py`).
5. Takes over Loxone import from the HK page; EHAL-Com loses its backend selector.

## 2. Architecture decisions

- **New readiness predicate**, next to the existing ones in `ui/setup_readiness.py` (pattern: `is_betrieb_unlocked()`, `needs_planning_onboarding()`): `is_sb_configured()` / `needs_sb_setup()`. Reads `ehal.backend` from `config.json` (via `runtime_store/ehal_setup.py:44` `active_ehal_backend()`) plus `hub_credentials_configured()` (same module, line 63). No new boolean flag is introduced — this repo's convention is to derive readiness from existing config state, not to store a separate "done" flag.
- **Nav gating**: `ui/navigation.py` gains a new `PageSpec` for the SB page, registered whenever `"live_environment" in enabled_mode_keys`, mirroring `_echtzeit_page_specs()` (lines 100–118). Unlike Optimierer-Dienst/EHAL-Com, the SB page must render *before* those are usable — the existing `is_setup_navigation_restricted()` mechanism (`ui/setup_readiness.py`, consumed at `ui/navigation.py:173`) is the natural hook to force-show SB and hide the other live pages until `is_sb_configured()` is true, the same way onboarding currently restricts nav to Hauskonfigurator + forced Daemon pages.
- **Detection module**: new `integrations/integration_scanner.py`, per `backlog/SB-Identification-Draft.md`. Pure network/detection logic, no Streamlit imports, so it can be unit-tested headless and reused outside the page (e.g. later CLI use) — same separation as `integrations/loxone_connectivity.py` / `integrations/loxone_structure.py`.
- **Session-state / wizard pattern**: reuse the flag set from `ui/ehal_greenfield_import.py:17-21` (`_SESSION_WIZARD`, `_SESSION_DISMISSED`, `_SESSION_LAST_REPORT`, `_SESSION_FLASH_OK`, `_SESSION_ACCESS`) for the SB page's own scan-result cache and post-rerun flash messages, instead of inventing a new pattern.
- **Credentials & persistence**: no new storage layer. Loxone keeps going through `.env` (`runtime_store/dotenv_io.py` `write_loxone_dotenv()`), HA/OpenEMS keep going through `config.json["ehal"]` (`ui/ehal_connection.py` `render_ha_connection_form()` / `render_openems_connection_form()`, persisted via `ui/house_config_io.py` `save_main_config`). The SB page becomes the caller of these existing forms; it does not reimplement them.
- **New dependency**: passive mDNS/SSDP discovery needs a library (e.g. `zeroconf` for mDNS; SSDP M-SEARCH can be hand-rolled over UDP without a new dependency). Add to `pyproject.toml` (canonical dependency file per `requirements.txt:1`), not `requirements.txt` directly.

## 3. Milestones

### M1 — `integration_scanner.py` (detection engine, no UI)

- Passive mDNS browse for `_home-assistant._tcp.local` (Home Assistant).
- Passive Loxone discovery: UDP broadcast (Miniserver discovery protocol) **and** SSDP M-SEARCH to `239.255.255.250:1900` — de-duplicate results from both methods by IP.
- Active OpenEMS port scan (8080 Apache Felix, 8085 UI websocket) with HTTP-signature verification against the Felix console — **opt-in only**, never runs as part of the default passive pass.
- A `scan_mode` parameter distinguishing:
  - `targeted`: only scan for the backend implied by install context (see M2 install-context detection) — e.g. LoxBerry plugin install → Loxone only, HA add-on install → Home Assistant only.
  - `full_passive`: mDNS + SSDP for all known backend types, no active scan.
  - `full_active`: `full_passive` plus the OpenEMS port scan (and, as fallback, a subnet scan per the draft's "Fallback: active subnet scan" row) — requires explicit user consent, never auto-triggered.
- Return type: list of `DiscoveredBackend(kind, host, port, extra)` — no side effects, no writes to config.
- Unit tests: `tests/test_integration_scanner.py`, mocking socket/mDNS responses (style reference: `tests/test_loxone_connectivity.py`, `tests/test_ehal_setup.py`). Cover: single match, multiple matches, zero matches, active-scan opt-out respected.
- Add `zeroconf` (or chosen mDNS lib) to `pyproject.toml`.

### M2 — Install-context detection + readiness predicate

- Helper to infer install context: LoxBerry plugin vs. Home Assistant add-on vs. plain/manual install. Check existing signals first (e.g. env vars already set by the HA add-on bootstrap — see `scripts/bootstrap_runtime.py` referenced in `backlog/Backlog.md:62` — and any LoxBerry-specific marker) before inventing a new one; this decides the `targeted` scan's backend filter from M1.
- `is_sb_configured()` / `needs_sb_setup()` in `ui/setup_readiness.py`, per §2.
- No UI yet — covered by plain unit tests alongside the other `setup_readiness` tests.

### M3 — SB page skeleton + navigation wiring

- New `ui/pages/page_smarthome_backend.py` with `render()`:
  - If `is_sb_configured()`: show current backend + status (read-only summary, link to reopen setup / re-scan).
  - If not configured: run the M1/M2 detection (`targeted` first, offer `full_passive` and, with explicit consent, `full_active` as escalation), then:
    - 0 results → hint block explaining the consequence (no automatic consumer/EHAL-binding import; live pages stay locked) — do **not** silently fall through, the user must see why other pages are missing.
    - 1 result → confirm-to-use flow.
    - >1 results → `st.selectbox`/list + explicit user confirmation (never auto-connect, per the draft's "Key Constraints").
  - After a backend is chosen: reuse `render_hub_credentials()` (`ui/setup_dotenv.py:124`) or the HA/OpenEMS forms from `ui/ehal_connection.py` (lines 60, 118) for credential entry — do not duplicate these forms.
  - On successful verify: persist via `persist_ehal_backend()` (`ui/ehal_connection.py:28`) / `write_loxone_dotenv()`, then rerun so `is_sb_configured()` flips and the other live pages unlock.
- Register the page in `ui/navigation.py` (new `PageSpec`, gated by `"live_environment"` same as `_echtzeit_page_specs()`), and make it the forced/only reachable live page while `not is_sb_configured()` via `is_setup_navigation_restricted()`.
- Add `docs/ui/betriebsmodi.md` update: SB joins the `live_environment` page list.

### M4 — HK page: move Loxone Import to SB

- Remove `render_greenfield_import_section()` call from `ui/house_config_profile_form.py:279-281`.
- Move the import trigger UI into the SB page's post-connection state (only shown once a backend is connected): for Loxone, call the same `_run_import()` / `run_greenfield_import()` chain (`ui/ehal_greenfield_import.py`, `integrations/loxone_greenfield_import.py`) — relocate, don't rewrite.
- Generalize the entry point so it can later switch on active backend ("automated import functionality") instead of being Loxone-only: e.g. `run_backend_import(backend)` dispatching to `run_greenfield_import` for Loxone today, with HA/OpenEMS import stubbed as "not yet available" (explicitly out of scope for this backlog item beyond Loxone, per the item text "switch to appropriate automated import functionality (Loxone / later HA & openEMS)").
- Update `page_loxone_debug.py:84-87` comment/reference (it currently documents that import lives on HK) and any onboarding copy that points at the HK page for Loxone import.

### M5 — EHAL-Com page: remove backend selector

- Remove `backend = render_backend_selector(key_prefix="ehal_com")` (`ui/pages/page_loxone_debug.py:69`) and the now-unused call site; read the active backend instead via `active_ehal_backend()` (`runtime_store/ehal_setup.py:44`), which SB has already set.
- Keep `_render_connection_section(backend)` (credentials re-entry / re-verify) — that stays on EHAL-Com, only the *selection* of which backend moves to SB.
- `render_backend_selector()` in `ui/ehal_connection.py:42-57` becomes dead code once no caller remains — delete it (and `_BACKEND_OPTIONS` if unused elsewhere) rather than leaving it unreferenced.

### M6 — Tests

- `tests/apptest/scripts/run_page_smarthome_backend.py` + `tests/apptest/test_page_smarthome_backend_apptest.py`, following the `page_loxone_debug` pattern (`tests/apptest/test_page_loxone_debug_apptest.py`): render-without-exception, "no backend found" hint text, credential form appears after a mock scan result.
- Update `tests/apptest/test_page_loxone_debug_apptest.py` to assert the backend selector is gone.
- Update/extend HK apptest to assert the Loxone-Import section no longer renders there.
- `tests/test_integration_scanner.py` (M1) and `setup_readiness` unit tests for `is_sb_configured()` (M2).

## 4. Sequencing & risk notes

- M1 and M2 are independent of Streamlit and can be built/tested in isolation first; M3–M5 are UI wiring on top of them and should follow in that order since M5 depends on M3 having replaced the selector's role.
- Active port scanning (OpenEMS) and subnet-scan fallback can trigger firewall/IDS alerts (explicitly called out in the draft, e.g. UniFi setups) — keep these behind an explicit extra confirmation step distinct from the initial passive scan consent, and log what was scanned for support/debugging.
- OpenEMS non-standard ports remain an open question from the draft (`backlog/SB-Identification-Draft.md:26`) — M1 should default to the standard 8080/8085 pair and leave a documented TODO rather than building configurable-port scanning now (no backlog item currently asks for it).
- The "later HA & openEMS" automated import in M4 is explicitly scoped out beyond a stub — do not build HA/OpenEMS import logic under this item; track it as a new backlog entry once SB/Loxone ships.

## 5. Implementation notes (deviations from the plan above)

- **Loxone UDP broadcast dropped.** Verified live against a real Miniserver-Gen2 and a real Home Assistant 2026.8 instance on the user's LAN: standard SSDP M-SEARCH (`239.255.255.250:1900`) gets a genuine Loxone response (`SERVER: Loxone Miniserver …`), while the proprietary "LoxLIVE" UDP-broadcast protocol on port 7070 (guessed payloads: empty, `\x00`, `LoxLIVE`, `eloxone`, `go`) got no response at all. `integrations/integration_scanner.py` therefore implements **SSDP-only** for Loxone passive discovery — this alone satisfies the draft's SSDP row, and the UDP-broadcast row is dropped rather than shipped unverified. mDNS for Home Assistant (`_home-assistant._tcp.local.`) was verified the same way and works as documented.
- **Install-context signal didn't exist — added one.** Neither the LoxBerry plugin compose nor the HA add-on `run.sh` exported anything distinguishing "how was Earnie installed" before this change. Added `EARNIE_INSTALL_CONTEXT` (`loxberry` / `homeassistant_addon`, read via `runtime_store/install_context.py`), set in `packaging/loxberry/data/docker/docker-compose.yml`, `docker/compose/loxberry-alpha.yml`, `docker/compose/loxberry_productive.yml`, and `packaging/homeassistant-addon/earnie/run.sh`.
- **The pre-nav blocking setup gate now *is* the SB page.** Not called out in the original M3 plan: `ui/setup_dotenv.py::render_ehal_setup_page()` — a full-screen gate in `app.py` shown once planning is complete and no backend is configured (`needs_loxone_setup()`), rendered *before* `st.navigation` exists — used its own hand-rolled `render_backend_selector()` + credentials form. Rather than keep two separate "pick a backend" implementations, `render_ehal_setup_page()` now just calls `page_smarthome_backend.render()`. This is why M5's selector removal and this blocking screen had to be resolved together: the selector's last remaining caller besides EHAL-Com was this gate.
- **Optimierer-Dienst/EHAL-Com hiding is scoped to onboarding only**, not a blanket "hide until SB configured" rule — a deliberate, narrower interpretation of the backlog's "do not enable EHAL-com and other live-environment related pages" than a literal reading suggests. `ui/navigation.py::_echtzeit_page_specs()` gained an `include_daemon_pages` flag, applied only when `force_echtzeit` is true (the greenfield-onboarding forced-nav path in `_restricted_page_specs`).
  - Outside onboarding, this mostly doesn't matter in practice: the blocking pre-nav gate (`needs_loxone_setup()`) forces backend setup before nav renders for the common case.
  - **Known residual gap:** `runtime_store/dotenv_io.py::loxone_setup_deferred()` intentionally stays "deferred" (gate does **not** block) for a *mature* config (`needs_planning_onboarding()` false, e.g. non-empty `flexible_consumers`) that has **never** had any backend credentials configured — confirmed by the existing, deliberate test `tests/test_dotenv_io.py::test_require_loxone_credentials_for_prod_without_onboarding`. In that narrow state, Optimierer-Dienst/EHAL-Com stay reachable without SB ever being configured. Closing this fully would mean making daemon-page visibility conditional on `is_sb_configured()` unconditionally (not just under `force_echtzeit`), which ripples into ~9 test files — several of which currently pass only because real Loxone credentials happen to be loaded from a developer's local `.env` (`tests/conftest.py`'s `load_dotenv`), not because they assert the right thing. Fixing that properly is a separate, larger test-hygiene pass, not part of this item's scope; flagged here rather than silently left undiscoverable.
- **`ui/setup_dotenv.py::render_hub_credentials()` and `ui/ehal_connection.py::render_backend_selector()` deleted**, not deprecated — both became fully unreferenced once EHAL-Com and the blocking gate stopped calling them (confirmed via repo-wide grep before deletion).
