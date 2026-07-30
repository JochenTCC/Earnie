# Earnie Loxone Templates (draft — 2.4.n Pattern B)

Virtual HTTP **In/Out** XML for Loxone Config. Shape matches [LoxBerry LoxoneTemplateBuilder](https://wiki.loxberry.de/entwickler/perl_develop_plugins_with_perl/perl_loxberry_sdk_dokumentation/perl_modul_loxberryloxonetemplatebuilder) (`VI_*.xml` / `VO_*.xml`).

**Status:** hand-authored draft. Import → fix Address/`Check` → **Als Vorlage speichern** → replace these files with Config-exported XML.

## Install in Loxone Config

Copy **only the `.xml` files** (not this `README.md`, not the repo folder tree as a whole). Destination folders depend on your Config install; use whichever path exists on your PC (create `VirtualIn` / `VirtualOut` if missing).

### 1. Virtual HTTP In → `VirtualIn` folder

Copy these **four** files from repo `share/loxone/templates/VirtualIn/` into Config’s **`VirtualIn`** template folder:

| Copy this file | Into (examples) |
|----------------|-----------------|
| `VI_Earnie_Plant.xml` | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualIn\` |
| `VI_Earnie_Heatpump.xml` | or `Documents\Loxone\Loxone Config\Templates\VirtualIn\` |
| `VI_Earnie_EV.xml` | |
| `VI_Earnie_Consumer.xml` | |

Keep the filenames exactly (`VI_…xml`). Do **not** nest an extra `VirtualIn\` subfolder inside `VirtualIn`.

### 2. Virtual Out → `VirtualOut` folder

Copy this **one** file from repo `share/loxone/templates/VirtualOut/` into Config’s **`VirtualOut`** template folder:

| Copy this file | Into (examples) |
|----------------|-----------------|
| `VO_Earnie_Status.xml` | `%ProgramData%\Loxone\Loxone Config\<version>\Template\VirtualOut\` |
| | or `Documents\Loxone\Loxone Config\Templates\VirtualOut\` |

### 3. After copy

1. Restart **Loxone Config**.
2. Insert via periphery **Device Templates** / Virtual In / Virtual Out (Earnie entries should appear).
3. Set Address: replace `EARNIE_HOST` with the Earnie LAN IP. Status URL `/ehal/loxone/status.json` is a **placeholder** until Earnie ships that endpoint (Core still uses Miniserver `/jdev/sps/io/{name}` today).

## Files (repo layout)

| Repo path | Role |
|-----------|------|
| `VirtualIn/VI_Earnie_Plant.xml` | Heartbeat + ESS setpoints |
| `VirtualIn/VI_Earnie_Heatpump.xml` | `Ernie_WP_Freigabe` |
| `VirtualIn/VI_Earnie_EV.xml` | `Ernie_EAuto_Soll_A`, `Ernie_EAuto_Modus` |
| `VirtualIn/VI_Earnie_Consumer.xml` | Generic Freigabe + Ziel_kW |
| `VirtualOut/VO_Earnie_Status.xml` | Optional alive / request_optimize |

Frozen Merker names: [`../greenfield_device_map.json`](../greenfield_device_map.json), recipes in [`../recipes/`](../recipes/).

## Not in these XMLs

- **Zähler / EFM** — attach meters in Config; unique Bezeichnung; see EFM research note.
- **Telemetry Merker** (`Ernie_Batterie_SoC`, `Ernie_Netzleistung`, …) — Memory/Status or meter names; create in Config or use EFM node names.
- **Earnie-dead fallback** — watchdog on `Ernie_Heartbeat` age in Config (documented in how-to when written).
