# Loxone-Anbindung

Earnie kommuniziert mit dem Loxone Miniserver über **HTTP** (Lesen und Schreiben von Werten). Die konkrete Schaltlogik in Loxone (Wechselrichter (Batteriespeicher), Wallbox, Pool, ...) liegt außerhalb von Earnie — der Optimizer liefert Sollwerte und Freigaben.

Andere Hubs (HA+evcc, OpenEMS): [Adapter wählen](adapter-wahl.md).

**Greenfield / Library:** Virtual-In/Out-Vorlagen einspielen, Zähler am EFM, Earnie-tot-Fallback und Import: [Earnie-Loxone-Library](loxone-earnie-library.md).

## Zugangsdaten (`config/.env`)


| Variable      | Bedeutung                              |
| ------------- | -------------------------------------- |
| `LOXONE_IP`   | IP-Adresse des Miniservers             |
| `LOXONE_USER` | Benutzername (HTTP Basic Auth)         |
| `LOXONE_PASS` | Passwort                               |


Vorlage: [.env.example](../../.env.example) → nach `config/.env` kopieren (Prod/Docker legt der Entrypoint die Datei an). 

Die Zugangsdaten können auch bequem über die Web-Oberfläche eingegeben werden.

## HTTP-Schnittstelle

- **Lesen:** `GET http://{LOXONE_IP}/jdev/sps/io/{Name}`
- **Schreiben:** `POST` auf dieselbe URL mit dem Zielwert

Antworten liefern den Wert unter `LL.value`. Loxone gibt Zahlen oft **mit Einheit** zurück (z. B. `3.5 kW`, `72 %`, `16 A`). Der Optimizer parst diese Strings und ignoriert die Einheit für die Berechnung.

Merker-Namen liegen in `plant.ehal_bindings` / `consumers[].ehal_bindings` (Hausprofil) — siehe [Loxone-Signale](../referenz/loxone-signale.md). Zuordnung in der UI: **EHAL-Com**.

## Was der Optimizer liest


| Bereich              | Konfiguration                                      | Zweck                                             |
| -------------------- | -------------------------------------------------- | ------------------------------------------------- |
| Anlage (Plant)       | `plant.ehal_bindings`                              | SOC, Netz/PV/ESS-Leistungen, Außentemperatur      |
| Steuer-Rückmeldung   | dieselben Soll-/Ist-Merker                         | Prüfen, ob Schreiben ankommt                      |
| Flexible Verbraucher | `consumers[].ehal_bindings`                        | Live-Leistung / Freigaben für `cons_data_hourly`  |
| E-Auto-Status        | EVCS-Felder in `ehal_bindings` / Ladeplan          | Anschluss, Rest-SOC, Fertig-um, max. Ladeleistung |




## Was der Optimizer schreibt


| Signal               | Konfiguration                                             | Wirkung (Schnittstelle)                                                 |
| -------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| ESS-Sollleistung     | `plant.ehal_bindings.set_ess_active_power` | kW; `+` = Entladung, `−` = Ladung; bei Automatik weglassen / 0          |
| Ladegrenze           | `plant.ehal_bindings.set_ess_charge_power_limit` | kW; echte Max. Ladeleistung                                             |
| Entladegrenze        | `plant.ehal_bindings.set_ess_discharge_power_limit` | kW; echte Max. Entladeleistung                                          |
| Steuerbefehl / ESS-Modus | `plant.ehal_bindings.set_ess_mode` | **Pflicht bei jedem Zyklus:** `0` = Automatik (Sollleistung ignorieren), `1` = Zwangsladen/Entladesperre, `2` = Zwangs-Entladen |
| Verbraucher-Freigabe | `consumers[].ehal_bindings` (Flex enable) | `0` = gesperrt, `1` = Freigabe (SwimSpa, Wärmepumpe, Filter)            |
| E-Auto Sollstrom     | `ehal_bindings.set_evcs_max_current` | Ziel-Ladestrom / -leistung                                              |
| E-Auto PV-Follow     | `ehal_bindings` / `set_evcs_mode`          | `0`/`1` bzw. Modus                                                      |

Frühere Rollen `target_soc_name` und `pv_counter_name` entfallen. Force über `set_ess_active_power`, Grenzen als echte Caps. Loxone-Merker sind **sticky** — Automatik ist `set_ess_mode = 0`, nicht „Sollleistung weggelassen“. PV-Intervallenergie aus ∫ `sens_pv_production_active`.
Historische Verbrauchsdaten kommen über CSV-Upload / Energiemonitor bzw. `cons_data` (kein Miniserver-FTP-Log mehr).

Die Umsetzung in der Anlage (wann tatsächlich geladen wird) obliegt der Loxone-Logik hinter diesen virtuellen Eingängen. Config muss `Steuerbefehl = 0` als Freigabe/Automatik behandeln, auch wenn `Earnie_Batterie_Sollleistung` noch einen alten Wert hält.

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