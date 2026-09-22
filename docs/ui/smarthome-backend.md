# Smarthome-Backend (SB)

The **Smarthome-Backend** page under **Daemon Control** picks and connects the live-environment hub — **Loxone**, **Home Assistant**, or **OpenEMS**. It is the single place backend selection **and credentials** happen; **EHAL-Com** no longer offers a backend switch or Anbindung form, it only shows live read/write and mapping for the backend chosen here.

## Access

1. Start Streamlit: `python -m scripts.run_streamlit`
2. Navigation: **Daemon Control → Smarthome-Backend**
3. Once planning is complete and no backend is configured yet, this page also appears as a blocking first-run screen before the rest of the app — same implementation, no separate setup form.

## Discovery

1. **Targeted scan** — if Earnie was installed via the LoxBerry plugin or the Home Assistant add-on (`EARNIE_INSTALL_CONTEXT`, see `runtime_store/install_context.py`), the scan narrows to that backend (SSDP for Loxone; for the HA add-on: Supervisor Core proxy first via `SUPERVISOR_TOKEN` / `http://supervisor/core`, then mDNS). Falls back to a full passive scan if nothing is found.
2. **Full passive scan** — otherwise, both mDNS (Home Assistant) and SSDP/UPnP (Loxone) run together. In the HA add-on, Supervisor self-discovery still runs first when HA is scanned.
3. **Extended scan (opt-in)** — an active TCP port scan (8080/8085) for OpenEMS, offered only after a passive scan finds nothing, since it can trigger firewall/IDS alerts on the home network (e.g. UniFi).
4. **Zero results** — a hint explains that the automatic consumer/EHAL import and other live-environment pages (EHAL-Com, Optimierer-Dienst) stay disabled until a backend is picked manually.
5. **Multiple results** — pick one from a list; nothing connects automatically.

See [SB-Identification-Draft](../../backlog/SB-Identification-Draft.md) and [development plan](../spec/smarthome-backend-page.md) for the underlying design.

## Anbindung / Credentials

Once a backend is connected, this page shows **Anbindung** at the top (re-enter / re-check credentials), then **Backend ändern** (discovery / switch), then **Loxone-Import** when the backend is Loxone.

Same storage as before, just reached from here now:

| Backend        | Storage                                       |
| -------------- | ---------------------------------------------- |
| Loxone         | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) |
| Home Assistant | `config.json` → `ehal.ha`                     |
| OpenEMS        | `config.json` → `ehal.openems`                |

For Loxone, `LOXONE_IP` may include an optional HTTP port (`192.168.178.1:85`; default without a port is 80).

For Home Assistant and OpenEMS, the HTTP port is part of the Base-URL field (`ehal.ha.base_url` / `ehal.openems.base_url`) — there is no separate port input. Defaults embed `:8123` (HA) and `:8084` (OpenEMS); use e.g. `http://homeassistant:8124` or `http://openems-edge:8085` when the hub listens elsewhere.

Saving credentials sets `ehal.backend` and unlocks **EHAL-Com** and **Optimierer-Dienst**.

## Loxone Import

The Loxone → house-profile import (formerly on the Hauskonfigurator) now runs from this page once Loxone is connected. After import, check created consumers on the Hauskonfigurator and signal mapping on EHAL-Com.

## See Also

- [EHAL-Com](ehal-com.md)
- [Betriebsmodi](betriebsmodi.md)
