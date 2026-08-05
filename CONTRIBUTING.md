# Mitwirken an Earnie

Danke für dein Interesse. Earnie lebt von Self-Hostern und der Tech-Community: als Multiplikatoren, Tester und Mitentwickler — besonders bei neuen Geräten und Smart-Home-Anbindungen.

Produktüberblick: **[README.md](README.md)** · Technische Einrichtung: **[DEVELOPER.md](DEVELOPER.md)** · Anwender-Doku: **[docs/README.md](docs/README.md)**

---

## Lizenz und Regeln (kurz)

Earnie ist **Source-Available** und für die **private, nicht-kommerzielle Nutzung** in Privathaushalten gedacht. Kommerzielle Nutzung, Weiterverkauf oder SaaS-Angebote Dritter sind ohne schriftliche Zustimmung nicht erlaubt.

Vollständige Bedingungen: **[LICENSE.md](LICENSE.md)**.

### Forks und Weitergabe

- Öffentliche Forks müssen unter denselben Bedingungen bleiben (Source-Available, Non-Commercial).
- Das sichtbare Attributions-Banner („**Banner der Wahrheit**“) muss erhalten bleiben und darf in der Aussage nicht entstellt oder entfernt werden (`LICENSE.md` § 4).
- Unofficial Builds können einen Warnhinweis zeigen; das Banner ist bewusst sichtbar, aber nicht technisch fälschungssicher.

---

## Wie du helfen kannst

### 1. Testen und Rückmeldung

- Earnie auf PC, NAS, LoxBerry oder Proxmox ausprobieren (auch Community-Pre-Releases).
  - Andere Plattformen gerne nachfragen
- Fehler, unplausible Optimierungen oder UI-Probleme melden — ideal mit kurzer Beschreibung (öffentliches GitHub-Issue; keine Secrets).
- Erweiterungs-Wünsche
- **In der App:** Sidebar **Info / About** → Kontakt (Art, Thema, Beschreibung) → **GitHub-Issue öffnen**. Optional lokal **ZIP sammeln** (wird nicht hochgeladen). Registry / Vertrauliches: `support@earnie-hems.com`.
- **GitHub:** Issues unter [JochenTCC/Earnie](https://github.com/JochenTCC/Earnie/issues) (Vorlagen: Bug / Change request / Improvement / Question).

### 2. Code und Dokumentation

Willkommen sind u. a.:

- Bugfixes und Tests
- Verbesserungen an Doku und Beispielen
- Anbindungen weiterer Smart-Home-Systeme (Ziel: Loxone-agnostische Connector-Architektur, siehe Roadmap)
- Templates / Profile für Wechselrichter, Speicher, Wallboxen, Wärmepumpen (SG-Ready u. a.)

Technischer Einstieg: **[DEVELOPER.md](DEVELOPER.md)** (venv, pytest, Container, Projektstruktur).

**Pull Requests:** Fork → Branch → PR gegen `main`. Kurze Beschreibung des *Warum*; bei Verhaltensänderungen Tests mitdenken. Große Architektur-Themen bitte vorher kurz absprechen (Issue oder Kontakt).

**Hotfixes für bereits getaggte Builds** (während `main` weiterläuft): Playbook [docs/spec/branching-hotfix-playbook.md](docs/spec/branching-hotfix-playbook.md) — Standard bleibt Fix auf `main`; kurzlebige `hotfix/…`-Branches nur bei dringendem Patch vom Release-Tag.

### 3. EHAL-Connectoren (Adapter)

Southbound-Anbindungen laufen über den **Earnie Hardware Access Layer (EHAL)** — normiertes JSON für Telemetrie, Setpoints und Capability-Flags.

**Verbindliche Spec (Englisch):** [docs/spec/ehal.md](docs/spec/ehal.md) · JSON-Schemas: `share/ehal/` · Python: Paket `ehal`.

**Adapter-Vertrag:**

- Nur **übersetzen**: Hub-Kanäle/Entities → dieselben EHAL-Strukturen; keine Hub-Typen im Optimizer/MILP-Kern.
- **Vorzeichen und Einheiten** im Adapter normalisieren (`+` = Netzbezug, Leistung in **W**, EVCS-Setpoint in **A**).
- **Capability-Flags** melden; bei fehlgeschlagenen Writes degradieren (loggen, Nutzerhinweis, Write-Error-Telemetry) — siehe Spec.
- Anbindung nur über **Netzwerk-API** (REST/WS/HTTP); keine Hub-Quelltexte oder Libraries in Earnie-Repos (Separate Works, z. B. OpenEMS/AGPL).
- Setpoints = **Grenzen/Fahrpläne**; Echtzeitregelung bleibt im Subsystem.
- Umschaltung **nur über Config** (`ehal.backend` + Hub-Block) — Core/MILP unverändert. Nachweis: `tests/test_ehal_contract_backends.py` (`2.4.h`).

**Rezept für einen neuen Hub-Adapter:**

1. `integrations/<hub>_adapter.py` mit `read_telemetry()`, `write_setpoints()`, `capabilities()` — Dokumente gegen M1-Schemas via `ehal.validate_*` emittieren (Vorbilder: `openems_adapter.py`, `ha_adapter.py`, `loxone_adapter.py`).
2. In [`integrations/ehal_live.py`](integrations/ehal_live.py) verdrahten: `is_<hub>_backend()`, `get_<hub>_adapter()`, Zweig in `get_adapter()`; bei Bedarf Setup-Keys in `settings/config_loaders.py` (`load_ehal_params`), `runtime_store/ehal_setup.py` und UI unter `ui/ehal_connection.py`.
3. Unit-Tests für den Adapter; Config-Switch-Parität in `tests/test_ehal_contract_backends.py` erweitern.
4. Mapping-Hilfen (Rollen/Rezepte) gehören in §4 — sie sind **keine** Live-I/O-Engine.

Referenz-Backends: OpenEMS (`2.4.b`), HA+evcc (`2.4.c`), Loxone-EHAL M1 (`2.4.e`); automatisierter Multi-Backend-Nachweis (`2.4.h`). Flex/`target_soc`/`control_cmd` bleiben vorerst auf `loxone_client` (kein Schema-Erweiterung in `2.4.e`).

Nicht alles ist Teil des Basis-Setups (z. B. individuelle Pool-, Klima- oder Sonderanlagen). Technisch versierte Nutzer dürfen den Local Core und vorhandene Schnittstellen nutzen, um **eigene Logiken** anzubinden — unter derselben Lizenz; neue Hubs idealerweise als EHAL-Adapter.

### 4. Hardware-Profile und Datenbeitrag

Die Weiterentwicklung hängt stark davon ab, dass unbekannte Geräte (Wechselrichter, Speicher, Wallboxen, …) beschrieben und geteilt werden.

Laut `LICENSE.md` § 3: Bei Hardware ohne offizielles Profil bist du zur Kooperation eingeladen — **anonymisierte** technische Parameter und Konfigurationsdaten (ohne personenbezogene Daten).

**Beitragsformat (2.4.g, Schema-Slice):**

| Was | Wo |
|-----|-----|
| EHAL-Geräterollen (Mapping-Hilfen) | `share/ehal/roles/` + Schema `share/ehal/device_roles.schema.json` |
| Modbus / SunSpec-Outline (Pfad D-Seed) | `share/hardware_profiles/` (+ `examples/`) |
| Loxone Merker-Rezepte (JSON, kein `.loxone`) | `share/loxone/recipes/` |
| Loader / Validierung | Python-Paket `ehal.profiles` |

Neue Profile bitte als JSON gegen die jeweiligen Schemas validieren (siehe Tests `tests/test_ehal_profiles.py`). Spec: [docs/spec/ehal.md](docs/spec/ehal.md) Abschnitt *Device roles and hardware profiles*.

**Geplant (noch nicht produktiv):** ein Community-**Hardware-Bounty**-Verfahren (Entwicklungsplan **M4**) — Einreichung neuer, verifizierter Geräteprofile gegen eine Entschädigung (Höhe/Form noch offen bzw. projektspezifisch definiert; siehe `LICENSE.md` § 3 / `[PARAM_DATA_COMPENSATION]`). Bis die Bounty-Engine steht: Profile und Hinweise gern über Info / About (GitHub-Issue) oder direkt als Issue.

---

## Was (noch) nicht erwartet wird

- Kein vertraglicher Herstellersupport — Rückmeldungen helfen trotzdem.
- Keine Garantie, dass jedes Custom-Setup in Managed-/Partner-Pakete aufgenommen wird (Scope-Limitation zugunsten stabiler Standard-Templates).
- Kommerzielle Cloud-/Managed-Dienste und Partner-Setup sind getrennt vom freien Local Core; Mitwirken am Kern ändert die Lizenz nicht.

---

## Kontakt und Ticket-Kanäle

| Kanal | Zweck |
| --- | --- |
| [GitHub Issues](https://github.com/JochenTCC/Earnie/issues) | Öffentlicher Intake: Bugs, Änderungswünsche, Verbesserungen, Fragen (Vorlagen + Labels). App **Info / About** öffnet ein vorbefülltes Issue. |
| App **Info / About** — ZIP lokal | Config-/Kontakt-ZIP nur herunterladen; nicht automatisch hochladen. Sichere Ausschnitte dürfen in Issues; vollständige Dumps nur privat. |
| `support@earnie-hems.com` | Privater Ausnahmekanal: Registry-Fingerprint, Secrets, sensible Dumps (ZIP manuell anhängen). |
| Roadmap | [backlog/Backlog.md](backlog/Backlog.md) — Scheduling-Quelle; Maintainer übernimmt Issues bei Einplanung mit `#NN`. |

**Triage (kurz):** neue Issues mit `needs-triage` → antworten/schließen oder labeln → bei Einplanung Markdown-Backlog-Eintrag mit Issue-Link. Bugfixes weiter über [backlog/Backlog-Bugfixes.md](backlog/Backlog-Bugfixes.md).

Demo ohne lokale Installation (Szenario-Explorer): [earnie.streamlit.app](https://earnie.streamlit.app) (falls verfügbar) — Feedback ebenfalls als GitHub-Issue (`cloud-demo`).
