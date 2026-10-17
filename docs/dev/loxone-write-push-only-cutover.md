# Loxone write push-only — staged cutover

Moved out of `docs/ui/ehal-com.md` (§ Silent Mode vs. Loud Mode, § Cutover Checklist, § Write push-only). Historical rollout checklist for switching Loud-mode writes to `status.json` push-only.

Loud writes publish only to `status.json` (qualified EHAL IDs). The Miniserver VI polls every **10 s**. Only qualified Check keys are published, so VI templates must use `VI_Earnie_*_v2.xml` or the Pilot VI.

## Preconditions

1. Earnie runs a build that publishes writes via `status.json` only (no Merker HTTP on the Loud cycle).
2. Regenerate Pilot VIs: `python -m scripts.pilot_vi_template_gen --config-dir <config> --host <Earnie-LAN-IP> --port 8541 --out-dir <dir>`.
3. In Config: each write actuator is driven by the **VirtualInHttpCmd** (same object as the old Merker title).

## Stage VI Checks

Rising risk; only qualified Check keys are emitted; observe ≥24 h per stage, day and night for EV and powerstations.

| Stage | Group | Pilot / v2 file (home plant example) |
| ----- | ----- | ------------------------------------ |
| 1 | Consumers `consumer.*.set_enable` | `VI_Pilot_*` / `VI_Earnie_Consumer_v2` (if any) |
| 2 | Heat pump `heatpump.*.set_enable` | `VI_Pilot_Waermepumpe.xml` |
| 3 | Pool / filter `pool.*.set_enable` | `VI_Pilot_Pool.xml` — keep **Analog** |
| 4 | Plant (forced ESS setpoint, export limit) + heartbeat | `VI_Pilot_Plant.xml`, `VI_Pilot_Heartbeat.xml`, house-battery Pilot |
| 5 | EV `evcs.*.set_evcs_*` | `VI_Pilot_EV.xml` — accept ≤10 s latency |
| 6 | Powerstations `ess.{id}.set_*` | `VI_Pilot_Batterie_*.xml` — accept ≤10 s latency |

Per stage: switch Check to the qualified key → confirm `status.json` has the key → VI value updates within one poll → **Live-Schreiben** / callback `ts` advances. Legacy Check keys are no longer published, so keep the VI on qualified IDs.

## After all stages

Confirm that actuators follow the VI within ≤10 s and that no `/dev/sps/io/…` setpoint traffic occurs for ESS, flex consumers, and powerstations. Observe ≥24 h.

**Accepted limits:** VI poll latency up to ~10 s for EV current and per-cycle powerstation writes; Freigabe Cmds stay Analog (sticky `\v`, no digital pulse on every poll).

## Silent Mode vs. Loud Mode


|                            | Silent mode                          | Loud mode                     |
| ---------------------------- | --------------------------------------- | -------------------------------- |
| Read                        | always active (also on this page)      | always active                    |
| Write by `main.py`          | no                                       | yes (only when the service runs) |
| Write table                 | setpoints only                          | value + success + timestamp      |
| Typical use                 | testing, parallel legacy operation      | production after cutover         |


Silent mode: `runtime/local_settings.json` → `"silent_mode"` (legacy: `"loxone_silent_mode"`; takes priority over `system.silent_mode`). Default without a file: **silent on**. The configured mode (Silent/Loud) is independent of whether the optimizer service is running: Loud mode writes only while **main.py** is running (start and stop on **Optimierer-Dienst**, see [Optimizer service and write mode](../ui/ehal-com.md#optimizer-service-and-write-mode)).

## Cutover Checklist

1. **Backend** and **credentials** on Smarthome-Backend (**Anbindung**).
2. **Live-Lesen:** `sens_*` / `get_*` rows with status **OK**.
3. **Live-Schreiben:** all `set_*` rows with `Erfolg` = `Ja` (turn silent mode off first).
4. **Cockpit / Sankey:** setpoints match live values ([Charts & Panels](../ui/charts.md)).
