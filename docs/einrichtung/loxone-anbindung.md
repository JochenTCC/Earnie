# Loxone-Anbindung

Earnie kommuniziert mit dem Loxone Miniserver über **HTTP**:

- **Telemetrie:** Der Miniserver schickt Messwerte per Virtual Output (VO) in die Push-Inbox von Earnie.
- **Sollwerte und Freigaben:** Earnie legt sie in `status.json` ab. Der Miniserver liest sie per Virtual Input (VI) und fragt etwa alle 10 s ab.

Die eigentliche Schaltlogik in Loxone (Wechselrichter, Wallbox, Pool, …) liegt außerhalb von Earnie.

Andere Hubs (HA + evcc, OpenEMS): [Smarthome-Backend wählen](smarthome-backend-wahl.md).

**Standard-Einrichtung mit der Earnie-Library:** Virtual-In/Out-Vorlagen einspielen, Zähler am EFM anlegen, Rückfallebene bei ausgefallenem Earnie und Import – beschrieben unter [Loxone-Signale und Earnie-Library](../referenz/loxone-signals.md).

## Zugangsdaten (`config/.env`)

| Variable      | Bedeutung                              |
| ------------- | -------------------------------------- |
| `LOXONE_IP`   | IP-Adresse des Miniservers; optional mit HTTP-Port (`192.168.178.1:85`, Standard ohne Angabe: Port 80) |
| `LOXONE_USER` | Benutzername (HTTP Basic Auth)         |
| `LOXONE_PASS` | Passwort                               |

Vorlage: [.env.example](../../.env.example) nach `config/.env` kopieren. Im Produktivbetrieb (Docker) legt der Container-Start (Entrypoint) die Datei selbst an.

Die Zugangsdaten lassen sich auch über die Web-Oberfläche eingeben.

Lehnt der Miniserver die Zugangsdaten ab (HTTP **401** oder **403**), pausiert der Optimierer-Dienst (`main.py`) alle Miniserver-Zugriffe. Die Web-Oberfläche zeigt dann einen Fehlerhinweis. Abhilfe: IP, Benutzer und Passwort unter **Smarthome-Backend → Anbindung** korrigieren und die Merker erneut testen.

## HTTP-Schnittstelle

- **Lesen (Live):** Loxone schickt Messwerte per Virtual Output an Earnie, und zwar per `GET /ehal/telemetry/<EHAL-ID>/<v>` auf den Daemon-Port (typisch **8541**). Für bestehende VOs gilt der Alias `/ehal/loxone/telemetry/…`. Earnie fragt den Miniserver **nicht** mehr per HTTP nach Merkern ab.
- **Schreiben (Loud):** Sollwerte erscheinen in `status.json` unter qualifizierten EHAL-IDs. Der Miniserver liest sie per Virtual Input.
- **Struktur und Import:** `GET http://{LOXONE_IP}/data/LoxAPP3.json` liefert die Control-Namen für Mapping und Import.

Aktivierte Signale stehen als Schlüssel in `plant.ehal_bindings`, `consumers[].ehal_bindings` bzw. `batteries[].ehal_bindings`. Die Werte bleiben leer, der Schlüssel dient nur als Aktivierungsflag. Vertrag und Match-Status zeigt **EHAL-Com → Signalliste**. Details: [Loxone-Signale](../referenz/loxone-signals.md).

<a id="was-der-optimizer-liest"></a>

## Was Earnie liest

| Bereich              | Konfiguration                                      | Zweck                                             |
| -------------------- | -------------------------------------------------- | ------------------------------------------------- |
| Anlage (Plant)       | `plant.ehal_bindings`                              | Netz-/PV-Leistungen, Außentemperatur              |
| Speicher (ESS)       | `batteries[].ehal_bindings` (`ess.{slug}.*`)       | SOC, ESS-Leistung, Grenzen und Sollwerte          |
| Steuer-Rückmeldung   | dieselben Soll-/Ist-Bindings (Live-Lesen)          | Prüfen, ob Schreiben ankommt                      |
| Flexible Verbraucher | `consumers[].ehal_bindings`                        | Live-Leistung / Freigaben für `cons_data`         |
| E-Auto-Status        | EVCS-Felder in `ehal_bindings` / Ladeplan          | Anschluss, Rest-SOC, Fertig-um, max. Ladeleistung |

<a id="was-der-optimizer-schreibt"></a>

## Was Earnie schreibt

| Signal               | Konfiguration                                             | Wirkung (Schnittstelle)                                                 |
| -------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| ESS-Sollleistung     | `batteries[].ehal_bindings.set_ess_active_power` (`ess.{slug}.*`) | kW; `+` = Entladung, `−` = Ladung; bei Automatik weglassen / 0          |
| Ladegrenze           | `batteries[].ehal_bindings.set_ess_charge_power_limit` | kW; echte max. Ladeleistung                                             |
| Entladegrenze        | `batteries[].ehal_bindings.set_ess_discharge_power_limit` | kW; echte max. Entladeleistung                                          |
| Steuerbefehl / ESS-Modus | `batteries[].ehal_bindings.set_ess_mode` | **Pflicht bei jedem Zyklus:** `0` = Automatik (Sollleistung ignorieren), `1` = Zwangsladen/Entladesperre, `2` = Zwangs-Entladen (nur Batterie) |
| Einspeisegrenze (outbound) | `plant.ehal_bindings.set_grid_export_power_limit` | kW, Betrag ≥ 0; harte Obergrenze für die Netz-Einspeisung; `0` = keine Einspeisung; Wert ohne Begrenzung: siehe [Einspeisegrenze](#einspeisegrenze) |
| Einspeisegrenze (inbound, optional) | `plant.ehal_bindings.get_grid_export_power_limit` | kW; variable Grenze vom Netz/HEMS an Earnie |
| Verbraucher-Freigabe | `consumers[].ehal_bindings` (Flex enable) | `0` = gesperrt, `1` = Freigabe (SwimSpa, Wärmepumpe, Filter)            |
| E-Auto Sollstrom     | `ehal_bindings.set_evcs_max_current` | Ziel-Ladestrom / -leistung                                              |
| E-Auto PV-Follow     | `ehal_bindings` / `set_evcs_mode`          | `0`/`1` bzw. Modus                                                      |

### Batteriesteuerung

- **Entfallene Rollen:** Die früheren Rollen `target_soc_name` und `pv_counter_name` gibt es nicht mehr.
- **Zwangsladen und -entladen:** Beides läuft über `set_ess_active_power`. Lade- und Entladegrenze sind echte Obergrenzen.
- **Automatik:** Virtual-In-Werte sind **sticky**, der letzte Wert bleibt am Miniserver stehen. Automatik bedeutet deshalb `set_ess_mode = 0`; eine weggelassene Sollleistung reicht dafür nicht.
- **Pro Speicher:** ESS-Bindings liegen je Speicher entity-scoped unter `ess.{slug}.*` in `batteries[].ehal_bindings`. Der Steuerbefehl (`set_ess_mode`) gilt pro Batterie und signalisiert keine Einspeisebegrenzung.
- **PV-Energie:** Die PV-Energie je Intervall ergibt sich aus dem Integral über `sens_pv_production_active`.

### Einspeisegrenze

Eine statische Obergrenze lässt sich optional im Hauskonfigurator setzen (`plant.max_export_power_kw`). Die wirksame Obergrenze ist das Minimum aus:

- dem Wert aus dem Hauskonfigurator,
- der inbound-Grenze über EHAL,
- **0**, wenn der Einspeisetarif negativ ist (Einspeisung kostet dann Geld).

In Loxone Config wird `set_grid_export_power_limit` als Abregelung (Curtailment) des Wechselrichters umgesetzt, am einfachsten als `MIN(Limit; WR-Nennleistung)`. `0` bedeutet Einspeisesperre.

Ohne Begrenzung schreibt Earnie die maximal mögliche Einspeisung der Anlage. Dafür summiert Earnie über alle netzgekoppelten Wechselrichter `min(max_ac_power_kw, PV-kWp begrenzt durch max_pv_input_kw + Zwangsentlade-kW)`:

- **Insel-Wechselrichter** zählen nicht.
- **Ohne geplante Wechselrichter** gilt die bisherige Rechnung (Legacy): Summe PV-kWp plus max. Entladeleistung der Batterien mit `Batteriesteuerung = voll`. Batterien mit `limits_only` oder `read_only` zählen nicht.
- **Sind beide unbekannt,** steht `1000` kW im Status.

### Vorzeichenkonvention (verbindlich)

Alle Leistungen, die *ins Haus* fließen, sind positiv. Ohne Wechselrichterverluste gilt:

```
P_cons = P_PV + P_Grid + P_Bat
```

| Größe | EHAL-Feld (Wire-ID) | `+` | `−` |
|---|---|---|---|
| `P_PV` | `sens_pv_production_active` | Erzeugung | – (≥ 0) |
| `P_Grid` | `grid.meter.sens_grid_power_active` | Bezug | Einspeisung |
| `P_Bat` | `ess.{id}.sens_ess_power` | Entladen | Laden |
| `P_cons` | `sens_power_consumers` | Verbrauch | – (≥ 0) |

Die Werte kommen per Virtual Output unter der qualifizierten EHAL-ID in Earnie an (Vorlagen `VO_Earnie_*`, siehe [Loxone-Signale](../referenz/loxone-signals.md)). Die Namen `Earnie_Netzleistung` u. a. sind nur ein optionaler Namenskatalog.

Earnie dreht keine Vorzeichen, die Virtual Outputs müssen die Werte bereits in dieser Konvention liefern. Huawei-Register haben teils andere Vorzeichen, die in Loxone gedreht werden müssen: 37113 (Netz, `+` = Einspeisung) und 37765 (Batterie, `+` = Laden).

Historische Verbrauchsdaten kommen über CSV-Upload, Energiemonitor bzw. `cons_data`. Ein FTP-Log vom Miniserver wird nicht mehr genutzt.

### Umsetzung in Loxone

Wann die Anlage tatsächlich lädt, entscheidet die Loxone-Logik hinter diesen virtuellen Eingängen. Loxone Config muss `Steuerbefehl = 0` als Freigabe bzw. Automatik behandeln, auch wenn `Earnie_Batterie_Sollleistung` noch einen alten Wert hält.

## Verbindung prüfen

```powershell
# Lesen aller konfigurierten IOs
python -m scripts.verify_loxone_setup
```

Jede Prüfung meldet `[OK]` oder `[FEHLER]` mit EHAL-ID und Detailtext. Typische Fehler:

- Das Signal fehlt in der Push-Inbox.
- Der Miniserver-Callback auf `status.json` fehlt.
- Der Benutzer hat nicht die nötigen Rechte.

Die Verbindung lässt sich auch in der Web-Oberfläche prüfen, auf der Seite **Smarthome-Backend** (Bereich Anbindung).

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

Die Web-Oberfläche (Streamlit) liest Live-Werte für die Anzeige (Sankey, SOC). Die Optimierung übernimmt sie aus dem letzten Durchlauf des Optimierer-Dienstes (`main.py`). Zum Schreibpfad: [EHAL-Com – Write push-only](../ui/ehal-com.md#write-push-only).
