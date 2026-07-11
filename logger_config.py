# logger_config.py
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from typing import TextIO


def configure_utf8_stdio() -> None:
    """Setzt stdout/stderr auf UTF-8 (relevant unter Windows und bei Shell-Umleitung)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


class _TeeStream:
    """Schreibt parallel in Original-Stream und UTF-8-Logdatei."""

    def __init__(self, original: TextIO, log_file: TextIO) -> None:
        self._original = original
        self._log_file = log_file

    def write(self, data: str) -> int:
        self._original.write(data)
        self._log_file.write(data)
        return len(data)

    def flush(self) -> None:
        self._original.flush()
        self._log_file.flush()

    def __getattr__(self, name: str):
        return getattr(self._original, name)


def attach_utf8_log_file(path: str) -> TextIO:
    """Dupliziert stdout/stderr zusätzlich in eine UTF-8-Logdatei."""
    log_dir = os.path.dirname(path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    handle = open(path, "w", encoding="utf-8", newline="\n")
    configure_utf8_stdio()
    sys.stdout = _TeeStream(sys.stdout, handle)
    sys.stderr = _TeeStream(sys.stderr, handle)
    return handle


def setup_logging(log_file="earnie.log", level=logging.INFO):
    """
    Konfiguriert das globale Logging-System für das gesamte Projekt.
    Erzeugt eine saubere Ausgabe auf der Konsole und schreibt rotierende
    Details in eine Log-Datei.
    """
    configure_utf8_stdio()

    # Verzeichnis für Logfile erstellen, falls Pfade genutzt werden
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # Root-Logger holen und Grundeinstellung setzen
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Falls der Logger bereits Handler hat (z.B. bei Re-Importen), diese säubern
    if root_logger.handlers:
        root_logger.handlers.clear()

    # --- FORMATIERUNG ---
    # Datei-Format: Sehr detailliert für Fehlersuche (Zeit, Level, Modul, Zeile, Nachricht)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] (%(name)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Konsolen-Format: Schlank für den schnellen Blick im Terminal
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    # --- 1. FILE HANDLER (Rotierend, maximal 5 Dateien à 5 MB, UTF-8 codiert) ---
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=5 * 1024 * 1024, 
        backupCount=5, 
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)

    # --- 2. CONSOLE HANDLER (Für Live-Ausgabe im Terminal) ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)

    # Handler an Root-Logger binden
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info("📝 Logging-System initialisiert. Log-Datei: '%s' (max 5x5MB)", log_file)