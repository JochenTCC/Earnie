"""Zustandstabellen für die Logiktests (analog zu ``fields.py``).

Ein neuer Zustand ist eine neue Zeile, kein neuer Test.
"""
from __future__ import annotations

# --- Optimierer-Dienst (ui/pages/page_daemon.py) ---------------------------------------
# Zustand, Status-Text, PID-Text, Start frei, Stop frei, Neustart frei.
# "unknown" lässt alle drei Aktionen zu (gewollt: der Nutzer soll den Zustand auflösen können).
DAEMON_STATES = [
    ("running", "läuft", "4242", False, True, True),
    ("stopped", "gestoppt", "—", True, False, True),
    ("unknown", "unbekannt", "—", True, True, True),
]

# Aktion: Button-Key, Zustand davor, aufgerufene Funktion, Zustand danach, Status-Text danach.
DAEMON_ACTIONS = [
    ("daemon_start", "stopped", "start", "running", "läuft"),
    ("daemon_stop", "running", "stop", "stopped", "gestoppt"),
    ("daemon_restart", "running", "restart", "running", "läuft"),
    ("daemon_restart", "stopped", "restart", "running", "läuft"),
]

# Bestätigungstext je Aktion (heute vom folgenden st.rerun() verworfen, siehe Backlog-Bugfixes).
DAEMON_SUCCESS_TEXT = {
    "start": "main.py gestartet.",
    "stop": "main.py gestoppt.",
    "restart": "main.py neu gestartet.",
}

# Logdatei mit gemischten Levels; zwei Zeilen (Traceback) tragen kein [LEVEL].
MIXED_LOG = "\n".join(
    [
        "2026-10-22 10:00:00 [DEBUG] debug eins",
        "2026-10-22 10:00:01 [INFO] info eins",
        "2026-10-22 10:00:02 [WARNING] warnung eins",
        "2026-10-22 10:00:03 [ERROR] fehler eins",
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in <module>',
        "2026-10-22 10:00:04 [CRITICAL] kritisch eins",
        "2026-10-22 10:00:05 [INFO] info zwei",
    ]
)


# --- Navigation (ui/navigation.py::build_page_specs), N1 ---------------------------------
# Eingaben: UI-Modi, Setup-Zustand. Erwartung: url_paths in Reihenfolge, Startseite.
# Setup-Schlüssel: restricted (is_setup_navigation_restricted), betrieb (is_betrieb_unlocked),
# planning (is_planning_ready), editor (is_scenario_editor_unlocked), sb_setup (needs_sb_setup),
# cloud_demo (is_cloud_demo).
_S2S, _EXPLORER, _LIVE, _PRICE = "sunset2sunset", "scenario_explorer", "live_environment", "price_forecast"
_READY = dict(restricted=False, betrieb=True, planning=True, editor=True, sb_setup=False, cloud_demo=False)

NAV_CASES = [
    # id, Modi, Setup-Abweichungen, erwartete url_paths, Startseite
    ("full-all-ready", [_S2S, _EXPLORER, _LIVE], {},
     ["cockpit", "devices", "consumer-analysis", "house-config", "scenario-editor", "tariffs",
      "scenario-explorer", "smarthome-backend", "ehal-com", "optimizer-daemon"], "cockpit"),
    ("full-needs-sb-setup", [_S2S, _EXPLORER, _LIVE], {"sb_setup": True},
     ["cockpit", "devices", "consumer-analysis", "house-config", "scenario-editor", "tariffs",
      "scenario-explorer", "smarthome-backend"], "cockpit"),
    ("sunset-only", [_S2S], {},
     ["cockpit", "devices", "house-config", "scenario-editor", "tariffs"], "cockpit"),
    ("sunset-and-explorer-no-live", [_S2S, _EXPLORER], {},
     ["cockpit", "devices", "house-config", "scenario-editor", "tariffs", "scenario-explorer"], "cockpit"),
    ("no-sunset-explorer-is-start", [_EXPLORER, _LIVE], {},
     ["house-config", "scenario-editor", "tariffs", "scenario-explorer", "smarthome-backend",
      "ehal-com", "optimizer-daemon"], "scenario-explorer"),
    ("betrieb-locked", [_S2S, _EXPLORER, _LIVE], {"betrieb": False},
     ["house-config", "scenario-editor", "tariffs", "scenario-explorer", "smarthome-backend",
      "ehal-com", "optimizer-daemon"], "scenario-explorer"),
    ("planning-not-ready-no-explorer", [_S2S, _EXPLORER, _LIVE], {"planning": False, "betrieb": False},
     ["house-config", "scenario-editor", "tariffs", "smarthome-backend", "ehal-com", "optimizer-daemon"],
     "house-config"),
    ("scenario-editor-locked", [_S2S, _EXPLORER, _LIVE], {"editor": False},
     ["cockpit", "devices", "consumer-analysis", "house-config", "scenario-explorer",
      "smarthome-backend", "ehal-com", "optimizer-daemon"], "cockpit"),
    ("price-forecast-only", [_PRICE], {"betrieb": False},
     ["price-forecast", "house-config", "scenario-editor", "tariffs"], "price-forecast"),
    ("price-forecast-with-cockpit", [_S2S, _PRICE], {},
     ["cockpit", "devices", "price-forecast", "house-config", "scenario-editor", "tariffs"], "cockpit"),
    # Eingeschränkte Navigation (Onboarding)
    ("restricted-live-sb-missing", [_S2S, _EXPLORER, _LIVE], {"restricted": True, "sb_setup": True},
     ["house-config", "scenario-editor", "tariffs", "smarthome-backend"], "smarthome-backend"),
    ("restricted-live-sb-configured", [_S2S, _EXPLORER, _LIVE], {"restricted": True},
     ["house-config", "scenario-editor", "tariffs", "smarthome-backend", "ehal-com", "optimizer-daemon"],
     "smarthome-backend"),
    ("restricted-explorer-only-forces-echtzeit", [_EXPLORER], {"restricted": True},
     ["house-config", "scenario-editor", "tariffs", "smarthome-backend", "ehal-com", "optimizer-daemon"],
     "house-config"),
    ("restricted-explorer-only-cloud-demo", [_EXPLORER], {"restricted": True, "cloud_demo": True},
     ["house-config", "scenario-editor", "tariffs"], "house-config"),
    ("restricted-editor-locked", [_S2S, _LIVE], {"restricted": True, "editor": False},
     ["house-config", "smarthome-backend", "ehal-com", "optimizer-daemon"], "smarthome-backend"),
]

NAV_READY = _READY

# Abschnitt je url_path (Menüstruktur)
NAV_SECTIONS = {
    "cockpit": "Live-Cockpit",
    "devices": "Live-Cockpit",
    "consumer-analysis": "Live-Cockpit",
    "price-forecast": "Live-Cockpit",
    "house-config": "Konfiguration",
    "scenario-editor": "Konfiguration",
    "tariffs": "Konfiguration",
    "scenario-explorer": "Konfiguration",
    "smarthome-backend": "Daemon Control",
    "ehal-com": "Daemon Control",
    "optimizer-daemon": "Daemon Control",
}

# EARNIE_UI_MODES (N2): Wert, erwartete Modus-Schlüssel, Sidebar-info-Fragmente, warning-Fragmente
UI_MODES_ENV_CASES = [
    ("sunset2sunset", ["sunset2sunset"], [], False),
    ("scenario_explorer,live_environment", ["scenario_explorer", "live_environment"], [], False),
    ("  Scenario_Explorer , LIVE_environment ", ["scenario_explorer", "live_environment"], [], False),
    ("live_environment,sunset2sunset", ["sunset2sunset", "live_environment"], [], False),
    ("bogus", ["sunset2sunset"], [], True),
    ("bogus,scenario_explorer", ["scenario_explorer"], [], False),
    ("historical", ["sunset2sunset"], ["Historischer Tag"], True),
    ("backtesting", ["sunset2sunset"], ["umbenannt", "scenario_explorer"], True),
    ("scenario_exploration", ["sunset2sunset"], ["scenario_exploration", "scenario_explorer"], True),
    ("backtesting,scenario_explorer", ["scenario_explorer"], ["umbenannt"], False),
]
