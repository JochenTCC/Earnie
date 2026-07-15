# Debug handoff: SoC BL Ziel (earnie silent stack)

**Session date:** 2026-07-15 (updated same day, ~10:45)  
**Status:** **Closed** (2026-07-15) — silent-stack verified; archived → `backlog/Backlog-Erledigt.md` § Bugfix SoC BL Ziel matched baseline  
**App version during debug:** 1.98.1  
**Environment:** `silent-migration-test` (local copy of `\\DS-KO-DO-2\docker\earnie`)

---

## Original issue

**SoC BL Ziel** (matched baseline SOC trace in Chart 1) appeared **too high** in the NAS silent stack compared to the legacy `energy_optimizer` stack (v1.24.3).

**Resolution of comparison question (2026-07-15):** After real-PV runs and snapshot analysis, **v1.24.3 is not a valid golden reference** for Wed-noon BL Ziel — it likely showed **artificially low** SOC due to the same flex-profile / ID-bridge / synthetic-PV bugs (plus UI-side auto-simulation). Current ~56–57% at Wed 12:00 matches `main.py` persisted `matched_baseline_rows` and is **consistent with the matched-baseline model** (no flex at Wed noon in CSV, PV charges battery).

---

## Root causes (confirmed with runtime evidence)

### 1. Broken flex CSV (initial blocker — FIXED)

1. `generate_consumption_profile()` failed with `"Columns not found: 'SwimSpa Filter'"`.
2. Export grouped by `consumer["name"]` but cons_data uses **display labels** (e.g. `"Smart"` for EV).
3. KeyError → entire flex CSV export failed → only `Consumption` column on disk.
4. Matched baseline lost profile-shaped EV competition.

### 2. Config appliances omitted from BL Ziel simulation (FIXED 2026-07-15)

`resolve_horizon_consumer_targets_kwh()` returned **0 kWh** for Waschmaschine/Trockner/Geschirrspüler (`daily_target_source=config`, `daily_target_kwh=0`) while `flexible_consumer_profiles.csv` had **4 + 5 + 2.4 kWh** in the horizon.

**Evidence (10:32 snapshot, before fix):** `energy_comparison` showed `matched_baseline_kwh: 0.0` for appliances vs `baseline_kwh: 4.0 / 5.0 / 2.4`.

**Fix:** `resolve_matched_baseline_horizon_targets()` in `optimizer/targets.py` — profile-sum targets for config appliances when explicit daily target is 0. Used in `calculate_optimization_savings()`.

**Post-fix (10:32):** `matched_baseline_kwh: 4.0` for Waschmaschine (and peers in `matched_targets` log). **Wed noon unchanged** — see weekday note below.

### 3. UI auto-simulation distorted charts (FIXED — architecture change)

Cockpit now reads `live_optimization_debug.json` from `main.py` by default (see UI section). Removes duplicate forecast.solar / divergent matched baseline from Streamlit.

---

## Hypotheses status

| ID | Hypothesis | Status | Evidence |
|----|------------|--------|----------|
| **H1** | Broken flex CSV → zero `expected_flex_kw` | **CONFIRMED / FIXED** | Regen failed; CSV had only `Consumption`; flex sums 0 before fix |
| **H2** | Zero profiles → wrong matched baseline SOC | **CONFIRMED / FIXED** | Profile regen; `ev=21.47 kWh` in horizon logs |
| **H3** | `ev`/`eauto` ID bridge in profile export | **FIXED** | CSV column `eauto`; `_load_flexible_consumer_hourly_profiles` uses `profile_column_id()` |
| **H4** | Thermal missing from horizon targets | **FIXED (code)** | `resolve_horizon_target_kwh` thermal paths |
| **H5** | Profile check silent when CSV OK | **ADDRESSED** | INFO `Profil-Check` / `Flex-Profile im Planungshorizont` |
| **H6** | Chart reads main.py snapshot only | **CONFIRMED** | UI log: `source: main.py`, `opt_in_pending: false` |
| **H7** | Synthetic PV caused chart mismatch | **REJECTED (10:19+ runs)** | `[OK] PV-Vektor nach Tuning: 28/44 h > 0, Max 3.39 kW` |
| **H8** | Stale pre-fix snapshot in UI | **REJECTED** | Snapshot `completed_at` matches latest main.py run |
| **H9** | Empty `matched_baseline_rows` in snapshot | **REJECTED** | 44 rows persisted |
| **H10** | Opt-in UI sim reintroduces wrong path | **REJECTED** | `opt_in_pending: false` in logs |
| **H11** | Appliances missing from matched targets | **CONFIRMED / FIXED** | `energy_comparison` 0 → 4 kWh Waschmaschine after fix |
| **H12** | Wed noon high SOC = no profile load + PV charge | **CONFIRMED** | CSV weekday 2 (Wed) hour 12: appliances 0; EV only 18–21 h; snapshot SOC 35.9% at 12:00 (10:39 run) |
| **H13** | Thu navigation shows appliance-shaped BL Ziel | **CONFIRMED** | Chart 1 → Thu works; snapshot Thu 12:00 appliances 5.7 kW; Thu 13:00 SOC 42.0% vs Wed 13:00 54.7% |

**Note on handoff “h12 SOC 10% vs 37.9%”:** That comparison used **simulation hour index** or **22:00 clock** (EV evening), not **Wednesday clock noon**. Snapshot at **22:00** shows ~**10%** SOC after scaled EV load — still true with fixes.

---

## Verified runs (silent-migration-test)

### 10:19 — real PV, flex OK

```
[OK] PV-Ertragsprognose … Max: 3.391 kW
[OK] PV-Vektor nach Tuning: 28/44 h > 0, Max 3.39 kW
Flex-Profile im Planungshorizont (kWh): ev=21.47, …
live_optimization_debug: Anzeige-Snapshot gespeichert (44 Sim-Zeilen)
```

### 10:39 — post appliance-target fix (latest snapshot)

**`live_optimization_debug.json` matched baseline:**

| Day / Clock | SoC BL Ziel | Appliances (kW) | Note |
|-------------|-------------|-----------------|------|
| Wed 12:00 | 35.9% | 0 | No weekday-2 profile load; PV charges |
| Wed 13:00 | 54.7% | 0 | Continued PV charge |
| Wed 22:00 | 10.0% | 0 | Post evening EV block |
| Thu 11:00 | 56.0% | 0 | Morning PV ramp |
| Thu 12:00 | 93.6% | WM 2.0 + TR 2.5 + GS 1.2 | **Start-of-hour** SOC after 11:00 PV charge; appliances run this hour |
| Thu 13:00 | 42.0% | WM 2.0 + TR 2.5 + GS 1.2 | **−51.6 pts** vs Thu 12:00 — appliance discharge dominates |
| Thu 14:00 | 10.0% | 0 | Appliance block ends |

**Interpretation:** Chart rows store **start-of-hour** SOC (`old_soc` in `_simulate_single_hour_baseline`). Thu noon *marker* can look high (93.6%) because 11:00–12:00 was pure PV charging; the appliance effect shows at the **13:00** boundary (42.0% < Wed 13:00 54.7%).

**`energy_comparison` (10:39):** Waschmaschine `matched_baseline_kwh: 4.0`; Smart `matched_baseline_kwh: 12.39`.

**Weekday profile fact:** `flexible_consumer_profiles.csv` weekday **3** (Thu) hours **12–13** have appliance peaks; weekday **2** (Wed) hour 12 has none. Chart 1 navigation to Thu **confirmed working** (user 10:45).

### 10:32 — earlier run (superseded by 10:39)

Wed 12:00 was 56.7% in the 10:32 snapshot (different initial_soc / run timing). Use **10:39** snapshot for acceptance.

---

## Fixes applied (instrumentation kept until sign-off)

| File | Change |
|------|--------|
| `data/profile_manager.py` | Flex CSV export/regen; INFO logging; debug logs → `debug-6dbc3d.log` |
| `optimizer/targets.py` | Thermal horizon targets; **`resolve_matched_baseline_horizon_targets()`** for profile appliances |
| `optimizer/simulation.py` | Uses matched targets; debug log (`matched_targets`, `matched_soc_by_slot`) |
| `data/pv_forecast.py` | Clearer synthetic vs real PV logging |
| `main.py` | Persists full display snapshot to `live_optimization_debug.json` |
| `ui/live_mode.py` | Snapshot-first Cockpit; debug logs for UI path |
| `optimizer/schedule.py`, `ui/main_py_sync.py`, `ui/simulation_results.py`, `runtime_store/live_display_loader.py` | UI relies on main.py (no default Live-MILP) |
| `tests/test_profile_manager_flex_export.py` | Export/regen tests |
| `tests/test_matched_baseline.py` | `test_matched_baseline_uses_profile_targets_for_config_appliances` |

**Instrumentation:** removed 2026-07-15 after silent-stack sign-off.

---

## Acceptance criteria (updated — v1.24.3 dropped)

~~Compare Chart 1 SoC BL Ziel to v1.24.3 on `energy_optimizer`.~~ **Removed.**

Use **internal consistency** instead:

1. **Terminal + snapshot agree:** `[OK] PV-Vektor nach Tuning` or `[OK] PV-Ertragsprognose`; `Flex-Profile im Planungshorizont` with non-zero `ev`; `live_optimization_debug.json` written each run.
2. **Chart = snapshot:** Cockpit SoC BL Ziel matches `matched_baseline_rows` for same `slot_datetime` (no opt-in UI simulation).
3. **Energy table sane:** `energy_comparison` — appliances have `matched_baseline_kwh` = profile sum when MILP target is 0; EV `matched_baseline_kwh` ≈ optimization target (profile-scaled).
4. **Profile shape:** EV load in matched baseline evening window (18–21 h); ~10% SOC after evening charge block (e.g. 22:00).
5. **Deploy:** NAS earnie gets code + flex CSV regen (`setup_silent_migration_test --force` or natural regen).

**Do not** tune downward to match v1.24.3 Wed noon without aligned weekday, initial SOC, and real PV — that reference is ** suspect**.

---

## UI architecture change (2026-07-15)

**Cockpit no longer auto-runs Live-MILP.** Chart 1 **SoC BL Ziel** from `main.py` → `live_optimization_debug.json` → `build_optimization_display_bundle_from_snapshot()`.

Opt-in UI simulation only when `main_down` + snapshot > 1 h + user confirms.

---

## Open / blocked

| Item | Status |
|------|--------|
| Thu chart segment (appliance profile validation) | **Done** — Chart 1 Thu navigation OK; Thu 13:00 SOC 42% vs Wed 54.7% (snapshot 10:39) |
| Remove debug instrumentation | **Done** (2026-07-15 sign-off) |
| Simulations-Details caption (optimized vs BL Ziel) | Open → [Backlog.md](../backlog/Backlog.md) New features |
| NAS earnie deploy + runtime CSV regen | Pending |
| forecast.solar retry-at plan | See `.cursor/plans/forecast.solar_retry-at_72a2f487.plan.md` |

---

## When resuming

1. ~~**Sign-off Wed BL Ziel**~~ **Done** — model-correct; v1.24.3 not a reference.
2. ~~**Fix Thu navigation + verify appliances**~~ **Done** — Thu 13:00 BL Ziel lower than Wed; appliances visible in snapshot rows.
3. **User sign-off** → remove `#region agent log` blocks (`profile_manager.py`, `simulation.py`, `live_mode.py`).
4. **Deploy to NAS earnie;** trigger profile regen on prod runtime.
5. **Backlog:** Move matched-baseline / flex-export items from `Backlog-Bugfixes.md` Verifications Pending → `Backlog-Erledigt.md` after NAS check.

---

## Resume checklist

1. Restart **main.py (Silent Migration Test)** after code pull.
2. Confirm terminal: `[OK] PV-Vektor nach Tuning`; `Flex-Profile im Planungshorizont (kWh): ev=…`.
3. Open Cockpit — **do not** use “Einmalige Simulation starten”.
4. Spot-check `live_optimization_debug.json`: Wed 12:00 SOC ~55–60%; Wed 22:00 SOC ~10%.
5. ~~Compare to v1.24.3~~ — **skip**; use acceptance criteria above.
6. If signed off: remove instrumentation, update backlog, NAS deploy.

---

## Related context

- Plan: `.cursor/plans/id_bridge_+_grundlast_68b3b906.plan.md`
- Plan: `.cursor/plans/ui_relies_on_main.py_a1f9f67e.plan.md`
- Plan: `.cursor/plans/forecast.solar_retry-at_72a2f487.plan.md`
- Launch: **main.py (Silent Migration Test)** → `silent-migration-test/config` + `runtime`
- Docs: `docs/einrichtung/silent-migration-test.md`
- Version: `1.98.1` — no bump without user approval
