# Smarthome-Backend (SB)

Die Seite **Smarthome-Backend** unter **Daemon Control** wählt den Hub der Live-Umgebung aus und verbindet ihn: **Loxone**, **Home Assistant** oder **OpenEMS**. Backend-Auswahl und Zugangsdaten liegen gemeinsam auf dieser Seite.

Auf **EHAL-Com** stehen Live-Lesen, Live-Schreiben und das Mapping für das hier gewählte Backend.

## Aufruf

1. Streamlit starten: `python -m scripts.run_streamlit`
2. In der Navigation **Daemon Control → Smarthome-Backend** öffnen.
3. Ist die Planung abgeschlossen und noch kein Backend konfiguriert, erscheint dieselbe Seite als blockierender First-Run-Screen vor dem Rest der App.

## Erkennung (Discovery)

1. **Gezielter Scan:** Bei Installation über das LoxBerry-Plugin oder das Home-Assistant-Add-on grenzt Earnie den Scan auf dieses Backend ein (`EARNIE_INSTALL_CONTEXT`, siehe `runtime_store/install_context.py`).
   - Loxone: SSDP.
   - HA-Add-on: zuerst der Supervisor-Core-Proxy über `SUPERVISOR_TOKEN` / `http://supervisor/core`, danach mDNS.
   - Findet der gezielte Scan nichts, folgt als Fallback der volle passive Scan.
2. **Voller passiver Scan:** In allen anderen Fällen laufen mDNS (Home Assistant) und SSDP/UPnP (Loxone) parallel. Im HA-Add-on läuft beim HA-Scan weiterhin zuerst die Supervisor-Self-Discovery.
3. **Erweiterter Scan (opt-in):** Ein aktiver TCP-Portscan (8080/8085) sucht nach OpenEMS. Die Seite bietet ihn nur an, wenn der passive Scan nichts findet.
   - Der Portscan kann Firewall- oder IDS-Alarme im Heimnetz auslösen (z. B. UniFi).
   - Voraussetzung ist ein bekanntes Heimnetz (`EARNIE_LAN_SUBNET` oder Host-IP über Supervisor).
   - Liegt die Container-IP in `172.16.0.0/12`, fragt die Seite nach dem LAN-CIDR, statt blind zu scannen. Details: [container.md](../einrichtung/container.md) § Netzwerk.
4. **Keine Treffer:** Die Seite weist darauf hin, dass der automatische Verbraucher-/EHAL-Import und weitere Live-Seiten (EHAL-Com, Optimierer-Dienst) deaktiviert bleiben, bis ein Backend gewählt ist. Im Docker-Bridge-Netz (ohne HA-Add-on) bietet die Seite zusätzlich sofort die Auswahl **Home Assistant** an, weil mDNS dort oft leer bleibt.
5. **Mehrere Treffer:** Die Auswahl erfolgt aus einer Liste; keines der Backends verbindet sich automatisch.

Bei verbundenem Loxone zeigen die Seite und EHAL-Com den **letzten Aufruf vom Miniserver** auf Port 8541 (Zeit und Peer-IP).

Einrichtungspfad: [Smarthome-Backend wählen](../einrichtung/smarthome-backend-wahl.md).

## Anbindung / Zugangsdaten

Ist ein Backend verbunden, zeigt die Seite von oben nach unten:

- Erfolgsmeldung mit dem aktiven Backend (EHAL-Com und Optimierer-Dienst sind freigeschaltet).
- **Zugangsdaten** (zuklappbar): Zugangsdaten erneut eingeben oder prüfen. Bei einem Loxone-Auth-Fehler öffnet sich der Bereich automatisch.
- **Backend ändern:** Discovery starten oder das Backend wechseln.
- **Loxone-Import:** nur bei Loxone.

Während der Ersteinrichtung erscheinen die Zugangsdaten als eigener Schritt (noch ohne Erfolgsmeldung). Nach dem Speichern verschwindet dieser offene Anbindung-Abschnitt.

Speicherorte:

| Backend        | Ablage                                       |
| -------------- | ---------------------------------------------- |
| Loxone         | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) |
| Home Assistant | optional `sign` / `boolean_invert` in `config.json` → `ehal.ha` |
| OpenEMS        | `config.json` → `ehal.openems`                |

**Ports:**

- **Loxone:** `LOXONE_IP` darf einen optionalen HTTP-Port enthalten (`192.168.178.1:85`). Ohne Port gilt 80.
- **OpenEMS:** Der HTTP-Port steht in der Base-URL (`ehal.openems.base_url`); ein separates Port-Feld gibt es nicht. Der Default enthält `:8084`. Lauscht der Hub auf einem anderen Port, die URL entsprechend anpassen, z. B. `http://openems-edge:8085`. **Home Assistant** ruft Earnie über den Daemon-Port 8541 auf.

Das Speichern der Zugangsdaten setzt `ehal.backend` und schaltet **EHAL-Com** sowie **Optimierer-Dienst** frei.

## Loxone-Import

Der Import von Loxone ins Hausprofil läuft von dieser Seite aus, sobald Loxone verbunden ist. Danach die Verbraucherliste im Hauskonfigurator und das Signal-Mapping auf EHAL-Com prüfen.

## Siehe auch

- [EHAL-Com](ehal-com.md)
- [Betriebsmodi](betriebsmodi.md)
- [Smarthome-Backend wählen](../einrichtung/smarthome-backend-wahl.md)
