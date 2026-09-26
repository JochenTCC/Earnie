# Smarthome-Backend (SB)

Die Seite **Smarthome-Backend** unter **Daemon Control** wählt und verbindet den Hub der Live-Umgebung — **Loxone**, **Home Assistant** oder **OpenEMS**. Hier laufen Backend-Auswahl **und** Zugangsdaten zusammen; **EHAL-Com** bietet keinen Backend-Wechsel und kein Anbindungsformular mehr, sondern nur Live-Lesen/Schreiben und Mapping für das hier gewählte Backend.

## Aufruf

1. Streamlit starten: `python -m scripts.run_streamlit`
2. Navigation: **Daemon Control → Smarthome-Backend**
3. Nach abgeschlossener Planung und ohne konfiguriertes Backend erscheint dieselbe Seite auch als blockierender First-Run-Screen vor dem Rest der App — dieselbe Implementierung, kein separates Setup-Formular.

## Erkennung (Discovery)

1. **Gezielter Scan** — bei Installation über LoxBerry-Plugin oder Home-Assistant-Add-on (`EARNIE_INSTALL_CONTEXT`, siehe `runtime_store/install_context.py`) wird der Scan auf dieses Backend eingegrenzt (SSDP für Loxone; beim HA-Add-on zuerst Supervisor-Core-Proxy über `SUPERVISOR_TOKEN` / `http://supervisor/core`, dann mDNS). Findet nichts → Fallback auf vollen passiven Scan.
2. **Voller passiver Scan** — sonst laufen mDNS (Home Assistant) und SSDP/UPnP (Loxone) parallel. Im HA-Add-on läuft die Supervisor-Self-Discovery beim HA-Scan weiterhin zuerst.
3. **Erweiterter Scan (opt-in)** — aktiver TCP-Portscan (8080/8085) für OpenEMS, nur angeboten wenn der passive Scan nichts findet (kann Firewall-/IDS-Alarme im Heimnetz auslösen, z. B. UniFi).
4. **Keine Treffer** — Hinweis, dass automatischer Verbraucher-/EHAL-Import und weitere Live-Seiten (EHAL-Com, Optimierer-Dienst) deaktiviert bleiben, bis ein Backend manuell gewählt wird.
5. **Mehrere Treffer** — Auswahl aus einer Liste; nichts verbindet sich automatisch.

Hintergrund: [SB-Identification-Draft](../../backlog/SB-Identification-Draft.md) und [Entwicklungsplan](../spec/smarthome-backend-page.md).

## Anbindung / Zugangsdaten

Ist ein Backend verbunden, zeigt die Seite oben **Anbindung** (Zugangsdaten erneut eingeben / prüfen), danach **Backend ändern** (Discovery / Wechsel), und bei Loxone den **Loxone-Import**.

Speicherorte:

| Backend        | Ablage                                       |
| -------------- | ---------------------------------------------- |
| Loxone         | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) |
| Home Assistant | `config/.env` (`EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN`); `sign` in `config.json` → `ehal.ha` |
| OpenEMS        | `config.json` → `ehal.openems`                |

Bei Loxone darf `LOXONE_IP` einen optionalen HTTP-Port enthalten (`192.168.178.1:85`; ohne Port gilt 80).

Bei Home Assistant und OpenEMS steckt der HTTP-Port in der Base-URL (`EHAL_HA_BASE_URL` in `.env` bzw. `ehal.openems.base_url`) — kein separates Port-Feld. Defaults enthalten `:8123` (HA) und `:8084` (OpenEMS); z. B. `http://homeassistant:8124` oder `http://openems-edge:8085`, wenn der Hub woanders lauscht.

Speichern der Zugangsdaten setzt `ehal.backend` und schaltet **EHAL-Com** sowie **Optimierer-Dienst** frei.

## Loxone-Import

Der Loxone → Hausprofil-Import (früher im Hauskonfigurator) läuft von dieser Seite, sobald Loxone verbunden ist. Danach Verbraucherliste im Hauskonfigurator und Signal-Mapping auf EHAL-Com prüfen.

## Siehe auch

- [EHAL-Com](ehal-com.md)
- [Betriebsmodi](betriebsmodi.md)
- [Smarthome-Backend wählen](../einrichtung/smarthome-backend-wahl.md)
