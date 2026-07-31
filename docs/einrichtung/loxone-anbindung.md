# Loxone-Anbindung

Earnie kommuniziert mit dem Loxone Miniserver über **HTTP** (Lesen und Schreiben von Werten) und optional **FTP** (Verbrauchs-Logdateien). Die konkrete Schaltlogik in Loxone (Wechselrichter (Batteriespeicher), Wallbox, Pool, ...) liegt außerhalb von Earnie — der Optimizer liefert Sollwerte und Freigaben.

Andere Hubs (HA+evcc, OpenEMS): [Adapter wählen](adapter-wahl.md).

## Zugangsdaten (`config/.env`)


| Variable      | Bedeutung                              |
| ------------- | -------------------------------------- |
| `LOXONE_IP`   | IP-Adresse des Miniservers             |
| `LOXONE_USER` | Benutzername (HTTP Basic Auth und FTP) |
| `LOXONE_PASS` | Passwort                               |


Vorlage: [.env.example](../../.env.example) → nach `config/.env` kopieren (Prod/Docker legt der Entrypoint die Datei an). 

Die Zugangsdaten können auch bequem über die Web-Oberfläche eingegeben werden.

## HTTP-Schnittstelle

- **Lesen:** `GET http://{LOXONE_IP}/jdev/sps/io/{Name}`
- **Schreiben:** `POST` auf dieselbe URL mit dem Zielwert

Antworten liefern den Wert unter `LL.value`. Loxone gibt Zahlen oft **mit Einheit** zurück (z. B. `3.5 kW`, `72 %`, `16 A`). Der Optimizer parst diese Strings und ignoriert die Einheit für die Berechnung.

Konfigurierte Namen stehen in `config.json` → siehe [Loxone-Signale](../referenz/loxone-signale.md).

## Was der Optimizer liest


| Bereich              | Konfiguration                        | Zweck                                             |
| -------------------- | ------------------------------------ | ------------------------------------------------- |
| Batterie             | `loxone_blocks`                      | SOC, Leistungen, PV                               |
| Steuer-Rückmeldung   | `loxone_blocks` (Soll-Merker)        | Prüfen, ob Schreiben ankommt                      |
| Flexible Verbraucher | `flexible_consumers[].loxone_inputs` | Live-Leistung für `cons_data_hourly`              |
| E-Auto-Status        | `charging_schedule.loxone`           | Anschluss, Rest-SOC, Fertig-um, max. Ladeleistung |




## Was der Optimizer schreibt


| Signal               | Konfiguration                                             | Wirkung (Schnittstelle)                                                 |
| -------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| ESS-Sollleistung     | `plant.ehal_bindings.set_ess_active_power` (Legacy: `target_active_power_name`) | kW; `+` = Entladung, `−` = Ladung; bei Automatik weglassen / 0          |
| Ladegrenze           | `plant.ehal_bindings.set_ess_charge_power_limit` (Legacy: `target_charge_power_name`) | kW; echte Max. Ladeleistung                                             |
| Entladegrenze        | `plant.ehal_bindings.set_ess_discharge_power_limit` (Legacy: `target_discharge_power_name`) | kW; echte Max. Entladeleistung                                          |
| Steuerbefehl / ESS-Modus | `plant.ehal_bindings.set_ess_mode` (Legacy: `control_cmd_name`) | Hinweis: `0` = Automatik, `1` = Zwangsladen/Entladesperre, `2` = Zwangs-Entladen |
| Verbraucher-Freigabe | `flexible_consumers[].loxone_outputs.enable_name` / `ehal_bindings.flex.enable_name` | `0` = gesperrt, `1` = Freigabe (SwimSpa, Wärmepumpe, Filter)            |
| E-Auto Sollstrom     | `ehal_bindings.set_evcs_max_current` (Legacy: `power_setpoint_name`) | Ziel-Ladestrom / -leistung                                              |
| E-Auto PV-Follow     | `ehal_bindings.pv_follow_name` / `set_evcs_mode`          | `0`/`1` bzw. Modus                                                      |

`target_soc_name` (Ziel-SOC) und `pv_counter_name` (kumulierte PV-kWh) wurden in **2.4.j** entfernt. Ab Design C1 (**2.4.o**): Force über `set_ess_active_power`, Grenzen als echte Caps, `set_ess_mode` nur Hinweis für Loxone/Huawei. PV-Intervallenergie aus ∫ `sens_pv_production_active`.
Das frühere Miniserver-FTP-Verbrauchslog (`loxone_blocks.log_filename`) und das PV-Tuning-Log entfallen in **2.4.m** — historische Verbrauchsdaten kommen über CSV-Upload / Energiemonitor bzw. `cons_data`.


Die Umsetzung in der Anlage (wann tatsächlich geladen wird) obliegt der Loxone-Logik hinter diesen virtuellen Eingängen.

## Verbindung prüfen

```powershell
# Lesen aller konfigurierten IOs
python -m scripts.verify_loxone_setup
```

Jede Prüfung meldet `[OK]` oder `[FEHLER]` mit IO-Name und Detailtext. Typische Fehler: falscher Merkername, Benutzer ohne Rechte, Wert außerhalb des erwarteten Bereichs (z. B. Freigabe ≠ 0/1).

Die Verbindung kann auch bequem über die Web-Oberfläche auf der Seite **EHAL-Com** (Anbindung) geprüft werden.

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