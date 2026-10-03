# Loxone-Anbindung

Earnie kommuniziert mit dem Loxone Miniserver über **HTTP** (Lesen und Schreiben von Werten). Die konkrete Schaltlogik in Loxone (Wechselrichter (Batteriespeicher), Wallbox, Pool, ...) liegt außerhalb von Earnie — der Optimizer liefert Sollwerte und Freigaben.

Andere Hubs (HA+evcc, OpenEMS): [Smarthome-Backend wählen](smarthome-backend-wahl.md).

**Default / Library:** Virtual-In/Out-Vorlagen einspielen, Zähler am EFM, Earnie-tot-Fallback und Import: [Loxone-Signale und Earnie-Library](../referenz/loxone-signals.md).

## Zugangsdaten (`config/.env`)


| Variable      | Bedeutung                              |
| ------------- | -------------------------------------- |
| `LOXONE_IP`   | IP-Adresse des Miniservers; optional mit HTTP-Port (`192.168.178.1:85`, Standard ohne Angabe: Port 80) |
| `LOXONE_USER` | Benutzername (HTTP Basic Auth)         |
| `LOXONE_PASS` | Passwort                               |


Vorlage: [.env.example](../../.env.example) → nach `config/.env` kopieren (Prod/Docker legt der Entrypoint die Datei an). 

Die Zugangsdaten können auch bequem über die Web-Oberfläche eingegeben werden.

Bei abgelehnten Zugangsdaten (HTTP **401** oder **403**) pausiert der Optimierer (`main.py`) die Miniserver-Zugriffe und zeigt in der Web-Oberfläche einen Fehlerhinweis. Korrigieren Sie IP, Benutzer und Passwort unter **Smarthome-Backend → Anbindung** und testen Sie die Merker erneut.

## HTTP-Schnittstelle

- **Lesen:** `GET http://{LOXONE_IP}/jdev/sps/io/{Name}`
- **Schreiben:** `POST` auf dieselbe URL mit dem Zielwert

Antworten liefern den Wert unter `LL.value`. Loxone gibt Zahlen oft **mit Einheit** zurück (z. B. `3.5 kW`, `72 %`, `16 A`). Der Optimizer parst diese Strings und ignoriert die Einheit für die Berechnung.

Merker-Namen liegen in `plant.ehal_bindings` / `consumers[].ehal_bindings` (Hausprofil) — siehe [Loxone-Signale](../referenz/loxone-signals.md). Zuordnung in der UI: **EHAL-Com**.

## Was der Optimizer liest


| Bereich              | Konfiguration                                      | Zweck                                             |
| -------------------- | -------------------------------------------------- | ------------------------------------------------- |
| Anlage (Plant)       | `plant.ehal_bindings`                              | SOC, Netz/PV/ESS-Leistungen, Außentemperatur      |
| Steuer-Rückmeldung   | dieselben Soll-/Ist-Merker                         | Prüfen, ob Schreiben ankommt                      |
| Flexible Verbraucher | `consumers[].ehal_bindings`                        | Live-Leistung / Freigaben für `cons_data`  |
| E-Auto-Status        | EVCS-Felder in `ehal_bindings` / Ladeplan          | Anschluss, Rest-SOC, Fertig-um, max. Ladeleistung |




## Was der Optimizer schreibt


| Signal               | Konfiguration                                             | Wirkung (Schnittstelle)                                                 |
| -------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| ESS-Sollleistung     | `plant.ehal_bindings.set_ess_active_power` | kW; `+` = Entladung, `−` = Ladung; bei Automatik weglassen / 0          |
| Ladegrenze           | `plant.ehal_bindings.set_ess_charge_power_limit` | kW; echte Max. Ladeleistung                                             |
| Entladegrenze        | `plant.ehal_bindings.set_ess_discharge_power_limit` | kW; echte Max. Entladeleistung                                          |
| Steuerbefehl / ESS-Modus | `plant.ehal_bindings.set_ess_mode` | **Pflicht bei jedem Zyklus:** `0` = Automatik (Sollleistung ignorieren), `1` = Zwangsladen/Entladesperre, `2` = Zwangs-Entladen (nur Batterie) |
| Einspeisegrenze (outbound) | `plant.ehal_bindings.set_grid_export_power_limit` | kW, Betrag ≥ 0; harte Decke für Netz-Einspeisung; `0` = keine Einspeisung; **unbegrenzt = PV-Nennleistung + max. Entladeleistung** |
| Einspeisegrenze (inbound, optional) | `plant.ehal_bindings.get_grid_export_power_limit` | kW; variable Grenze vom Netz/HEMS → Earnie |
| Verbraucher-Freigabe | `consumers[].ehal_bindings` (Flex enable) | `0` = gesperrt, `1` = Freigabe (SwimSpa, Wärmepumpe, Filter)            |
| E-Auto Sollstrom     | `ehal_bindings.set_evcs_max_current` | Ziel-Ladestrom / -leistung                                              |
| E-Auto PV-Follow     | `ehal_bindings` / `set_evcs_mode`          | `0`/`1` bzw. Modus                                                      |

Frühere Rollen `target_soc_name` und `pv_counter_name` entfallen. Force über `set_ess_active_power`, Grenzen als echte Caps. Loxone-Merker sind **sticky** — Automatik ist `set_ess_mode = 0`, nicht „Sollleistung weggelassen“. PV-Intervallenergie aus ∫ `sens_pv_production_active`.
Statische HK-Decke: optional `plant.max_export_power_kw` im Hauskonfigurator. Effektive Decke = `min` aus HK, inbound EHAL und **0** wenn der Einspeisetarif negativ ist (Nutzer zahlt für Einspeisung). Config setzt `set_grid_export_power_limit` als Wechselrichter-Curtailment um, am einfachsten als `MIN(Limit; WR-Nennleistung)`: `0` = Einspeisesperre; ohne Begrenzung schreibt Earnie die maximal mögliche Einspeisung der Anlage = Summe der PV-Nennleistungen (kWp) + Summe der maximalen Entladeleistungen aller gewählten Batterien, die zwangsentladen werden können (`Batteriesteuerung = voll`; `limits_only` / `read_only` zählen nicht, 2.7.c). Sind beide unbekannt, steht `1000` kW im Merker. ESS-Bindings liegen je Speicher unter Pattern B `ess.{slug}.*` in `batteries[].ehal_bindings` (plant-flach nur noch als Alias der Primärbatterie). Der Steuerbefehl (`set_ess_mode`) gilt pro Batterie und signalisiert keine Einspeisebegrenzung.
**Vorzeichenkonvention (verbindlich):** Alle Leistungen, die *ins Haus* fließen, sind positiv. Ohne Wechselrichterverluste gilt:

```
P_cons = P_PV + P_Grid + P_Bat
```

| Größe | Merker / EHAL-Feld | `+` | `−` |
|---|---|---|---|
| `P_PV` | PV-Leistung / `sens_pv_production_active` | Erzeugung | — (≥ 0) |
| `P_Grid` | `Earnie_Netzleistung` / `sens_grid_power_active` | Bezug | Einspeisung |
| `P_Bat` | `Earnie_Batterie_Leistung` bzw. EFM-Speicher / `sens_ess_power` | Entladen | Laden |
| `P_cons` | Hausverbrauch / `sens_power_consumers` | Verbrauch | — (≥ 0) |

Earnie dreht keine Vorzeichen — die Loxone-Merker müssen bereits so geliefert werden. Huawei-Register haben teils andere Vorzeichen und müssen in Loxone gedreht werden: 37113 (Netz, `+` = Einspeisung) und 37765 (Batterie, `+` = Laden).
Historische Verbrauchsdaten kommen über CSV-Upload / Energiemonitor bzw. `cons_data` (kein Miniserver-FTP-Log mehr).

Die Umsetzung in der Anlage (wann tatsächlich geladen wird) obliegt der Loxone-Logik hinter diesen virtuellen Eingängen. Config muss `Steuerbefehl = 0` als Freigabe/Automatik behandeln, auch wenn `Earnie_Batterie_Sollleistung` noch einen alten Wert hält.

## Verbindung prüfen

```powershell
# Lesen aller konfigurierten IOs
python -m scripts.verify_loxone_setup
```

Jede Prüfung meldet `[OK]` oder `[FEHLER]` mit IO-Name und Detailtext. Typische Fehler: falscher Merkername, Benutzer ohne Rechte, Lesen oder Parsen fehlgeschlagen.

Die Verbindung kann auch bequem über die Web-Oberfläche auf der Seite **Smarthome-Backend** (Anbindung) geprüft werden.

## Datenfluss (Überblick)

```
Loxone Miniserver                    Earnie
─────────────────                    ────────────────
Merker (SOC, Leistung, PV)    ──►   main.py liest
E-Auto-Status, Flex-Leistung  ──►   Optimierung (MILP)
                                     │
Virtuelle Eingänge (Soll)     ◄──   main.py schreibt
Freigaben (0/1)               ◄──   alle 15 Minuten
```

Die Streamlit-App liest Live-Werte für Anzeige (Sankey, SOC) und übernimmt die Optimierung aus dem letzten `main.py`-Durchlauf.