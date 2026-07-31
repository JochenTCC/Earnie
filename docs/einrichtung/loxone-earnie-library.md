# Earnie-Loxone-Library (Virtual In/Out, Pattern B)

Anleitung für die **Earnie-Vorlagen** unter `share/loxone/templates/`: Virtual HTTP **In** (Earnie → Loxone) und Virtual HTTP **Out** (Loxone → Earnie). Nach dem Einbau in Loxone Config liefert der **Greenfield-Import** auf [EHAL-Com](../ui/ehal-com.md) typisierte Hausprofil-Entities und Merker-Bindings.

Verwandt: [Loxone-Anbindung](loxone-anbindung.md) · [Loxone-Signale](../referenz/loxone-signale.md) · Templates-README [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md)

## Überblick Pattern B

| Richtung | Baustein | Rolle |
| -------- | -------- | ----- |
| Earnie → Loxone | **Virtual HTTP In** (`VI_Earnie_*.xml`) | Earnie pollt Status/Sollwerte/Freigaben in **benannte Merker** (`Earnie_*`) |
| Loxone → Earnie | **Virtual Out** (`VO_Earnie_*.xml`) | optionaler Push (Telemetrie); Core liest weiterhin `/jdev/sps/io/{Name}` |
| Zähler | EFM / Meter | Netz/PV/Batterie-/Flex-**Leistung** bevorzugt über EFM-Bezeichnung |

Earnie Core schreibt und liest dieselben Merker-Namen am Miniserver. Die Library ergänzt die **Loxone-seitige** HTTP-Spiegelung und ermöglicht einen **Earnie-tot**-Fallback in Config (siehe unten). Status-/Telemetry-URLs in den XMLs (`/ehal/loxone/status.json`, `/ehal/loxone/telemetry/…`) sind **Platzhalter**, bis Earnie die Endpunkte ausliefert — Cmd-**Titles** sind trotzdem der Import-Vertrag.

**XML-Stand:** Die Dateien im Repo sind handgeschriebene **Drafts**. Nach Validierung in Config bitte **Als Vorlage speichern** und die exportierte XML an Earnie zurückgeben, damit die kanonischen Templates ersetzt werden können.

## 1. Vorlagen in Loxone Config kopieren

Nur die `.xml`-Dateien kopieren (nicht `README.md`, keinen ganzen Ordnerbaum als Unterordner verschachteln).

### VirtualIn

Quelle: `share/loxone/templates/VirtualIn/`

| Datei | Inhalt (Kurz) |
| ----- | ------------- |
| `VI_Earnie_Plant.xml` | Heartbeat + ESS Design-C1-Sollwerte |
| `VI_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Freigabe` |
| `VI_Earnie_EV.xml` | E-Auto Sollstrom / Modus |
| `VI_Earnie_Consumer.xml` | generische Freigabe + Ziel_kW |
| `VI_Earnie_Pool.xml` | Pool- / Filter-Freigabe |

Zielordner (eines der vorhandenen Config-Pfade; Ordner ggf. anlegen):

- `%ProgramData%\Loxone\Loxone Config\<Version>\Template\VirtualIn\`
- oder `Documents\Loxone\Loxone Config\Templates\VirtualIn\`

### VirtualOut

Quelle: `share/loxone/templates/VirtualOut/`

| Datei | Inhalt (Kurz) |
| ----- | ------------- |
| `VO_Earnie_Status.xml` | optional alive / request_optimize |
| `VO_Earnie_Plant.xml` | Plant `sens_*`, Außentemperatur |
| `VO_Earnie_EV.xml` | EV-Telemetrie |
| `VO_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Leistung` |
| `VO_Earnie_Consumer.xml` | Flex-Leistung |
| `VO_Earnie_Pool.xml` | Pool-Telemetrie |

Ziel: entsprechender Ordner **`VirtualOut`**.

Danach **Loxone Config neu starten**. Die Vorlagen erscheinen unter Peripherie / Device Templates (Virtual In / Virtual Out).

## 2. Earnie-Adresse setzen

In jedem eingefügten Virtual-In/Out den Platzhalter `EARNIE_HOST` durch die LAN-IP bzw. den Hostnamen von Earnie ersetzen (Port typisch **8501** im Compose-Stack, siehe [Streamlit-Ports](../referenz/streamlit-ports.md)).

Beispiel Virtual In Address:

`http://192.168.178.10:8501/ehal/loxone/status.json`

Virtual Out Address (Basis):

`http://192.168.178.10:8501`

Polling / Cmd-Check-Muster erst anpassen, wenn Earnie echte JSON-Keys liefert; bis dahin reichen stabile **Titles** für Core und Greenfield-Import.

## 3. Geräte einfügen und Merker belassen

1. Pro Rolle die passende Vorlage einmal (oder mehrfach bei mehreren Flex-Verbrauchern) einfügen.
2. Cmd-**Titles** nicht willkürlich umbenennen — sie müssen zu [`greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) / [Loxone-Signale](../referenz/loxone-signale.md) passen.
3. **Mehrere Flex-Verbraucher / E-Autos:** Titles nach Schema Prefix+Slug; VI-Check und VO-Pfad mit `{hk_id}` / `{ev_id}` (siehe [Namenskonvention](../referenz/loxone-signale.md#mehrere-flex-verbraucher-namenskonvention)).
4. Programm auf den Miniserver speichern / laden.

## 4. Zähler und Energieflussmonitor (EFM)

Die Templates enthalten **keine** Zähler-Hardware. In Config:

1. Zähler mit **eindeutiger, stabiler Bezeichnung** anlegen bzw. belassen.
2. Zähler dem **Energieflussmonitor** zuordnen (Netz / PV / Batterie / Lasten).
3. Residual-/Rest-Knoten nicht als eigener Flex-Verbraucher verwenden (Import überspringt typische Rest-Labels).

Leistungs-Merker (`Earnie_Netzleistung`, `Earnie_PV_Leistung`, …) **dürfen** vom EFM kommen; VO-Cmds bleiben optionaler Namenskatalog. Earnie bevorzugt die EFM-Bezeichnung im Binding, wenn vorhanden. HITL-Nacharbeit: EHAL-Com → **Energieflussmonitor → Verbraucher**.

## 5. Earnie-tot-Fallback (in Loxone Config)

Ziel: Wenn Earnie nicht erreichbar ist oder Virtual In nicht mehr aktualisiert, **Earnie-Sollwerte ignorieren** und lokale Regeln fahren.

Empfohlener Ablauf (Logikbausteine in Config, kein Earnie-Code):

1. **Watchdog** auf `Earnie_Heartbeat` (Unix-Zeitstempel aus `VI_Earnie_Plant`): Alter = jetzt − Heartbeat (bzw. „Wert seit x Sekunden unverändert“).
2. Schwelle wählen (z. B. 2–3× PollingTime der Virtual In, typisch ≥ 90 s bei 30 s Poll).
3. Bei **stale**:
   - `Earnie_Steuerbefehl` / ESS-Modus lokal auf **Automatik** (`0`) bzw. sichere ESS-Regeln der Anlage setzen
   - Flex-**Freigaben** (`Earnie_*_Freigabe`) auf `0` (gesperrt) oder bekannte Notfall-Logik
   - E-Auto-Sollwerte nicht mehr aus Earnie-Merker übernehmen
4. Bei **frisch**: Earnie-Merker wie vorgesehen an Aktorik / Programm weiterreichen.

Earnie Core bleibt unverändert auf Miniserver-IOs; der Fallback ist **nur** Config-Logik um die Merker herum.

## 6. Greenfield-Import in Earnie

Voraussetzung: Library (oder gleichnamige Merker) auf dem Miniserver; Zugangsdaten in `.env` / EHAL-Com.

1. **Hauskonfigurator** (Erstsetup): optional Assistent „Loxone-Import?“ → springt zu EHAL-Com mit Backend Loxone.
2. Auf **EHAL-Com**: Anbindung prüfen, dann **Greenfield importieren**.
3. Earnie lädt `LoxAPP3.json`, prüft `Earnie_*` per HTTP-Probe (auch Prefix+Slug, case-insensitive), legt typisierte Entities an und merged EFM-Zähler.
4. Mapping-Tabelle prüfen; Parameter (kWh, Fahrpläne, Wohnfläche, …) im **Hauskonfigurator** nachziehen.

Siehe [EHAL-Com — Loxone Struktur → EHAL Mapping](../ui/ehal-com.md#loxone-struktur--ehal-mapping).

## Checkliste

- [ ] `VI_` / `VO_` XMLs in Config-Template-Ordner kopiert, Config neu gestartet
- [ ] `EARNIE_HOST` gesetzt; Geräte eingefügt; Titles stabil
- [ ] Mehrfach-Verbraucher / E-Autos: Slug-Titles + Check/VO `{hk_id}` / `{ev_id}` (falls genutzt)
- [ ] Zähler am EFM mit eindeutigen Bezeichnungen
- [ ] Programm auf Miniserver
- [ ] Optional: Heartbeat-Watchdog + Fallback programmiert
- [ ] EHAL-Com: Greenfield importieren → Parameter im Hauskonfigurator
