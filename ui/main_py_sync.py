"""Hilfetexte zur Synchronisation app.py ↔ main.py."""

from optimizer import schedule as optimization_schedule

_MAX_MIN = optimization_schedule.APP_MAIN_SYNC_MAX_WAIT_SECONDS // 60

MAIN_PY_SYNC_HELP = (
    "**main.py** führt die Produktiv-Optimierung zu Viertelstunden-Takten aus "
    "(:00 / :15 / :30 / :45).\n\n"
    "Die App aktualisiert Chart und Simulation, sobald der Lauf für den "
    "**aktuellen Slot** abgeschlossen ist (typisch wenige Sekunden). "
    f"Spätestens nach ca. **{_MAX_MIN} Min** wird mit dem letzten Plan fortgefahren."
)


def main_py_sync_status_message(wait_sec: int, reason: str) -> str:
    _ = reason
    return (
        f"⏳ **Warte auf main.py** für den aktuellen Viertelstunden-Slot "
        f"(noch ca. **{wait_sec} s**)."
    )
