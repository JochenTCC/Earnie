# logger_config.py
import logging
import os
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from typing import TextIO

from runtime_store.month_file_rotation import (
    ARCHIVE_EXT_MATCH,
    ARCHIVE_SUFFIX,
    DEFAULT_BACKUP_COUNT,
    compute_next_month_rollover,
    rotate_file,
)

_DEFAULT_BACKUP_COUNT = DEFAULT_BACKUP_COUNT


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


class MonthRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate at local month start; rename with copy+truncate fallback. No size trigger."""

    def __init__(
        self,
        filename: str,
        *,
        backupCount: int = _DEFAULT_BACKUP_COUNT,
        encoding: str | None = "utf-8",
        delay: bool = False,
        utc: bool = False,
        atTime=None,
    ) -> None:
        # Parent requires a when= value; computeRollover/shouldRollover are overridden.
        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            utc=utc,
            atTime=atTime,
        )
        self.suffix = ARCHIVE_SUFFIX
        self.extMatch = ARCHIVE_EXT_MATCH
        self.rolloverAt = int(compute_next_month_rollover(time.time()))

    def computeRollover(self, currentTime: int) -> int:
        return int(compute_next_month_rollover(currentTime))

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        return int(time.time()) >= self.rolloverAt

    def rotate(self, source: str, dest: str) -> None:
        rotate_file(source, dest)

    def doRollover(self) -> None:
        current_time = int(time.time())
        time_tuple = time.gmtime(current_time) if self.utc else time.localtime(current_time)
        dfn = self._unique_archive_name(time_tuple)
        if self.stream:
            self.stream.close()
            self.stream = None
        try:
            self.rotate(self.baseFilename, dfn)
            if self.backupCount > 0:
                for path in self.getFilesToDelete():
                    os.remove(path)
        finally:
            if not self.delay and self.stream is None:
                self.stream = self._open()
            self.rolloverAt = self.computeRollover(current_time)

    def _unique_archive_name(self, time_tuple: time.struct_time) -> str:
        stamp = time.strftime(self.suffix, time_tuple)
        dfn = self.rotation_filename(f"{self.baseFilename}.{stamp}")
        if not os.path.exists(dfn):
            return dfn
        n = 1
        while os.path.exists(f"{dfn}.{n}"):
            n += 1
        return f"{dfn}.{n}"


# Backward-compatible alias (former size+weekly handler name).
SizeAndTimeRotatingFileHandler = MonthRotatingFileHandler


def setup_logging(log_file="earnie.log", level=logging.INFO):
    """
    Konfiguriert das globale Logging-System für das gesamte Projekt.
    Erzeugt eine saubere Ausgabe auf der Konsole und schreibt rotierende
    Details in eine Log-Datei (monatlich, bis zu 12 Archive).
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

    # --- 1. FILE HANDLER (monatlich, max. 12 Archive) ---
    file_handler = MonthRotatingFileHandler(
        log_file,
        backupCount=_DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
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

    logging.info(
        "Logging-System initialisiert. Log-Datei: '%s' (monatlich, max %d Archive)",
        log_file,
        _DEFAULT_BACKUP_COUNT,
    )
