# Home Assistant + evcc (DACH-Pfad A2 / B)

Für den Produktivbetrieb mit breitem Geräteangebot im DACH-Raum spricht Earnie als Geräteanbindung (Southbound) den **HA-EHAL-Adapter** (REST) an. **evcc** läuft als Sidecar unter Home Assistant und liefert typische Entities für Wallbox, Zähler und Wechselrichter. Earnie schreibt auf **stabile HA-Entities** und greift nicht parallel direkt auf die evcc-API zu.

Den Vergleich von Loxone, HA und OpenEMS sowie den Wechsel des Backends beschreibt [Smarthome-Backend wählen](smarthome-backend-wahl.md). Das Entwickler-Setup (Compose, Token, Mapping) steht in der [HA-Lab Spec](../dev/ha-lab-setup.md).

## Pfad A2 (Standard) und Pfad B im Vergleich

| Pfad | Ziel | Bundle |
| --- | --- | --- |
| **A2 (Standard im DACH-Raum)** | Neues Setup oder Gateway-Setup mit dynamischen Tarifen, Wallbox, PV und Zähler | Earnie + Home Assistant + evcc (Compose) |
| **B (Bestand, Installed Base)** | Bestehendes Home Assistant | Earnie + Entity-Mapping; evcc optional ergänzen |

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

## Entity-Mapping (Human-in-the-Loop)

Wie bei Loxone liegen die Entity-IDs **entity-scoped** bei der jeweiligen Komponente: `plant.ehal_bindings`, `batteries[].ehal_bindings` und `consumers[].ehal_bindings` (in `house_profiles.json`, für Speicher in `components.json`). In `config.json` bleiben unter `ehal.ha` nur der Hinweis auf die Zugangsdaten und `sign`. URL und Token stehen in `config/.env`. Das frühere flache `ehal.ha.entities` wird **einmalig migriert und geleert** (per Migrationsschritt bzw. Mapping-UI). Neue Installationen befüllen es nicht mehr.

**Live-Laufzeit – Transport:** Der Schlüssel `ehal.ha.transport` in `config.json` legt fest, wie Earnie mit Home Assistant Daten austauscht:

- **`pull`** (Standard): Ablauf siehe nächster Absatz.
- **`push`:** Gleicher HTTP-Vertrag wie bei Loxone, also Push nach `/ehal/telemetry/…` und Setpoints per `GET /ehal/status.json`. `push` schaltet die Live-Pfade auf Push und `status.json` um. Details und die **EHAL-Basiseinheiten auf der Push-Leitung** beschreibt die [EHAL-Spec § Home Assistant](../referenz/ehal.md#implementation-notes--home-assistant--evcc).

> **Hinweis:** `push` ist bisher nur im Labor erprobt. Im Produktivbetrieb weiterhin **`pull`** verwenden.

**Live-Laufzeit (`pull`, HA-Adapter):** Der HA-Adapter liest und schreibt die Felder, die `aggregate_ha_entities` / `HA_ALL_FIELDS` zusammenführen. Typisch sind:

- **Anlage:** Leistungen und ESS (`sens_grid_*`, `sens_pv_*`, `sens_ess_*`), optionale Energiezähler und ESS-Setpoints.
- **Abwesenheit:** das optionale Plant-Signal `sens_absent_mode` (Abwesenheitsmodus, Side-Channel).
- **E-Auto:** am **ersten EV**-Verbraucher `sens_evcs_active_power`, `set_evcs_max_current` und `set_evcs_mode`.

Außentemperatur, EV-SoC/connected sowie Flex- und Pool-Felder gehören nicht zu den HA-Mapping-Feldern. Der Mapping-Assistent bietet sie nicht an, und mit dem Backend Home Assistant stehen sie derzeit nicht zur Verfügung.

1. In Home Assistant ein **Long-Lived Access Token** anlegen.
2. Auf **Daemon Control → Smarthome-Backend** das Backend **Home Assistant** wählen und URL/Token eintragen. Die Seite setzt `ehal.backend=ha` und schreibt `EHAL_HA_*` in `config/.env`. Alternativ `ehal.backend` aus dem Snippet [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) übernehmen und die Zugangsdaten in `.env` setzen.
3. Danach auf **Daemon Control → EHAL-Com** den Expander **HA Entity → EHAL Mapping** öffnen: Entities scannen (einmal pro Session), eine Entity wählen (Anlage, Batterie oder Verbraucher), nur deren EHAL-Felder zuweisen und **Mapping speichern**. Gespeichert wird in `plant` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings`, nicht in `ehal.ha.entities`.
4. Optional **Telemetrie testen**. LLM-gestützte Vorschläge sind **nicht** Teil der ausgelieferten UI.

**Optional – Ist-Werte je Slot:** Für Slot-Ist (ΔkWh → mittlere kW) auf der Anlage `sens_pv_energy`, `sens_grid_energy_import` und `sens_grid_energy_export` mappen (`device_class=energy`, bevorzugt `total_increasing`). Details: [EHAL-Com](../ui/ehal-com.md) · [Charts](../ui/charts.md).

### Wenn marq24 / evcc bereits in HA verbunden ist

**Voraussetzung:** Die Integration **evcc☀️🚘- Solar Charging** zeigt Geräte unter **Einstellungen → Geräte & Dienste**. Im Lab lautet die URL `http://evcc:7070`.

1. In HA unter **Entwicklerwerkzeuge → Zustände** die exakten `entity_id`s notieren (Filter z. B. `evcc`). Mit dem Lab-Stub (`ha_lab/evcc/evcc.yaml`) sind Leistungen oft **0 W** und der SoC **50 %**. Für den Pfadnachweis reicht das.
2. **Mindestens zuordnen:** Netzleistung → `sens_grid_power_active`, PV → `sens_pv_production_active`, Batterie-SoC → `ess.{id}.sens_ess_soc` (auf der Batterie-Entity, nicht flach auf der Anlage). Optional: Batterie-/Ladeleistung, Maxstrom (`number`).
3. In Earnie (http://localhost:8506) auf **Smarthome-Backend** das Backend **Home Assistant** mit URL/Token verbinden (setzt `ehal.backend=ha`). Danach auf **EHAL-Com** im Expander **HA Entity → EHAL Mapping** scannen, eine Entity wählen, zuweisen, **Telemetrie testen** und **Mapping speichern**.
4. **Vorzeichen:** Im EHAL bedeutet Netz **+** Bezug und ESS **+** Entladen. Weicht die Integration davon ab, **negate** setzen (weiterhin unter `ehal.ha.sign`).
5. **Erfolg:** Der Telemetrie-Test ist OK, `config.json` enthält `ehal.backend=ha`, die Bindings stehen im Hausprofil und in `components.json`. Der Live-Betrieb läuft ohne die Meldung „Kein Zugriff auf EHAL SoC“.

Eine Schritt-für-Schritt-Anleitung (Englisch, inkl. Abnahmetabelle) steht in der [HA-Lab Spec §5.1](../dev/ha-lab-setup.md#51-after-marq24-ha-evcc-is-connected-lab-follow-up). Installation der Integration: [§3.5 Option 2](../dev/ha-lab-setup.md#35-expose-evcc-entities-into-home-assistant).

## Optimizer-Exklusivität (Checkliste)

Lokale Strategien des Hubs für Überschuss, Preise oder Laden dürfen Earnies 48-h-Fahrplan nicht überschreiben:

- [ ] In **evcc** ist keine eigenständige Surplus- oder Spotpreis-Ladeplanung aktiv (kein Smart Cost, kein konkurrierender Planner).
- [ ] Der Loadpoint ist so eingestellt, dass Earnie den Maxstrom (HA-`number`-Entity) setzen kann.
- [ ] Keine HA-Automation schreibt auf dieselben Setpoint-Entities wie Earnie.
- [ ] Spotpreise und Fahrpläne kommen aus **Earnie**, nicht aus dem Hub.

## Modbus-Regel

Pro physischem Bus bzw. Gerät gibt es genau **einen** schreibenden Southbound-Owner, also das System, das Sollwerte an das Gerät sendet. Typisch ist das **evcc** *oder* eine HA-Integration inkl. Proxy. Auf demselben Wechselrichter keine parallelen Modbus-Clients betreiben.

## Pfad B (bestehendes HA)

1. Earnie so betreiben, dass die bestehende HA-URL und ein Token erreichbar sind (Docker-Netz / Host-IP).
2. Den Mapping-Assistenten wie oben nutzen: native HA-Entities (Long-Tail), evcc optional.
3. Dieselbe Checkliste zur Optimizer-Exklusivität und die Modbus-Regel anwenden.

## Stop

Lab-Stack beenden:

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml down
```
