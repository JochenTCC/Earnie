"""Hilfetexte zur Synchronisation app.py ↔ main.py."""

MAIN_PY_SYNC_HELP = (
    "**main.py** führt die Produktiv-Optimierung zu Viertelstunden-Takten aus "
    "(:00 / :15 / :30 / :45).\n\n"
    "Die App wartet, bis der Lauf für den **aktuellen Slot** abgeschlossen ist, "
    "bevor Chart und Simulation aktualisiert werden (ca. 1 Min nach Slot-Wechsel)."
)


def main_py_sync_status_message(wait_sec: int, reason: str) -> str:
    if reason == "delay":
        return (
            f"⏳ **Synchronisation mit main.py:** Aktualisierung in ca. **{wait_sec} s**"
        )
    return (
        f"⏳ **Warte auf main.py-Durchlauf** für den aktuellen Slot "
        f"(noch ca. **{wait_sec} s**)."
    )
