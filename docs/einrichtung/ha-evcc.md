# Home Assistant + evcc

Earnie nutzt Home Assistant als Geräteanbindung (Southbound): Home Assistant liest Zähler, Wechselrichter, Batterie und Wallbox aus und setzt die Sollwerte von Earnie um. **evcc** kann dabei als Sidecar unter Home Assistant laufen und liefert typische Entities für Wallbox, Zähler und Wechselrichter.

Den Datenaustausch übernimmt das **Push-Verfahren**: Home Assistant schickt Messwerte an Earnie und holt Sollwerte über `status.json` ab. Welche Entity zu welchem Signal gehört, steht in einem **YAML-Paket**, das Earnie erzeugt und das in Home Assistant eingebunden wird.

Den Vergleich mit anderen Smarthome-Backends beschreibt [Smarthome-Backend wählen](smarthome-backend-wahl.md).

## Ausgangslagen

Die Einrichtung ist in beiden Fällen dieselbe. Unterschiedlich ist nur, woher die Entities kommen:

- **Neues Setup:** Home Assistant und evcc werden zusammen mit Earnie aufgesetzt, typisch für Anlagen mit dynamischem Tarif, Wallbox, PV und Zähler. evcc bindet Wallbox und Zähler an, Home Assistant reicht die Entities an Earnie weiter. Das ist die Empfehlung für neue Setups im DACH-Raum.
- **Bestehendes Home Assistant:** Die Geräte sind bereits in Home Assistant eingebunden. Earnie nutzt die vorhandenen Entities; evcc lässt sich bei Bedarf ergänzen.

Wo Earnie läuft, ist davon unabhängig: als [Home-Assistant-Add-on](homeassistant-addon.md) oder separat, z. B. per Docker Compose ([Container](container.md)).

## Voraussetzungen

- **Port `8541`:** Der Daemon-Port für das Push-Verfahren muss von Home Assistant aus erreichbar sein (`system.ehal_http_port`, Standard `8541`). Läuft Earnie außerhalb von Home Assistant, braucht Home Assistant dafür die Host-IP bzw. den Container-Namen von Earnie.
- **Push-Token:** `EARNIE_PUSH_TOKEN` (Alias `EARNIE_PILOT_PUSH_TOKEN`) ist optional. Ist der Token gesetzt, muss er bei jedem Push mitgeschickt werden; ohne gesetztes Token akzeptiert Earnie Telemetrie ohne Authentifizierung (offenes LAN).

<a id="entity-mapping-human-in-the-loop"></a>

## Einrichtung

Die Komponenten tragen unter `ehal_bindings` nur **Aktivierungsschlüssel** ohne Wert: `plant.ehal_bindings` und `consumers[].ehal_bindings` (in `house_profiles.json`) sowie `batteries[].ehal_bindings`, `inverters[].ehal_bindings` und `pv_systems[].ehal_bindings` (in `components.json`). Die Zuordnung zu echten Entities steht im YAML-Paket in Home Assistant.

1. Auf **Daemon Control → Smarthome-Backend** das Backend **Home Assistant** wählen. Die Seite setzt `ehal.backend=ha`. Alternativ `ehal.backend` aus dem Snippet [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) übernehmen.
2. Haus und Komponenten im **Hauskonfigurator** speichern. Earnie aktiviert dabei die Pflichtsignale als leere Schlüssel in `ehal_bindings`. Für jede netzgekoppelte Hausbatterie gehört dazu auch die **Batterieleistung** (`ess.<id>.sens_ess_power`): Earnie leitet daraus die Anlagen-Batterieleistung ab, ohne sie bricht Live-Lesen ab. Bei einer bestehenden Konfiguration ergänzt die **Konfigurations-Migration** das Signal; danach das YAML-Paket neu herunterladen und den neuen Platzhalter `ENTITY_ess_<id>_sens_ess_power` belegen.
3. Auf **Daemon Control → EHAL-Com** die **Signalliste** prüfen. Die Liste zeigt den Signalvertrag: Pflicht, optional, aktiviert und Match-Status. Optionale Signale lassen sich dort zu- und abschalten.
4. Unter **HA Push-Carrier** das **YAML-Paket** herunterladen. Es enthält `ENTITY_*`-Platzhalter, den periodischen Push, den Heartbeat und den Abruf von `status.json`.
5. In Home Assistant unter **Entwicklerwerkzeuge → Zustände** die passenden `entity_id`s heraussuchen. Das Paket als Package einbinden und jeden `ENTITY_*`-Platzhalter durch die passende `entity_id` ersetzen (siehe [Mindestsignale](#mindestsignale)). Der Push läuft periodisch (Standard 10 s), nicht nur bei Wertänderung.
6. Auf EHAL-Com mit **Live-Lesen** und **Live-Schreiben** prüfen, dass Werte ankommen und Sollwerte abgerufen werden. Die Einrichtung ist abgeschlossen, wenn die Signalliste die Pflichtsignale als aktiviert meldet und der Live-Betrieb ohne die Meldung „Kein Zugriff auf EHAL SoC“ läuft.

Die Werte im Push sind bereits in EHAL-Einheiten (z. B. W, kWh, %). Die Umrechnung aus den HA-Einheiten übernimmt das YAML-Paket. In `config.json` stehen unter `ehal.ha` nur die optionalen Einstellungen `sign` und `boolean_invert`.

### Mindestsignale

- Netzleistung für `sens_grid_power_active`.
- PV-Leistung je Wechselrichter für `inv.{id}.sens_inv_power_pv` (Pflicht, sobald am Wechselrichter PV hängt; die Anlagen-PV leitet Earnie daraus ab).
- Batterie-SoC für `ess.{id}.sens_ess_soc` und Batterieleistung für `ess.{id}.sens_ess_power` (beide auf der Batterie, nicht flach auf der Anlage).

Optional: Ladeleistung der Wallbox und Maxstrom (`number`-Entity) als Schreibweg.

**Vorzeichen:** Im EHAL bedeutet Netz **+** Bezug und ESS **+** Entladen. Weicht die Integration davon ab, **negate** setzen (unter `ehal.ha.sign`).

**Ist-Werte je Slot:** Die Ist-Werte je Viertelstunde (z. B. für die [Charts](../ui/charts.md)) berechnet Earnie aus den gepushten Leistungswerten. Sie werden alle 30 s abgetastet und über die Viertelstunde gemittelt. Zusätzliche Energiezähler sind dafür nicht nötig.

## evcc einbinden

In Home Assistant stellt die Integration **evcc☀️🚘- Solar Charging** die Geräte von evcc als Entities bereit. Sie erscheinen unter **Einstellungen → Geräte & Dienste**. Die `entity_id`s findet man unter **Entwicklerwerkzeuge → Zustände** mit dem Filter `evcc`. Sie werden wie alle anderen Entities in die `ENTITY_*`-Platzhalter des YAML-Pakets eingetragen.

Damit evcc und Earnie sich nicht in die Quere kommen, gilt die folgende Checkliste.

### Optimizer-Exklusivität (Checkliste)

Lokale Strategien des Hubs für Überschuss, Preise oder Laden dürfen Earnies 48-h-Fahrplan nicht überschreiben:

- [ ] In **evcc** ist keine eigenständige Surplus- oder Spotpreis-Ladeplanung aktiv (kein Smart Cost, kein konkurrierender Planner).
- [ ] Der Loadpoint ist so eingestellt, dass Earnie den Maxstrom (HA-`number`-Entity) setzen kann.
- [ ] Keine HA-Automation schreibt auf dieselben Setpoint-Entities wie die Automationen aus dem Earnie-YAML-Paket.
- [ ] Spotpreise und Fahrpläne kommen aus **Earnie**, nicht aus dem Hub.

## Modbus-Regel

Pro physischem Bus bzw. Gerät gibt es genau **einen** schreibenden Southbound-Owner, also das System, das Sollwerte an das Gerät sendet. Typisch ist das **evcc** *oder* eine HA-Integration inkl. Proxy. Auf demselben Wechselrichter keine parallelen Modbus-Clients betreiben.

## Weiterführend

- [EHAL-Com](../ui/ehal-com.md): Signalliste, YAML-Paket, Live-Lesen und Live-Schreiben (Englisch).
- [Home-Assistant-Add-on](homeassistant-addon.md): Earnie innerhalb von Home Assistant, Ports und Supervisor-Proxy.
- [EHAL-Spec § Home Assistant](../referenz/ehal.md#implementation-notes--home-assistant--evcc): Push-Verfahren, Token, Push-Takt und Einheiten auf der Leitung (Englisch).
- [Charts](../ui/charts.md): Darstellung der Ist-Werte.
- Für Entwickler: Lab-Stack mit Home Assistant und evcc per Compose, Installation der evcc-Integration und Abnahmetabelle in der [HA-Lab Spec](../dev/ha-lab-setup.md) (Englisch).
