# Loxone-Signale — Referenz

Für **Greenfield / Earnie-Library (2.4.n)** gelten die **gefrorenen** Merkernamen in [`share/loxone/greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) und [`share/loxone/recipes/`](../../share/loxone/recipes/) (z. B. `Earnie_Waermepumpe_Leistung`, `Earnie_Batterie_SoC`). Bestehende Anlagen dürfen abweichende Bezeichnungen behalten — in `ehal_bindings` muss die Adresse exakt dem Miniserver-Namen entsprechen.

**Begriffsklärung (Smarthome-Merker):** Die **Adresse** (Zeichenkette, z. B. `Earnie_Waermepumpe_Freigabe`) ist ein *Smarthome-Merker*. Die **Rolle** ist der EHAL-Feldname (`sens_ess_soc`, `flex.{slug}.sens_power_act`, …) in `ehal_bindings`. Live-Backend bleibt vorerst Loxone-HTTP. Nicht verwechseln mit Chart-Markern oder `earnie_role` (Bekannt/Gesteuert/Manuell).

**Pattern B (Library):** **VI** = Earnie→Loxone (`set_*` / Freigaben / Sollwerte, Heartbeat) über `GET http://<Earnie>:8541/ehal/loxone/status.json` (Daemon-HTTP; `heartbeat_ts` = Unix-Jetztzeit, Sollwerte aus dem letzten `loxone_sent`). **VO** = optional Loxone→Earnie Push von `sens_*` / `get_*` / Flex-Leistung (Platzhalter-URLs). Core schreibt/liest weiterhin `/jdev/sps/io/{name}`. Entwürfe: [`share/loxone/templates/`](../../share/loxone/templates/).

**Freigabe-VI:** Cmds mit sticky 0/1 als **Analog** (`Analog="true"`), nicht als digitalen Eingang — sonst kurzer `1`-Puls je Polling-Zyklus (siehe [loxone-earnie-library.md](../einrichtung/loxone-earnie-library.md)).

### Drei Schichten (Title / Check / VO-Pfad)

| Schicht | Wo | Beispiel Flex | Beispiel EV |
|--------|-----|---------------|-------------|
| **Miniserver-Title** | Cmd Title (jdev / Import) | `Earnie_Verbraucher_Waschmaschine_Freigabe` | `Earnie_EAuto_Garage_Soll_A` |
| **VI Check / Status-JSON** | Virtual In Check-Muster | `flex.{hk_id}.Earnie_Verbraucher_Freigabe` | `ev.{ev_id}.Earnie_EAuto_Soll_A` |
| **VO Befehl bei Ein** | Virtual Out URL | `/ehal/loxone/telemetry/flex.{hk_id}.sens_power_act/\v` | `/ehal/loxone/telemetry/ev.{ev_id}.sens_evcs_soc_act/\v` |

`{hk_id}` / `{ev_id}` = Hausprofil-Entity-`id` (snake_case). Templates lassen die Platzhalter stehen — in Config ersetzen.

### HTTP-Marker-Probe (Greenfield, ohne Visualisierung)

Die Template-Cmd-Titel sind **bekannt** (`greenfield_device_map.json`). Earnie kann sie per `GET /jdev/sps/io/{Name}` prüfen, **ohne** dass die Bausteine in der App-Visualisierung / `LoxAPP3.json` stehen:

| `LL.Code` | Bedeutung für den Import |
|-----------|---------------------------|
| `200` | Name vorhanden und lesbar |
| `403` | Name auf dem Miniserver bekannt, für den User nicht lesbar (häufig bei Virtual HTTP In) — zählt als **vorhanden** |
| `404` | Name unbekannt / nicht hochgeladen |

Greenfield-Import: LoxAPP3-Namen **union** Probe-Treffer. EFM-Zähler weiterhin aus `LoxAPP3.json`.

### Mehrere Flex-Verbraucher (Namenskonvention)

Ein Template `VI_Earnie_Consumer` / `VO_Earnie_Consumer` deckt **einen** Verbraucher ab. Miniserver-Bezeichnungen müssen eindeutig sein. Der Hausprofil-`id` (klein, snake_case, z. B. `waschmaschine`) ist der kanonische **Entity-Slug** (`{hk_id}`).

| Signal | Merker-Title (1. / weitere) | VI Check / VO-Pfad |
|--------|-----------------------------|--------------------|
| Leistung | `Earnie_Verbraucher_Leistung` → `Earnie_Verbraucher_<Slug>_Leistung` | VO: `flex.{hk_id}.sens_power_act` |
| Freigabe | `Earnie_Verbraucher_Freigabe` → `…_<Slug>_Freigabe` | Check: `flex.{hk_id}.Earnie_Verbraucher_Freigabe` |
| Ziel kW | `Earnie_Verbraucher_Ziel_kW` → `…_<Slug>_Ziel_kW` | Check: `flex.{hk_id}.Earnie_Verbraucher_Ziel_kW` |

**Beispiel Waschmaschine** (`id` = `waschmaschine`):

- Title: `Earnie_Verbraucher_Waschmaschine_Leistung`
- VO Befehl bei Ein: `/ehal/loxone/telemetry/flex.waschmaschine.sens_power_act/\v`
- VI Check (Freigabe): `"flex.waschmaschine.Earnie_Verbraucher_Freigabe":\v` (Title bleibt `Earnie_Verbraucher_Waschmaschine_Freigabe`)
- EHAL-Com Binding: `flex.{hk_id}.sens_power_act` → Title (bei `zaehler_<slug>`: Wire-Slug ohne `zaehler_`)

**`<Slug>` im Merker:** kurzer stabiler Token (z. B. `Waschmaschine`). **`{hk_id}`:** gleicher Consumer wie im Hausprofil.

### Mehrere E-Autos (Namenskonvention)

Analog: Prefix `Earnie_EAuto_`, Entity-`id` = `{ev_id}` (z. B. `eauto`, `garage`).

| Signal | Merker-Title (1. / weitere) | VI Check / VO-Pfad |
|--------|-----------------------------|--------------------|
| Soll A | `Earnie_EAuto_Soll_A` → `Earnie_EAuto_<Slug>_Soll_A` | Check: `ev.{ev_id}.Earnie_EAuto_Soll_A` |
| Modus | `Earnie_EAuto_Modus` → `…_<Slug>_Modus` | Check: `ev.{ev_id}.Earnie_EAuto_Modus` |
| Leistung | `Earnie_EAuto_Leistung` → `…_<Slug>_Leistung` | VO: `ev.{ev_id}.sens_evcs_active_power` |
| weitere sens/get | `Earnie_EAuto_*` → `…_<Slug>_*` | VO: `ev.{ev_id}.<ehal_field>` |

Wärmepumpe: Titles `Earnie_Waermepumpe_Leistung` / `Earnie_Waermepumpe_Freigabe` (Legacy `Earnie_WP_*`); VO/Check mit `flex.{hk_id}` (Default-`id` oft `waermepumpe` / `wp_heating`). Pool: `flex.pool.sens_power_act` bzw. `{hk_id}`.

**Import:** Greenfield matcht **case-insensitive** exakte Template-Namen und **Prefix+Slug**
(z. B. `Earnie_Verbraucher_Waschmaschine_Leistung` → Consumer `waschmaschine`; `Earnie_EAuto_Garage_Soll_A` → EV `garage`). Bindings behalten die Miniserver-Schreibweise.

In Config: Template einfügen → Cmd-Titles + VO-Pfad `{id}` setzen → auf Miniserver speichern. Details: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md).

Prüfung aller konfigurierten Signale:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

## Rolle ↔ Entity (Überblick)

| Entity / Bereich | Speicherort | Typische EHAL-Felder / Rollen |
|------------------|-------------|-------------------------------|
| Anlage (Batterie, PV, Netz, Steuerbefehl, Hauslast, Außentemperatur) | `house_profiles.json` → `plant.ehal_bindings` | `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, `sens_temperature_outside`, `sens_power_consumers`, `set_ess_*` |
| Request Optimize (außerplanmäßig) | Loxone VO → Daemon-HTTP | `Earnie_Request_Optimize` auf Port `system.ehal_loxone_http_port` (Standard **8541**) |
| Wärmepumpe / Flex / Thermal | `consumers[].ehal_bindings` | `flex.{slug}.sens_power_act`, `flex.{slug}.set_enable`, `flex.{slug}.set_power_setpoint` |
| E-Auto (`ev`) | `consumers[].ehal_bindings` | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*` |
| Pool / SwimSpa | `consumers[].ehal_bindings` + Filter-Entity | siehe Greenfield `Earnie_Pool_*` / C.6 |

Bearbeitung in der UI: **nur** unter **Daemon Control → EHAL-Com → Loxone Struktur → EHAL Mapping** (Entity wählen). Der Hauskonfigurator editiert keine Merker-Adressen mehr.

## Zentrale Signale (`plant.ehal_bindings`)

Greenfield-Namen (2.4.n). Bestehende Prod-Namen (z. B. `B004-Battery_SOC`) bleiben gültig, wenn sie in `ehal_bindings` stehen. Netz/PV/Batterie-**Leistung** bevorzugt über EFM-Zähler-Bezeichnung.

| EHAL-Feld | Richtung | Greenfield-Name | Wert / Einheit |
|-----------|----------|-----------------|----------------|
| `sens_ess_soc` | Lesen | `Earnie_Batterie_SoC` | Batterie-SOC, % |
| `sens_pv_production_active` | Lesen | `Earnie_PV_Leistung` (oder EFM Production) | PV-Leistung, kW |
| `sens_ess_power` | Lesen | `Earnie_Batterie_Leistung` (oder EFM Storage) | Batterie; EHAL: +Entladung |
| `sens_grid_power_active` | Lesen | `Earnie_Netzleistung` (oder EFM Grid) | Netz: +Bezug, kW |
| `sens_power_consumers` | Lesen | (optional) | Hauslast; sonst Ableitung |
| `sens_temperature_outside` | Lesen | `Earnie_Aussentemperatur` | Außentemperatur °C (hausweit; WP/Pool) |
| `set_ess_active_power` | Schreiben | `Earnie_Batterie_Sollleistung` | Forced Leistung, kW; `+` Entladung, `−` Ladung |
| `set_ess_charge_power_limit` | Schreiben | `Earnie_LadeLeistungs-Limit` | Max. Ladeleistung (echte Grenze) |
| `set_ess_discharge_power_limit` | Schreiben | `Earnie_EntladeLeistungs-Limit` | Max. Entladeleistung (echte Grenze) |
| `set_ess_mode` | Schreiben | `Earnie_Steuerbefehl` | Sticky: immer schreiben; `0` = Automatik (Sollleistung ignorieren); OpenEMS ignoriert |
| *(Watchdog)* | Lesen | `Earnie_Heartbeat` | Pattern B; kein EHAL-Feld |

Legacy-Rollenamen (`soc_name`, `pv_power_name`, …) in `loxone_blocks` werden beim Migrate nach `plant.ehal_bindings` übernommen und danach aus der Config entfernt (leeres `loxone_blocks` entfällt; **2.4.m**).

**Sticky Merker:** Loxone behält den zuletzt geschriebenen Wert. Automatik ist **`set_ess_mode = 0`** — Config darf Sollleistung bei Modus 0 nicht anwenden, auch wenn `Earnie_Batterie_Sollleistung` noch einen alten Wert hält.

## Flexible Verbraucher — `ehal_bindings` am Consumer

Live-Steuerung kommt aus dem aktiven Hausprofil (`house_profiles.json`). Merker liegen unter `ehal_bindings` mit EHAL-Feldnamen. Bestehende Profile ohne Bindings: `python -m scripts.migrate_ehal_bindings --path <house_profiles.json> [--config <config.json>]`.

### Flex / Thermal (Stub `flex.*`)

| EHAL-Feld | Richtung | Greenfield / Beispiel | Wert |
|-----------|----------|------------------------|------|
| `flex.{slug}.sens_power_act` | Lesen | WP: `Earnie_Waermepumpe_Leistung` (Legacy `Earnie_WP_P_act`); Generic: `Earnie_Verbraucher_Leistung`; oder EFM Load | kW oder 0/1 |
| `flex.{slug}.set_enable` | Schreiben | WP: `Earnie_Waermepumpe_Freigabe` (Legacy `Earnie_WP_Freigabe`); Generic: `Earnie_Verbraucher_Freigabe` | `0`/`1` |
| `flex.{slug}.set_power_setpoint` | Schreiben | `Earnie_Verbraucher_Ziel_kW` (optional) | kW-Sollwert |

SwimSpa u. Ä. behalten projektspezifische Namen (z. B. `Earnie_SwimSpa_Freigabe`), sofern in `ehal_bindings` gesetzt.

### E-Auto (Prefix `Earnie_EAuto_`)

| EHAL-Feld | Richtung | Greenfield-Name | Wert |
|-----------|----------|-----------------|------|
| `sens_evcs_active_power` | Lesen | `Earnie_EAuto_Leistung` (Legacy `Earnie_EAuto_P_act`; oder EFM Load; dual `flex.{slug}.sens_power_act`) | kW |
| `sens_evcs_connected` | Lesen | `Earnie_EAuto_Angeschlossen` | `1` = angeschlossen |
| `sens_evcs_soc_act` | Lesen | `Earnie_EAuto_SOC` | Aktueller SOC, % |
| `sens_evcs_bat_capacity` | Lesen | `Earnie_EAuto_Kapazitaet` | kWh |
| `get_evcs_nominal_current` | Lesen | `Earnie_EAuto_MaxStrom` | A |
| `get_evcs_ready_by_time` | Lesen | AlarmClock-**Bezeichnung** (z. B. `Ladewecker` / `Wecker_Smart`; Import merged auf EV mit Zähler) | **SpecialState10** (`nextEntryTime`, Loxone-Sekunden seit 01.01.2009 → Unix `+ 1230768000`) via `/jdev/sps/io/{name}/all`. Backup: Ausgang **Tna** (Text z. B. `Morgen, 11:00`). Kein Virtual-Out-String. |
| `get_evcs_limit_soc` | Lesen | `Earnie_EAuto_LimitSOC` | Ladeziel-SOC % |
| `set_evcs_max_current` | Schreiben | `Earnie_EAuto_Soll_A` | Soll-/Maxstrom A |
| `set_evcs_mode` | Schreiben | `Earnie_EAuto_Modus` | `off`=0 \| `pv`=1 \| `now`=2 |

Zusätzlich Pflichtfeld **`min_power_kw`** am Verbraucher. Pool/SwimSpa-Filter: Hausprofil-Verbraucher **`pool_filter`** mit EHAL-Rollen (`get_filter_remaining_hours` u. a.) unter `ehal_bindings`. Greenfield-Prefix `Earnie_Pool_*` / `Earnie_Pool_Filter_*` (siehe [ehal-com.md](../ui/ehal-com.md) §C.6); bestehende SwimSpa-Merker-Namen bleiben gültig.

## Request Optimize (außerplanmäßige Läufe)

Außerplanmäßige Optimierungsläufe in `main.py` (zwischen den Viertelstunden) über Loxone → Earnie HTTP — **nicht** mehr über Merker-Event-Trigger in Config oder Hausprofil.

| Element | Bedeutung |
|---------|-----------|
| Virtual Out | Vorlage `share/loxone/templates/VirtualOut/VO_Earnie_Status.xml` |
| Address | `http://EARNIE_HOST:8541` (Port = `system.ehal_loxone_http_port`, Standard **8541**) |
| Cmd `Earnie_Request_Optimize` | `POST /ehal/loxone/request_optimize` — weckt den Daemon vor der nächsten Viertelstunde |
| Cmd `Earnie_Push_Alive` / Alive | `GET /ehal/loxone/alive` — Erreichbarkeitscheck |

Compose-Produktiv-Stacks veröffentlichen den Container-Port **8541** (siehe [Streamlit-Ports](streamlit-ports.md)).

## Beispiel-Mapping

| Verbraucher (`id`) | Steuerung (Schreiben) | Leistung (Lesen) |
|--------------------|----------------------|------------------|
| `swimspa` | `flex.{slug}.set_enable` → `Earnie_SwimSpa_Freigabe` | `flex.{slug}.sens_power_act` → `Earnie_Swim-Spa-P_act` |
| `eauto` | `set_evcs_max_current` / `set_evcs_mode` | `sens_evcs_*` / `flex.{slug}.sens_power_act` |
| `wp_heating` | `flex.{slug}.set_enable` → `Earnie_Waermepumpe_Freigabe` | `flex.{slug}.sens_power_act` → `Earnie_Waermepumpe_Leistung` |

## Lesen vs. Schreiben in `main.py`

| Phase | Aktion |
|-------|--------|
| Einlesen | SOC, Leistungen, PV, Flex-Inputs, E-Auto-Status |
| Optimierung | MILP über 24 h (15-Min-Slots intern) |
| Schreiben | ESS-Limits / Modus, Freigaben / EV-Strom je Slot |

Die App **liest** dieselben Live-Werte für Anzeige; **schreibt** Steuerwerte nur im Live-Modus. Merker-Zuordnung: [EHAL-Com](../ui/ehal-com.md).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).
