# Entwickler-Dokumentation

Diese Seiten gehören nicht zur [Anwender-Dokumentation](../README.md). Sie sind technisch, teils englisch, und richten sich an Entwickler:innen sowie an den Entwickler-Betrieb.

## Specs (Englisch/technisch)

Lab- und Simulationsumgebungen (HA Lab Compose, HouseSim-Mock) sind nur hier beschrieben und gehören nicht zur Anwender-Einrichtung.

- [EHAL](../referenz/ehal.md) – Vertrag des Hardware Access Layer.
- [HA + evcc lab setup](../dev/ha-lab-setup.md) – Compose-Umgebung Earnie ↔ Home Assistant.
- [House simulator](../dev/house-sim.md) – interne Mock- und Dogfood-Umgebung (`house_sim/`).
- [OpenEMS lab setup](../dev/openems-lab-setup.md) – Compose-Umgebung Earnie ↔ OpenEMS.
- [Branching & Hotfix Playbook](../workflow/branching-hotfix-playbook.md) – `main`, `release/x.y`, Tags und Hotfixes.
- [Release Checklist](../workflow/release-checklist.md) – Ablauf vom Kandidaten über den Test auf HA / LoxBerry bis zur Freigabe.
- [Shadow Mode](../dev/shadow-mode.md) – Prod-Feed-Recorder (S1) und Shadow-Client (S2+S3, **2.7.f**) sind umgesetzt; S4 folgt in **2.+1**.
- [Regression Suite](../workflow/regression-suite.md) – Golden-Master-Cases vor jedem Release, mit öffentlichen und privaten Daten.
- [EV return prognosis](../dev/done/ev-return-prognosis.md) – Connect-Phasen bei abwesendem E-Auto (`forecast_when_absent`).

Arbeitsnotizen, Entwürfe und abgeschlossene Epics liegen unter [`docs/dev/`](../dev/). Sie sind nicht Teil der Doku-Reviews.

## Entwickler-Betrieb

- [Greenfield Dev-Stack](../einrichtung/greenfield-dev-stack.md) – lokale Ersteinrichtung für Hauskonfigurator und Backtesting.
- [OpenEMS-Lab](../einrichtung/openems-lab.md) – Earnie mit OpenEMS Edge/UI; der Kommunikationscheck steht in der Spezifikation.
- [HA ↔ Loxone Bridge-Generator](../dev/done/ha-loxone-bridge.md) – Prototyp (POC): erzeugt die Brücke für die Delta 3 aus einer Mapping-Datei, Loxone → HA per Webhook.

- [Shadow-Betrieb](shadow-betrieb.md) – Prod-Feed-Recorder und Shadow-Client einrichten.
