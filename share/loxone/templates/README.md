# Earnie Loxone Templates (Pattern B + 2.7.q Q4)

Virtual HTTP **In/Out** XML for Loxone Config. Shape matches [LoxBerry LoxoneTemplateBuilder](https://wiki.loxberry.de/entwickler/perl_develop_plugins_with_perl/perl_loxberry_sdk_dokumentation/perl_modul_loxberryloxonetemplatebuilder) (`VI_*.xml` / `VO_*.xml`).

**How-to (operators):** [`docs/referenz/loxone-signals.md`](../../../docs/referenz/loxone-signals.md) — Library setup, Default Merker names, EFM, Earnie-dead fallback, Loxone import.

**Status:** `VirtualOut/VO_*.xml` follow the structure that Loxone Config exports (checked 2026-10-07 against a template saved with **Als Vorlage speichern**): `Info` element first, `HintText` / `CmdAnswer` / `SourceVal…` attributes, UTF-8 with BOM, tab indent. Titles, comments and commands are still hand-authored, and the placeholders (`EARNIE_HOST`, `{hk_id}` / `{ev_id}`) have to be replaced after inserting. `VirtualIn/VI_*.xml` follow the structure of a Virtual Input exported by Config the same way (`Info templateType="2"`, `Unit`, `HintText`); a Virtual Input extracts the value with the escape in `Check`, a Virtual Output command writes it with `<v>`.

**Pattern B:** **VI** = Earnie → Loxone (`set_*` / Freigaben / Sollwerte + Heartbeat). **VO** = Loxone → Earnie telemetry push (`sens_*` / `get_*`; qualified path IDs). Core reads from the push inbox for those fields.

**Freigabe 0/1:** VI cmds use `Analog="true"` (sticky value from `\v`). `Analog="false"` (digital) pulses true on every successful poll — do not use for Freigabe.

## Legacy vs v2 vs Pilot

| Kind | Files | When to use |
| ---- | ----- | ----------- |
| **Legacy VI** | `VI_Earnie_*.xml` (no `_v2`) | Rollback of Check keys only (while dual-emit still serves legacy JSON keys) |
| **VI v2** | `VI_Earnie_*_v2.xml` | Preferred — Check keys = qualified EHAL IDs; Titles from the ID (placeholders `{hk_id}` / `{ev_id}`) |
| **VI Pilot** | generated `VI_Pilot_*.xml` | Live config — real Kennungen filled by `python -m scripts.pilot_vi_template_gen` |
| **VO Pilot** | generated `VO_Pilot_*.xml` | Live config — paths + titles from qualified IDs via `python -m scripts.pilot_vo_template_gen` |

**Dual-emit:** `status.json` emits legacy Check keys **and** qualified peers until Q8. After **2.7.q Q5**, Earnie no longer writes Merkers via `/dev/sps/io`; actuation is VI poll of `status.json` only (see `docs/ui/ehal-com.md` § Q5).

### Generators

```text
python -m scripts.pilot_vi_template_gen --config-dir <earnie_env/config> \
    --host <Earnie-LAN-IP> --port 8541 --out-dir <dir>

python -m scripts.pilot_vo_template_gen --config-dir <earnie_env/config> \
    --host <Earnie-LAN-IP> --port 8541 --out-dir <dir>
```

VO titles are `Push_<qualified-id>` (dots → `_`). VI titles are the sanitized qualified ID without `Push_`.

## Install in Loxone Config

Copy **only the** `.xml` **files** (not this `README.md`, not the repo folder tree as a whole). Destination folders depend on your Config install; use whichever path exists on your PC (create `VirtualIn` / `VirtualOut` if missing).

### 1. Virtual HTTP In → `VirtualIn` folder

Copy these files from repo `share/loxone/templates/VirtualIn/` into Config’s **`VirtualIn`** template folder:

| Copy this file | Into (examples) |
| -------------- | --------------- |
| `VI_Earnie_Plant.xml` / `VI_Earnie_Plant_v2.xml` | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualIn\` |
| `VI_Earnie_Heatpump.xml` / `_v2` | or `Documents\Loxone\Loxone Config\Templates\VirtualIn\` |
| `VI_Earnie_EV.xml` / `_v2` | |
| `VI_Earnie_Consumer.xml` / `_v2` | |
| `VI_Earnie_Pool.xml` / `_v2` | |

Keep the filenames exactly (`VI_…xml`). Do **not** nest an extra `VirtualIn\` subfolder inside `VirtualIn`. Prefer **v2** for new wiring; keep legacy only for rollback.

### 2. Virtual Out → `VirtualOut` folder

Copy these files from repo `share/loxone/templates/VirtualOut/` into Config’s **`VirtualOut`** template folder:

| Copy this file | Into (examples) |
| -------------- | --------------- |
| `VO_Earnie_Status.xml` | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualOut\` |
| `VO_Earnie_Plant.xml` | or `Documents\Loxone\Loxone Config\Templates\VirtualOut\` |
| `VO_Earnie_EV.xml` | |
| `VO_Earnie_Heatpump.xml` | |
| `VO_Earnie_Consumer.xml` | |
| `VO_Earnie_Pool.xml` | |

### 3. After copy

1. Restart **Loxone Config**.
2. Insert via periphery **Device Templates** / Virtual In / Virtual Out (Earnie entries should appear).
3. Set Address: replace `EARNIE_HOST` with the Earnie LAN IP. **Virtual In** status (`/ehal/loxone/status.json`) and **`VO_Earnie_Status.xml`** (`Earnie_Request_Optimize` / `/alive`) use port **8541** (`system.ehal_loxone_http_port`). Telemetry VOs also use port **8541** (`/ehal/loxone/telemetry/…`). The value placeholder in a Virtual Output command is `<v>`, written `&lt;v&gt;` in the XML (`\v` would be sent as the control character 0x0B).

## Files (repo layout)

| Repo path | Role |
| --------- | ---- |
| `VirtualIn/VI_Earnie_Plant.xml` | Legacy: Heartbeat + ESS Design C1 (Merker Titles) |
| `VirtualIn/VI_Earnie_Plant_v2.xml` | v2: same Checks; Titles = field names (`heartbeat_ts`, `set_ess_*`, …) |
| `VirtualIn/VI_Earnie_Heatpump.xml` | Legacy Freigabe Check |
| `VirtualIn/VI_Earnie_Heatpump_v2.xml` | `heatpump.{hk_id}.set_enable` |
| `VirtualIn/VI_Earnie_EV.xml` | Legacy `ev.{ev_id}.Earnie_EAuto_*` |
| `VirtualIn/VI_Earnie_EV_v2.xml` | `evcs.{ev_id}.set_evcs_max_current` / `set_evcs_mode` |
| `VirtualIn/VI_Earnie_Consumer.xml` | Legacy `flex.{hk_id}.Earnie_Verbraucher_Freigabe` |
| `VirtualIn/VI_Earnie_Consumer_v2.xml` | `consumer.{hk_id}.set_enable` |
| `VirtualIn/VI_Earnie_Pool.xml` | Legacy bare pool Freigaben |
| `VirtualIn/VI_Earnie_Pool_v2.xml` | `pool.{hk_id}.set_enable` + `pool.pool_filter.set_enable` |
| `VirtualOut/VO_Earnie_Status.xml` | Optional alive / `Earnie_Request_Optimize` (port **8541**) |
| `VirtualOut/VO_Earnie_Plant.xml` | Plant `sens_*` / `get_*` (incl. ESS SOC-Min/Max + max charge/discharge, 2.7.j) + `Earnie_Aussentemperatur` |
| `VirtualOut/VO_Earnie_EV.xml` | EV `sens_*` / `get_*` (`Earnie_EAuto_Leistung`, …) |
| `VirtualOut/VO_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Leistung`, `Earnie_Waermespeicher_Temp_eq`, `Earnie_Waermespeicher_Temp_low` |
| `VirtualOut/VO_Earnie_Consumer.xml` | `Earnie_Verbraucher_Leistung`; `Earnie_Verbraucher_<Slug>_Aktiv` → VO `consumer.{hk_id}.sens_consumer_active` (2.7.p) |
| `VirtualOut/VO_Earnie_Pool.xml` | Pool temps / power / filter telemetry |

Frozen Merker names (import / legacy): [`../greenfield_device_map.json`](../greenfield_device_map.json), recipes in [`../recipes/`](../recipes/).

### Plant ESS (Design C1) + Aussentemperatur

- `Earnie_Batterie_Sollleistung` → `set_ess_active_power` (VI legacy Title; v2 Title = field name)
- `Earnie_LadeLeistungs-Limit` / `Earnie_EntladeLeistungs-Limit` → true caps (VI)
- `Earnie_Steuerbefehl` → `set_ess_mode` (sticky: **0 = Automatik**; VI)
- `Earnie_Speicher_Quellenwahl` → `set_ess_source_select` (2.7.h: **0 = Netz** / **1 = Batterie-Insel**; VI)
- VO: `Earnie_Netzleistung`, `Earnie_PV_Leistung`, `Earnie_Batterie_SoC`, `Earnie_Batterie_Leistung`, `Earnie_Aussentemperatur` (`sens_temperature_outside`), `Earnie_Abwesend` (`sens_absent_mode`)

**Zähler-Bausteine:** `Earnie_Netzleistung`, `Earnie_PV_Leistung`, `Earnie_Batterie_Leistung` (sowie WP/EV/Verbraucher/Pool-Leistung) **können auch vom jeweiligen EFM-Zähler kommen**. VO-Cmds bleiben im XML als Namenskatalog / optionaler Push — Earnie-Binding bevorzugt die EFM-Bezeichnung, wenn vorhanden.

## Multiple consumers / EVs (`VI_`/`VO_` Consumer + EV)

**Canonical naming** (user reference): [`docs/referenz/loxone-signals.md`](../../../docs/referenz/loxone-signals.md) — *Multiple Flex Consumers* / *Multiple EVs*.

Three layers (legacy vs v2 Check):

| Layer | Flex legacy | Flex v2 | EV legacy | EV v2 |
| ----- | ----------- | ------- | --------- | ----- |
| Miniserver **Title** (import) | `Earnie_Verbraucher_<Slug>_…` | same until Q8 | `Earnie_EAuto_<Slug>_…` | same until Q8 |
| VI **Check** / status JSON | `flex.{hk_id}.Earnie_Verbraucher_Freigabe` | `consumer.{hk_id}.set_enable` | `ev.{ev_id}.Earnie_EAuto_Soll_A` | `evcs.{ev_id}.set_evcs_max_current` |
| VO **Befehl bei Ein** | qualified path (Pilot) | same | qualified path (Pilot) | same |

Template defaults leave `{hk_id}` / `{ev_id}` placeholders — replace in Config, or generate Pilot XML from your config dir.

1. Insert **Device Template** once per flex/EV device (prefer **v2**).
2. Rename Cmd **Titles** if needed and set Check/VO `{hk_id}` / `{ev_id}` as above — or use Pilot generator for real Kennungen.
3. Align VI **Check** patterns with JSON keys Earnie publishes (dual-emit during cutover).
4. In Earnie EHAL-Com, bind fields (Merker names remain as activation / import hints until Q8; Loud writes use qualified `status.json` keys after Q5).

## Not in these XMLs

- **Zähler / EFM hardware** — attach meters in Config; unique Bezeichnung; see EFM research note. Power VO Titles may still exist as optional aliases.
- **Earnie-dead fallback** — watchdog on `Earnie_Heartbeat` / `heartbeat_ts` age in Config: [loxone-signals.md](../../../docs/referenz/loxone-signals.md#earnie-dead-fallback-in-loxone-config).
