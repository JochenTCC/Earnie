# Loxone-Anbindung

Earnie kommuniziert mit dem Loxone Miniserver über **HTTP** (Lesen und Schreiben von Werten) und optional **FTP** (Verbrauchs-Logdateien). Die konkrete Schaltlogik in Loxone (Relais, Huawei-WR, Ladebox) liegt außerhalb dieses Tools — der Optimizer liefert Sollwerte und Freigaben.

## Zugangsdaten (`config/.env`)

| Variable | Bedeutung |
|----------|-----------|
| `LOXONE_IP` | IP-Adresse des Miniservers |
| `LOXONE_USER` | Benutzername (HTTP Basic Auth und FTP) |
| `LOXONE_PASS` | Passwort |

Vorlage: [.env.example](../../.env.example) → nach `config/.env` kopieren (Prod/Docker legt der Entrypoint die Datei an). Die Datei wird nicht versioniert. Lokale Dev kann weiterhin `./.env` im Projektroot nutzen (Legacy-Fallback).

## HTTP-Schnittstelle

- **Lesen:** `GET http://{LOXONE_IP}/jdev/sps/io/{Name}`
- **Schreiben:** `POST` auf dieselbe URL mit dem Zielwert

Antworten liefern den Wert unter `LL.value`. Loxone gibt Zahlen oft **mit Einheit** zurück (z. B. `3.5 kW`, `72 %`, `16 A`). Der Optimizer parst diese Strings und ignoriert die Einheit für die Berechnung.

Konfigurierte Namen stehen in `config.json` → siehe [Loxone-Signale](../referenz/loxone-signale.md).

## Was der Optimizer liest

| Bereich | Konfiguration | Zweck |
|---------|---------------|-------|
| Batterie | `loxone_blocks` | SOC, Leistungen, PV |
| Steuer-Rückmeldung | `loxone_blocks` (Soll-Merker) | Prüfen, ob Schreiben ankommt |
| Flexible Verbraucher | `flexible_consumers[].loxone_inputs` | Live-Leistung für `cons_data_hourly` |
| E-Auto-Status | `charging_schedule.loxone` | Anschluss, Rest-SOC, Fertig-um, max. Ladeleistung |

## Was der Optimizer schreibt

| Signal | Konfiguration | Wirkung (Schnittstelle) |
|--------|---------------|-------------------------|
| Ziel-SOC | `target_soc_name` | Virtueller Eingang, % |
| Zwangsladeleistung | `target_charge_power_name` | kW |
| Ziel-Entladeleistung | `target_discharge_power_name` | kW |
| Steuerbefehl | `control_cmd_name` | `0` = Automatik, `1` = Zwangsladen/Entladesperre, `2` = Zwangs-Entladen |
| Verbraucher-Freigabe | `flexible_consumers[].loxone_outputs.enable_name` | `0` = gesperrt, `1` = Freigabe |

Die Umsetzung in der Anlage (wann tatsächlich geladen wird) obliegt der Loxone-Logik hinter diesen virtuellen Eingängen.

## FTP (Verbrauchslog)

- Dateiname: `loxone_blocks.log_filename` (z. B. `Verbrauch.csv`)
- Pfad auf dem Miniserver: Verzeichnis `log/`
- Verwendung: Import historischer Verbrauchsdaten, Aufbau von `cons_data_hourly.csv`

## Verbindung prüfen

```powershell
# Lesen aller konfigurierten IOs
python -m scripts.verify_loxone_setup
```

Jede Prüfung meldet `[OK]` oder `[FEHLER]` mit IO-Name und Detailtext. Typische Fehler: falscher Merkername, Benutzer ohne Rechte, Wert außerhalb des erwarteten Bereichs (z. B. Freigabe ≠ 0/1).

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

Die Streamlit-App liest Live-Werte für Anzeige (Sankey, SOC) und synchronisiert die Simulation mit dem letzten `main.py`-Durchlauf.
