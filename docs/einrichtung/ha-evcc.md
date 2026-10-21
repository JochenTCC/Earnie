# Home Assistant + evcc (DACH-Pfad A2 / B)

Für den Produktivbetrieb mit breitem Geräteangebot im DACH-Raum nutzt Earnie Home Assistant als Geräteanbindung (Southbound). **evcc** läuft als Sidecar unter Home Assistant und liefert typische Entities für Wallbox, Zähler und Wechselrichter. Earnie greift nicht parallel direkt auf die evcc-API zu.

Den Datenaustausch übernimmt der **Push-Vertrag**, derselbe HTTP-Vertrag wie bei Loxone: Home Assistant schickt Messwerte an Earnie und holt Sollwerte über `status.json` ab. Earnie fragt keine Entity-Zustände per REST ab.

Den Vergleich von Loxone, HA und OpenEMS sowie den Wechsel des Backends beschreibt [Smarthome-Backend wählen](smarthome-backend-wahl.md). Das Entwickler-Setup (Compose, Token, Carrier) steht in der [HA-Lab Spec](../dev/ha-lab-setup.md).

## Pfad A2 (Standard) und Pfad B im Vergleich

| Pfad | Ziel | Bundle |
| --- | --- | --- |
| **A2 (Standard im DACH-Raum)** | Neues Setup oder Gateway-Setup mit dynamischen Tarifen, Wallbox, PV und Zähler | Earnie + Home Assistant + evcc (Compose) |
| **B (Bestand, Installed Base)** | Bestehendes Home Assistant | Earnie + YAML-Paket aus der Signalliste; evcc optional ergänzen |

> **Hinweis:** In der Dokumentation zur [Verbrauchs-CSV](../konfiguration/verbrauchs-csv.md) bezeichnen „Pfad A / Pfad B“ etwas anderes (Baseload-CSV). Hier geht es nur um die **Geräteanbindung**.

OpenEMS bleibt ein Prototyp für Labor und Industrie (**Pfad C**) und ist kein Standard für Privathaushalte: [OpenEMS-Lab](openems-lab.md).

## Compose starten (A2)

Verzeichnisse anlegen und den Lab-Stack starten:

```powershell
mkdir ha_lab\config, ha_lab\runtime, ha_lab\homeassistant, ha_lab\evcc
# ha_lab\evcc\evcc.yaml ist im Repo als Lab-Stub; bei Bedarf anpassen
docker compose --project-directory . -f docker/compose/ha-lab.yml up -d --build
```

| Service | URL |
| --- | --- |
| Earnie Streamlit | http://localhost:8506 |
| Home Assistant | http://localhost:8123 |
| evcc UI | http://localhost:7070 |

Earnie speichert seine Daten in `ha_lab/config/` und `ha_lab/runtime/`. Die HA-Konfiguration liegt in `ha_lab/homeassistant/`.

<a id="entity-mapping-human-in-the-loop"></a>

## Signale binden (YAML-Paket)

Earnie speichert keine HA-`entity_id`s. Die Komponenten tragen unter `ehal_bindings` nur **Aktivierungsschlüssel** ohne Wert: `plant.ehal_bindings`, `batteries[].ehal_bindings`, `consumers[].ehal_bindings` und `inverters[].ehal_bindings` (in `house_profiles.json`, für Speicher in `components.json`). Die Zuordnung zu echten Entities steht im YAML-Paket in Home Assistant.

**Voraussetzungen:**

- **Port `8541`:** Der Daemon-Port für den Push-Vertrag muss von Home Assistant aus erreichbar sein (`system.ehal_loxone_http_port`, Standard `8541`). Ohne diesen Port erreicht das YAML-Paket Earnie nicht.
- **Push-Token:** `EARNIE_PUSH_TOKEN` (Alias `EARNIE_PILOT_PUSH_TOKEN`) ist optional. Ist der Token gesetzt, muss er bei jedem Push mitgeschickt werden; ohne gesetztes Token akzeptiert Earnie Telemetrie ohne Authentifizierung (offenes LAN).

**Ablauf:**

1. Auf **Daemon Control → Smarthome-Backend** das Backend **Home Assistant** wählen und URL/Token eintragen. Die Seite setzt `ehal.backend=ha` und schreibt `EHAL_HA_*` in `config/.env`. Alternativ `ehal.backend` aus dem Snippet [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) übernehmen und die Zugangsdaten in `.env` setzen. Im Add-on übernimmt der Supervisor-Proxy URL und Token ([Home-Assistant-Add-on](homeassistant-addon.md)).
2. Haus und Komponenten im **Hauskonfigurator** speichern. Earnie aktiviert dabei die Pflichtsignale als leere Schlüssel in `ehal_bindings`. Für jede netzgekoppelte Hausbatterie gehört dazu auch die **Batterieleistung** (`ess.<id>.sens_ess_power`): Earnie leitet daraus die Anlagen-Batterieleistung ab, ohne sie bricht Live-Lesen ab. Bei einer bestehenden Konfiguration ergänzt die **Konfigurations-Migration** das Signal; danach das YAML-Paket neu herunterladen und den neuen Platzhalter `ENTITY_ess_<id>_sens_ess_power` belegen.
3. Auf **Daemon Control → EHAL-Com** die **Signalliste** prüfen. Die Liste zeigt den Signalvertrag: Pflicht, optional, aktiviert und Match-Status. Optionale Signale lassen sich dort zu- und abschalten.
4. Unter **HA Push-Carrier** das **YAML-Paket** herunterladen. Es enthält `ENTITY_*`-Platzhalter, den periodischen Push, den Heartbeat und den Abruf von `status.json`.
5. Das Paket in Home Assistant als Package einbinden und jeden `ENTITY_*`-Platzhalter durch die passende `entity_id` ersetzen. Der Push läuft periodisch (Standard 10 s), nicht nur bei Wertänderung.
6. Auf EHAL-Com mit **Live-Lesen** und **Live-Schreiben** prüfen, dass Werte ankommen und Sollwerte abgerufen werden.

> **Hinweis:** Der frühere Schlüssel `ehal.ha.transport` und die Zuordnung von HA-Entities in der Earnie-Oberfläche entfallen. Alte Configs bereinigt der Migrations-Assistent; gespeicherte `entity_id`s verwirft er, die Aktivierungsschlüssel bleiben erhalten.

Die Werte im Push sind bereits in EHAL-Einheiten (z. B. W, kWh, %). Die Umrechnung aus den HA-Einheiten übernimmt das YAML-Paket. In `config.json` bleiben unter `ehal.ha` nur die optionalen Einstellungen `sign` und `boolean_invert`.

**Optional – Ist-Werte je Slot:** Für Slot-Ist (ΔkWh → mittlere kW) auf der Anlage die Energiezähler `sens_pv_energy`, `sens_grid_energy_import` und `sens_grid_energy_export` in der Signalliste aktivieren und im YAML-Paket passende Entities eintragen (`device_class=energy`, bevorzugt `total_increasing`). Energiezähler nimmt Earnie bei ausbleibendem Push nie als 0 an.

**Weiterführend:**

- [EHAL-Com](../ui/ehal-com.md): Signalliste, YAML-Paket, Live-Lesen und Live-Schreiben (Englisch).
- [Home-Assistant-Add-on](homeassistant-addon.md): Earnie innerhalb von Home Assistant, Ports und Supervisor-Proxy.
- [EHAL-Spec § Home Assistant](../referenz/ehal.md#implementation-notes--home-assistant--evcc): Push-Vertrag, Token, Push-Takt und Einheiten auf der Leitung (Englisch).
- [Charts](../ui/charts.md): Darstellung der Ist-Werte.

### Wenn marq24 / evcc bereits in HA verbunden ist

**Voraussetzung:** Die Integration **evcc☀️🚘- Solar Charging** zeigt Geräte unter **Einstellungen → Geräte & Dienste**. Im Lab lautet die URL `http://evcc:7070`.

1. In HA unter **Entwicklerwerkzeuge → Zustände** die exakten `entity_id`s notieren (Filter z. B. `evcc`). Mit dem Lab-Stub (`ha_lab/evcc/evcc.yaml`) sind Leistungen oft **0 W** und der SoC **50 %**. Für den Pfadnachweis reicht das.
2. In Earnie (http://localhost:8506) auf **Smarthome-Backend** das Backend **Home Assistant** verbinden (setzt `ehal.backend=ha`). Danach Haus und Batterie im Hauskonfigurator speichern.
3. Auf **EHAL-Com** die Signalliste prüfen und das YAML-Paket herunterladen.
4. **Mindestens eintragen:** Netzleistung für `sens_grid_power_active`, PV für `sens_pv_production_active` und Batterie-SoC für `ess.{id}.sens_ess_soc` (auf der Batterie, nicht flach auf der Anlage). Optional: Batterie- und Ladeleistung, Maxstrom (`number`).
5. **Vorzeichen:** Im EHAL bedeutet Netz **+** Bezug und ESS **+** Entladen. Weicht die Integration davon ab, **negate** setzen (unter `ehal.ha.sign`).
6. **Erfolg:** Live-Lesen zeigt die Werte, `config.json` enthält `ehal.backend=ha` und die Signalliste meldet die Pflichtsignale als aktiviert. Der Live-Betrieb läuft ohne die Meldung „Kein Zugriff auf EHAL SoC“.

Eine Schritt-für-Schritt-Anleitung (Englisch, inkl. Abnahmetabelle) steht in der [HA-Lab Spec §5.1](../dev/ha-lab-setup.md#51-after-marq24-ha-evcc-is-connected-lab-follow-up). Installation der Integration: [§3.5 Option 2](../dev/ha-lab-setup.md#35-expose-evcc-entities-into-home-assistant).

## Optimizer-Exklusivität (Checkliste)

Lokale Strategien des Hubs für Überschuss, Preise oder Laden dürfen Earnies 48-h-Fahrplan nicht überschreiben:

- [ ] In **evcc** ist keine eigenständige Surplus- oder Spotpreis-Ladeplanung aktiv (kein Smart Cost, kein konkurrierender Planner).
- [ ] Der Loadpoint ist so eingestellt, dass Earnie den Maxstrom (HA-`number`-Entity) setzen kann.
- [ ] Keine HA-Automation schreibt auf dieselben Setpoint-Entities wie die Automationen aus dem Earnie-YAML-Paket.
- [ ] Spotpreise und Fahrpläne kommen aus **Earnie**, nicht aus dem Hub.

## Modbus-Regel

Pro physischem Bus bzw. Gerät gibt es genau **einen** schreibenden Southbound-Owner, also das System, das Sollwerte an das Gerät sendet. Typisch ist das **evcc** *oder* eine HA-Integration inkl. Proxy. Auf demselben Wechselrichter keine parallelen Modbus-Clients betreiben.

## Pfad B (bestehendes HA)

1. Earnie so betreiben, dass Home Assistant den Daemon-Port `8541` erreicht und Earnie die HA-URL erreicht (Docker-Netz / Host-IP). Den Push-Token setzen.
2. Signalliste und YAML-Paket wie oben nutzen: native HA-Entities (Long-Tail) in die `ENTITY_*`-Platzhalter eintragen, evcc optional.
3. Dieselbe Checkliste zur Optimizer-Exklusivität und die Modbus-Regel anwenden.

## Stop

Lab-Stack beenden:

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml down
```
