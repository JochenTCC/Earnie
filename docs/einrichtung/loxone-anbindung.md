# Loxone-Anbindung

Earnie kommuniziert mit dem Loxone Miniserver über **HTTP**:

- **Telemetrie:** Der Miniserver schickt Messwerte per Virtual Output (VO) in die Push-Inbox von Earnie.
- **Sollwerte und Freigaben:** Earnie legt sie in `status.json` ab. Der Miniserver liest sie per Virtual Input (VI) und fragt etwa alle 10 s ab.

Die eigentliche Schaltlogik (Wechselrichter, Wallbox, Pool, …) ist in Loxone implementiert und liegt damit außerhalb von Earnie.

Für andere Hubs (HA + evcc, OpenEMS) gilt: [Smarthome-Backend wählen](smarthome-backend-wahl.md).

Die **Einrichtung** beschreibt [Loxone-Signale und Vorlagen](../referenz/loxone-signals.md):

- **Zähler:** Zähler am EFM anlegen.
- **Vorlagen:** Virtual-In/Out-Vorlagen auf EHAL-Com aus der Signalliste exportieren und in Loxone Config einspielen. Earnie erzeugt sie passend zur aktuellen Konfiguration.
- **Rückfallebene und Import:** Verhalten bei ausgefallenem Earnie und Import der Struktur.

## Zugangsdaten (`config/.env`)

| Variable      | Bedeutung                                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| `LOXONE_IP`   | IP-Adresse des Miniservers; optional mit HTTP-Port (`192.168.178.1:85`, Standard ohne Angabe: Port 80) |
| `LOXONE_USER` | Benutzername (HTTP Basic Auth)                                                                         |
| `LOXONE_PASS` | Passwort                                                                                               |

Im Produktivbetrieb (Docker) legt der Container-Start (Entrypoint) eine fehlende `config/.env` aus der Vorlage an. Die Werte werden danach unter **Smarthome-Backend → Anbindung** eingetragen oder direkt in der Datei gesetzt. Lokal ohne Container: [.env.example](../../.env.example) nach `config/.env` kopieren, sofern die Datei noch fehlt.

Lehnt der Miniserver die Zugangsdaten ab (HTTP **401** oder **403**), pausiert der Optimierer-Dienst (`main.py`) alle Miniserver-Zugriffe. Die Web-Oberfläche zeigt dann einen Fehlerhinweis. Abhilfe: IP, Benutzer und Passwort unter **Smarthome-Backend → Anbindung** korrigieren und die Merker erneut testen.

## HTTP-Schnittstelle

- **Lesen (Live):** Loxone schickt Messwerte per Virtual Output an Earnie. Dazu ruft der Miniserver `GET /ehal/telemetry/<EHAL-ID>/<v>` auf dem Port des Optimierer-Dienstes auf (typisch **8541**).
- **Schreiben (Loud):** Sollwerte erscheinen in `status.json` unter qualifizierten EHAL-IDs. Der Miniserver liest sie per Virtual Input.
- **Import / Struktur:** `GET http://{LOXONE_IP}/data/LoxAPP3.json` liefert die sichtbaren Control-Namen. Earnie nutzt sie für den Loxone-Import (Greenfield inkl. EFM-Zähler) und für die Presence-Probe auf EHAL-Com. Live-Telemetrie und Sollwerte laufen nicht über diese Datei.

Aktivierte Signale stehen als Schlüssel in `plant.ehal_bindings`, `consumers[].ehal_bindings` bzw. `batteries[].ehal_bindings`. Die Werte zu den Schlüsseln bleiben leer, der Schlüssel dient nur als Aktivierungsflag. Die verbindliche Signalliste und den Match-Status zeigt die Seite **EHAL-Com → Signalliste**. Details: [Loxone-Signale](../referenz/loxone-signals.md).

## Was Earnie liest

| Bereich              | Konfiguration                                | Zweck                                             |
| -------------------- | -------------------------------------------- | ------------------------------------------------- |
| Anlage (Plant)       | `plant.ehal_bindings`                        | Netz-/PV-Leistungen, Außentemperatur              |
| Speicher (ESS)       | `batteries[].ehal_bindings` (`ess.{slug}.*`) | SOC, ESS-Leistung, Grenzen und Sollwerte          |
| Steuer-Rückmeldung   | dieselben Soll-/Ist-Bindings (Live-Lesen)    | Prüfen, ob Schreiben ankommt                      |
| Flexible Verbraucher | `consumers[].ehal_bindings`                  | Live-Leistung / Freigaben für `cons_data`         |
| E-Auto-Status        | EVCS-Felder in `ehal_bindings` / Ladeplan    | Anschluss, Rest-SOC, Fertig-um, max. Ladeleistung |

Die PV-Energie je Intervall ergibt sich aus dem Integral über `sens_pv_production_active`.

## Was Earnie schreibt

| Signal                              | Konfiguration                                                     | Wirkung (Schnittstelle)                                                                                                                             |
| ----------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| ESS-Sollleistung                    | `batteries[].ehal_bindings.set_ess_active_power` (`ess.{slug}.*`) | kW; `+` = Entladung, `−` = Ladung; bei Automatik weglassen / 0                                                                                      |
| Ladegrenze                          | `batteries[].ehal_bindings.set_ess_charge_power_limit`            | kW; echte max. Ladeleistung                                                                                                                         |
| Entladegrenze                       | `batteries[].ehal_bindings.set_ess_discharge_power_limit`         | kW; echte max. Entladeleistung                                                                                                                      |
| Steuerbefehl / ESS-Modus            | `batteries[].ehal_bindings.set_ess_mode`                          | **Pflicht bei jedem Zyklus:** `0` = Automatik (Sollleistung ignorieren), `1` = Zwangsladen/Entladesperre, `2` = Zwangs-Entladen (nur Batterie)      |
| Einspeisegrenze (outbound)          | `plant.ehal_bindings.set_grid_export_power_limit`                 | kW, Betrag ≥ 0; harte Obergrenze für die Netz-Einspeisung; `0` = keine Einspeisung; Wert ohne Begrenzung: siehe [Einspeisegrenze](../konfiguration/batterie-pv.md#einspeisegrenze) |
| Einspeisegrenze (inbound, optional) | `plant.ehal_bindings.get_grid_export_power_limit`                 | kW; variable Grenze vom Netz/HEMS an Earnie                                                                                                         |
| Verbraucher-Freigabe                | `consumers[].ehal_bindings` (Flex enable)                         | `0` = gesperrt, `1` = Freigabe (SwimSpa, Wärmepumpe, Filter)                                                                                        |
| E-Auto Sollstrom                    | `ehal_bindings.set_evcs_max_current`                              | Ziel-Ladestrom / -leistung                                                                                                                          |
| E-Auto PV-Follow                    | `ehal_bindings` / `set_evcs_mode`                                 | `0`/`1` bzw. Modus                                                                                                                                  |

### Batteriesteuerung

- **Zwangsladen und -entladen:** Beides läuft über `set_ess_active_power`. Lade- und Entladegrenze sind echte Obergrenzen.
- **Automatik:** Virtual-In-Werte sind **sticky**, der letzte Wert bleibt am Miniserver stehen. Automatik bedeutet deshalb `set_ess_mode = 0`; eine weggelassene Sollleistung reicht dafür nicht. Loxone Config muss `Steuerbefehl = 0` als Freigabe bzw. Automatik behandeln, auch wenn der Virtual Input für `set_ess_active_power` (im optionalen Namenskatalog `Earnie_Batterie_Sollleistung`) noch einen alten Wert hält.
- **Pro Speicher:** Die ESS-Bindings liegen je Speicher entity-scoped unter `ess.{slug}.*` in `batteries[].ehal_bindings`. Der Steuerbefehl (`set_ess_mode`) gilt pro Batterie und signalisiert keine Einspeisebegrenzung.

### Einspeisegrenze in Loxone Config

In Loxone Config wird `set_grid_export_power_limit` als Abregelung (Curtailment) des Wechselrichters umgesetzt, am einfachsten als `MIN(Limit; WR-Nennleistung)`. Der Wert `0` bedeutet Einspeisesperre. Wie Earnie die wirksame Grenze und den Wert ohne Begrenzung berechnet, steht unter [Einspeisegrenze](../konfiguration/batterie-pv.md#einspeisegrenze).

### Vorzeichenkonvention (verbindlich)

Alle Leistungen, die *ins Haus* fließen, sind positiv. Ohne Wechselrichterverluste gilt:

```
P_cons = P_PV + P_Grid + P_Bat
```

| Größe    | EHAL-Feld (Wire-ID)                 | `+`       | `−`         |
| -------- | ----------------------------------- | --------- | ----------- |
| `P_PV`   | `sens_pv_production_active`         | Erzeugung | – (≥ 0)     |
| `P_Grid` | `grid.meter.sens_grid_power_active` | Bezug     | Einspeisung |
| `P_Bat`  | `ess.{id}.sens_ess_power`           | Entladen  | Laden       |
| `P_cons` | `sens_power_consumers`              | Verbrauch | – (≥ 0)     |

Die Werte kommen per Virtual Output unter der qualifizierten EHAL-ID in Earnie an (Vorlagen `VO_Earnie_*`, siehe [Loxone-Signale](../referenz/loxone-signals.md)). Namen wie `Earnie_Netzleistung` sind nur ein optionaler Namenskatalog.

Earnie speichert den Push zunächst unverändert. Erst beim Lesen rechnet Earnie den Hub-Wert in den EHAL-Wert um. Grundlage sind die `loxone`-Blöcke in den Rollen (`share/ehal/roles/*.json`) mit `factor` (z. B. kW → W) und `sign`. Die Vorzeichenkonvention oben gilt für den EHAL-Wert nach dieser Umrechnung.

Manche Geräte liefern entgegengesetzte Vorzeichen, z. B. Huawei-Register 37113 (Netz, `+` = Einspeisung) und 37765 (Batterie, `+` = Laden). Für solche Werte gibt es zwei Wege:

- **In Loxone Config:** Das Vorzeichen so drehen, dass der VO den von der Rolle erwarteten Hub-Wert liefert.
- **In der Rolle:** Ein passendes `sign` setzen (Standard für Loxone-Leistungen: `sign: 1`).

Historische Verbrauchsdaten kommen über CSV-Upload, Energiemonitor bzw. `cons_data`. Ein FTP-Log vom Miniserver wird nicht mehr genutzt.

## Verbindung prüfen

```powershell
# Lesen aller konfigurierten IOs
python -m scripts.verify_loxone_setup
```

Das Skript liest nur die Push-Inbox (Werte, die der Miniserver per Virtual Output an Earnie schickt). Jede Prüfung meldet `[OK]`, `[WARNUNG]` oder `[FEHLER]` mit EHAL-ID und Detailtext. Typische Meldungen:

- `[WARNUNG]` „Kein frischer Push-Inbox-Wert“: Das Signal ist aktiviert, aber vom Miniserver ist noch nichts angekommen. Prüfen Sie den VO-Export aus der Signalliste (Hinweis „Signalliste → Export“) und ob der Virtual Output sendet.
- `[FEHLER]` „Kein Push-Inbox-Wert (kein Mapping …)“: Für das Signal gibt es kein gültiges Mapping.
- `[FEHLER]` „IO-Name fehlt“: In der Konfiguration ist für das Signal kein Name eingetragen.

Warnungen lassen das Gesamtergebnis grün. Die Schreibrichtung (`status.json`, Abruf durch die Virtual Inputs) prüft das Skript nicht. Dafür dient der Schreibtest auf **EHAL-Com**.

Alternativ lässt sich die Verbindung in der Web-Oberfläche prüfen, auf der Seite **Smarthome-Backend** im Bereich Anbindung.

## Datenfluss (Überblick)

```
Loxone Miniserver                    Earnie
─────────────────                    ────────────────
Telemetrie (VO push / Inbox)  ──►   main.py liest
E-Auto-Status, Flex-Leistung  ──►   Optimierung (MILP)
                                     │
Virtuelle Eingänge (VI)       ◄──   status.json (push-only)
  poll ~10 s, qualified Checks ◄──   Freigaben / ESS / EV-Soll
```

Der Optimierer-Dienst (`main.py`) betreibt den HTTP-Empfänger auf Port 8541, schreibt `status.json` und pflegt die Push-Inbox.

Die Web-Oberfläche (Streamlit) liest Live-Werte für die Anzeige (Sankey, SOC) aus diesen Dateien bzw. aus dem letzten Durchlauf. Im Normalbetrieb steuert sie den Miniserver nicht. Ausnahmen sind Verbindungsprüfung, Loxone-Import und Diagnosen auf **Smarthome-Backend** und **EHAL-Com**; diese Funktionen sprechen den Miniserver direkt an. Mehr zum Schreibpfad: [EHAL-Com – Write push-only](../ui/ehal-com.md#write-push-only).
