# Earnie Loxone Templates (draft — 2.4.n Pattern B)

Virtual HTTP **In/Out** XML for Loxone Config. Shape matches [LoxBerry LoxoneTemplateBuilder](https://wiki.loxberry.de/entwickler/perl_develop_plugins_with_perl/perl_loxberry_sdk_dokumentation/perl_modul_loxberryloxonetemplatebuilder) (`VI_*.xml` / `VO_*.xml`).

**Status:** hand-authored draft. Import → fix Address/`Check` → **Als Vorlage speichern** → replace these files with Config-exported XML.

## Install in Loxone Config

Copy **only the** `.xml` **files** (not this `README.md`, not the repo folder tree as a whole). Destination folders depend on your Config install; use whichever path exists on your PC (create `VirtualIn` / `VirtualOut` if missing).

### 1. Virtual HTTP In → `VirtualIn` folder

Copy these **four** files from repo `share/loxone/templates/VirtualIn/` into Config’s `**VirtualIn`** template folder:


| Copy this file           | Into (examples)                                                    |
| ------------------------ | ------------------------------------------------------------------ |
| `VI_Earnie_Plant.xml`    | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualIn\` |
| `VI_Earnie_Heatpump.xml` | or `Documents\Loxone\Loxone Config\Templates\VirtualIn\`           |
| `VI_Earnie_EV.xml`       |                                                                    |
| `VI_Earnie_Consumer.xml` |                                                                    |


Keep the filenames exactly (`VI_…xml`). Do **not** nest an extra `VirtualIn\` subfolder inside `VirtualIn`.

### 2. Virtual Out → `VirtualOut` folder

Copy this **one** file from repo `share/loxone/templates/VirtualOut/` into Config’s `**VirtualOut`** template folder:


| Copy this file         | Into (examples)                                                     |
| ---------------------- | ------------------------------------------------------------------- |
| `VO_Earnie_Status.xml` | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualOut\` |
|                        | or `Documents\Loxone\Loxone Config\Templates\VirtualOut\`           |




### 3. After copy

1. Restart **Loxone Config**.
2. Insert via periphery **Device Templates** / Virtual In / Virtual Out (Earnie entries should appear).
3. Set Address: replace `EARNIE_HOST` with the Earnie LAN IP. Status URL `/ehal/loxone/status.json` is a **placeholder** until Earnie ships that endpoint (Core still uses Miniserver `/jdev/sps/io/{name}` today).



## Files (repo layout)


| Repo path                          | Role                                                             |
| ---------------------------------- | ---------------------------------------------------------------- |
| `VirtualIn/VI_Earnie_Plant.xml`    | Heartbeat + ESS Design C1 setpoints (Soll + limits + mode) |
| `VirtualIn/VI_Earnie_Heatpump.xml` | `Ernie_WP_Freigabe`                                              |
| `VirtualIn/VI_Earnie_EV.xml`       | `Ernie_EAuto_Soll_A`, `Ernie_EAuto_Modus`                        |
| `VirtualIn/VI_Earnie_Consumer.xml` | Generic Freigabe + Ziel_kW (one consumer; see below for several) |
| `VirtualOut/VO_Earnie_Status.xml`  | Optional alive / request_optimize                                |


Frozen Merker names: [`../greenfield_device_map.json`](../greenfield_device_map.json), recipes in [`../recipes/`](../recipes/).

### Plant ESS (Design C1)

- `Ernie_Batterie_Sollleistung` → `set_ess_active_power` (forced power; omit/0 when Automatik)
- `Ernie_Ladegrenze` / `Ernie_Entladegrenze` → true max charge/discharge caps
- `Ernie_Steuerbefehl` → `set_ess_mode` (hint for Huawei/Loxone Config; OpenEMS ignores)

## Multiple generic consumers (`VI_Earnie_Consumer.xml`)

The template is a **single** flex consumer with fixed Cmd titles:

- `Earnie_Verbraucher_Freigabe`
- `Earnie_Verbraucher_Ziel_kW`

Those names must stay **unique** on the Miniserver. For a second (third, …) consumer, do **not** insert the same template unchanged a second time.

### Recommended workflow in Config

1. Insert **Device Template** `Earnie Generic Consumer` once per flex device (or once, then duplicate the Virtual HTTP In in the periphery tree).
2. For each instance, rename the **Virtual HTTP In** device (e.g. `Earnie Waschmaschine`) so the tree stays readable.
3. Rename each **Virtual HTTP In Command** (Title) to a unique Bezeichnung under the `Ernie_Verbraucher_` prefix, e.g.:


| Role                                                | Consumer 1 (template default)                | Consumer 2 (example)                                       |
| --------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| Freigabe                                            | `Earnie_Verbraucher_Freigabe`                | `Earnie_Verbraucher_Waschmaschine_Freigabe`                |
| Ziel kW                                             | `Earnie_Verbraucher_Ziel_kW`                 | `Earnie_Verbraucher_Waschmaschine_Ziel_kW`                 |
| Leistung (usually EFM Zähler / Merker, not this VI) | `Earnie_Verbraucher_Leistung` or Zähler name | `Earnie_Verbraucher_Waschmaschine_Leistung` or Zähler name |


1. Align the **Check** pattern with the JSON key Earnie will publish (must match the Cmd Title if status JSON uses that name), e.g. `"Ernie_Verbraucher_Waschmaschine_Freigabe":\v`.
2. Same Earnie base URL/`status.json` is fine for all instances; each Cmd only extracts its own key.
3. In Earnie HK / EHAL mapping, each generic consumer gets its own `ehal_bindings` pointing at those unique names. Greenfield import matches the `Ernie_Verbraucher_` prefix group.

Keep one consumer’s Freigabe/Ziel/Leistung names consistent (same slug). Prefer EFM Load **Bezeichnung** for live power when that Zähler is the consumer.

## Not in these XMLs

- **Zähler / EFM** — attach meters in Config; unique Bezeichnung; see EFM research note.
- **Telemetry Merker** (`Ernie_Batterie_SoC`, `Ernie_Netzleistung`, …) — Memory/Status or meter names; create in Config or use EFM node names.
- **Earnie-dead fallback** — watchdog on `Ernie_Heartbeat` age in Config (documented in how-to when written).

