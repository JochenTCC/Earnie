# Entwickler-Dokumentation

Nicht Teil der Anwender-Dokumentation ([Anwender-Doku](../README.md)). Englisch/technisch bzw. Entwickler-Betrieb.

## Specs (Englisch/technisch)

Lab- und Simulationsumgebungen (HA Lab Compose, HouseSim-Mock) stehen nur hier — **nicht** Teil der Anwender-Einrichtung.

- [EHAL](../referenz/ehal.md) — Hardware Access Layer contract
- [HA + evcc lab setup](../dev/ha-lab-setup.md) — Compose Earnie ↔ Home Assistant
- [House simulator](../dev/house-sim.md) — interne Mock-/Dogfood-Bank (`house_sim/`)
- [OpenEMS lab setup](../dev/openems-lab-setup.md) — Compose + Earnie ↔ OpenEMS
- [Branching & Hotfix Playbook](../workflow/branching-hotfix-playbook.md) — Tags, hotfixes, `main`
- [Release Checklist](../workflow/release-checklist.md) — Kandidat → Test auf HA / LoxBerry → Freigabe
- [Shadow Mode](../dev/shadow-mode.md) — Prod-Feed-Recorder (S1) + Shadow-Client (S2+S3, **2.7.f**) implemented; S4 → **2.+1**
- [Regression Suite](../workflow/regression-suite.md) — Golden-Master-Cases vor Release, öffentliche + private Daten (Entwurf)
- [EV return prognosis](../dev/done/ev-return-prognosis.md) — Connect-Phasen bei abwesendem E-Auto (`forecast_when_absent`)
- Arbeitsnotizen, Entwürfe und abgeschlossene Epics: [`docs/dev/`](../dev/) (nicht Teil von Doku-Reviews)
- [Shadow-Betrieb](shadow-betrieb.md) — Prod-Feed-Recorder und Shadow-Client einrichten (Dev)
