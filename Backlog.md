🗺️ Projekt-Roadmap & Backlog
[x] Sicherheit & Config: Umstellung auf .env und globale Timeouts (config.py).

[x] API-Fundament 1: Robustes Error-Handling und Typisierung für aWATTar (awattar_client.py).

[x] API-Fundament 2: Rollierender 24h-Blick und saisonaler Fallback für PV-Prognose (pv_forecast.py).

[x] Daten-Synchronisation: Umstellung auf eine indexbasierte, zeitsynchrone 24-Stunden-Matrix (profile_manager.py & main.py).

[ ] Das Gehirn (optimizer.py): <- Aktueller Fokus

[ ] Beheben des Cutoff-Bugs (Wechsel von fixen Array-Indizes auf dynamische Perzentile/Quantile).

[ ] Integration der PV-Prognose in die Heuristik (Entladesperre/Zwangsladung nur, wenn der Folgetag nicht genug Sonne bringt).

[ ] Loxone-Schnittstelle (loxone_client.py):

[ ] Code-Review des HTTP-Versands und des FTP-Log-Downloads (Hinzufügen von Timeouts und Type Hints).

[ ] Integrationstest & Logging:

[ ] Probelauf des Gesamtsystems und Aufsetzen eines sauberen File-Loggings für den unbeaufsichtigten Dauerbetrieb (z.B. via logging Modul).