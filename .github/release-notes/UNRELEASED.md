# Unreleased — Sammelnotizen für das nächste Release

Beim nächsten Tag in `.github/release-notes/v<version>.md` übernehmen und hier leeren (siehe `docs/spec/release-checklist.md` §1).

## Breaking / Bitte prüfen

- **Home Assistant: Vorzeichen der Batterieleistung prüfen.** Earnie rechnet den Hausverbrauch jetzt durchgehend als `PV + Netz + Batterie`, mit Netz `+` = Bezug und Batterie `+` = Entladen ([Vorzeichenkonvention](../../docs/spec/ehal.md#units-and-sign-convention-frozen)). Bisher wurde die Batterie im Live-Hausverbrauch mit falschem Vorzeichen eingerechnet, und der abgeleitete Hausverbrauch (`sens_power_consumers`) nutzte `PV − Netz − Batterie`. Wer in der EHAL-Zuordnung (`ehal.ha.sign`) die Batterieleistung bewusst gedreht hat, damit der alte Wert plausibel aussah, muss das prüfen: Die Batterie-Entity muss nach der Zuordnung beim **Entladen positiv** sein. Gleiches gilt für Loxone: `Earnie_Batterie_Leistung` muss beim Entladen positiv sein (Earnie dreht nicht mehr).
