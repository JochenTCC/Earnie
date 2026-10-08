# Earnie Loxone Templates (draft — 2.4.n Pattern B)

Virtual HTTP **In/Out** XML for Loxone Config. Shape matches [LoxBerry LoxoneTemplateBuilder](https://wiki.loxberry.de/entwickler/perl_develop_plugins_with_perl/perl_loxberry_sdk_dokumentation/perl_modul_loxberryloxonetemplatebuilder) (`VI_*.xml` / `VO_*.xml`).

**How-to (operators):** [`docs/referenz/loxone-signals.md`](../../../docs/referenz/loxone-signals.md) — Library setup, Default Merker names, EFM, Earnie-dead fallback, Loxone import.

**Status:** `VirtualOut/VO_*.xml` follow the structure that Loxone Config exports (checked 2026-10-07 against a template saved with **Als Vorlage speichern**): `Info` element first, `HintText` / `CmdAnswer` / `SourceVal…` attributes, UTF-8 with BOM, tab indent. Titles, comments and commands are still hand-authored, and the placeholders (`EARNIE_HOST`, `{hk_id}` / `{ev_id}`) have to be replaced after inserting. `VirtualIn/VI_*.xml` follow the structure of a Virtual Input exported by Config the same way (`Info templateType="2"`, `Unit`, `HintText`); a Virtual Input extracts the value with the escape in `Check`, a Virtual Output command writes it with `<v>`.

**Pattern B:** **VI** = Earnie → Loxone (`set_*` / Freigaben / Sollwerte + Heartbeat). **VO** = optional Loxone → Earnie telemetry push (`sens_*` / `get_*` / Flex-Leistung; placeholder URLs). Core still reads Miniserver `/jdev/sps/io/{name}`.

**Freigabe 0/1:** VI cmds use `Analog="true"` (sticky value from `\v`). `Analog="false"` (digital) pulses true on every successful poll — do not use for Freigabe.

## Install in Loxone Config

Copy **only the** `.xml` **files** (not this `README.md`, not the repo folder tree as a whole). Destination folders depend on your Config install; use whichever path exists on your PC (create `VirtualIn` / `VirtualOut` if missing).

### 1. Virtual HTTP In → `VirtualIn` folder

Copy these files from repo `share/loxone/templates/VirtualIn/` into Config’s **`VirtualIn`** template folder:

| Copy this file | Into (examples) |
| -------------- | --------------- |
| `VI_Earnie_Plant.xml` | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualIn\` |
| `VI_Earnie_Heatpump.xml` | or `Documents\Loxone\Loxone Config\Templates\VirtualIn\` |
| `VI_Earnie_EV.xml` | |
| `VI_Earnie_Consumer.xml` | |
| `VI_Earnie_Pool.xml` | |

Keep the filenames exactly (`VI_…xml`). Do **not** nest an extra `VirtualIn\` subfolder inside `VirtualIn`.

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
3. Set Address: replace `EARNIE_HOST` with the Earnie LAN IP. **Virtual In** status (`/ehal/loxone/status.json`) and **`VO_Earnie_Status.xml`** (`Earnie_Request_Optimize` / `/alive`) use port **8541** (`system.ehal_loxone_http_port`). Telemetry VOs (`VO_Earnie_*` except `Status`) now also use port **8541**; their receiver `/ehal/loxone/telemetry/…` exists only in the pilot on branch `spike/vo-push-pilot` (no receiver on `main`). The value placeholder in a Virtual Output command is `<v>`, written `&lt;v&gt;` in the XML (`\v` would be sent as the control character 0x0B).

## Files (repo layout)

| Repo path | Role |
| --------- | ---- |
| `VirtualIn/VI_Earnie_Plant.xml` | Heartbeat + ESS Design C1 setpoints |
| `VirtualIn/VI_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Freigabe` |
| `VirtualIn/VI_Earnie_EV.xml` | `Earnie_EAuto_Soll_A`, `Earnie_EAuto_Modus` |
| `VirtualIn/VI_Earnie_Consumer.xml` | Generic Freigabe |
| `VirtualIn/VI_Earnie_Pool.xml` | `Earnie_Pool_Freigabe`, `Earnie_Pool_Filter_Freigabe` |
| `VirtualOut/VO_Earnie_Status.xml` | Optional alive / `Earnie_Request_Optimize` (port **8541**) |
| `VirtualOut/VO_Earnie_Plant.xml` | Plant `sens_*` / `get_*` (incl. ESS SOC-Min/Max + max charge/discharge, 2.7.j) + `Earnie_Aussentemperatur` |
| `VirtualOut/VO_Earnie_EV.xml` | EV `sens_*` / `get_*` (`Earnie_EAuto_Leistung`, …) |
| `VirtualOut/VO_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Leistung`, `Earnie_Waermespeicher_Temp_eq`, `Earnie_Waermespeicher_Temp_low` |
| `VirtualOut/VO_Earnie_Consumer.xml` | `Earnie_Verbraucher_Leistung` |
| `VirtualOut/VO_Earnie_Pool.xml` | Pool temps / power / filter telemetry |

Frozen Merker names: [`../greenfield_device_map.json`](../greenfield_device_map.json), recipes in [`../recipes/`](../recipes/).

### Plant ESS (Design C1) + Aussentemperatur

- `Earnie_Batterie_Sollleistung` → `set_ess_active_power` (VI)
- `Earnie_LadeLeistungs-Limit` / `Earnie_EntladeLeistungs-Limit` → true caps (VI)
- `Earnie_Steuerbefehl` → `set_ess_mode` (sticky: **0 = Automatik**; VI)
- `Earnie_Speicher_Quellenwahl` → `set_ess_source_select` (2.7.h: **0 = Netz** / **1 = Batterie-Insel**; VI)
- VO: `Earnie_Netzleistung`, `Earnie_PV_Leistung`, `Earnie_Batterie_SoC`, `Earnie_Batterie_Leistung`, `Earnie_Aussentemperatur` (`sens_temperature_outside`), `Earnie_Abwesend` (`sens_absent_mode`)

**Zähler-Bausteine:** `Earnie_Netzleistung`, `Earnie_PV_Leistung`, `Earnie_Batterie_Leistung` (sowie WP/EV/Verbraucher/Pool-Leistung) **können auch vom jeweiligen EFM-Zähler kommen**. VO-Cmds bleiben im XML als Namenskatalog / optionaler Push — Earnie-Binding bevorzugt die EFM-Bezeichnung, wenn vorhanden.

## Multiple consumers / EVs (`VI_`/`VO_` Consumer + EV)

**Canonical naming** (user reference): [`docs/referenz/loxone-signals.md`](../../../docs/referenz/loxone-signals.md) — *Multiple Flex Consumers* / *Multiple EVs*.

Three layers:

| Layer | Flex example | EV example |
| ----- | ------------ | ---------- |
| Miniserver **Title** (jdev / import) | `Earnie_Verbraucher_<Slug>_Leistung` | `Earnie_EAuto_<Slug>_Soll_A` |
| VI **Check** / status JSON | `flex.{hk_id}.Earnie_Verbraucher_Freigabe` | `ev.{ev_id}.Earnie_EAuto_Soll_A` |
| VO **Befehl bei Ein** | `flex.{hk_id}.sens_power_act` | `ev.{ev_id}.sens_evcs_soc_act` |

| Layer | Rule | Waschmaschine example |
| ----- | ---- | --------------------- |
| HK `id` | snake_case entity | `waschmaschine` |
| Merker Title | `Earnie_Verbraucher_<Slug>_…` | `Earnie_Verbraucher_Waschmaschine_Leistung` |
| VO path | `flex.{hk_id}.sens_power_act` | `…/flex.waschmaschine.sens_power_act/<v>` |
| EHAL binding key | `flex.{hk_id}.sens_power_act` on that consumer | → Merker Title |

Template defaults leave `{hk_id}` / `{ev_id}` placeholders — replace in Config. WP: Titles `Earnie_Waermepumpe_*` (legacy `Earnie_WP_*`); Pool: `flex.pool.sens_power_act` or `{hk_id}`.

1. Insert **Device Template** once per flex/EV device.
2. Rename Cmd **Titles** (Prefix+Slug) and set Check/VO `{hk_id}` / `{ev_id}` as above.
3. Align VI **Check** patterns with JSON keys Earnie will publish.
4. In Earnie EHAL-Com, bind fields to the Titles.

## Not in these XMLs

- **Zähler / EFM hardware** — attach meters in Config; unique Bezeichnung; see EFM research note. Power VO Titles may still exist as optional aliases.
- **Earnie-dead fallback** — watchdog on `Earnie_Heartbeat` age in Config: [loxone-signals.md](../../../docs/referenz/loxone-signals.md#earnie-dead-fallback-in-loxone-config).
