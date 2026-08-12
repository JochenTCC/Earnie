# logger_config.py
import logging
import os
import re
import shutil
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from typing import TextIO

_DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 8
_SIZE_TIME_SUFFIX = "%Y-%m-%d_%H-%M-%S"
_SIZE_TIME_EXT_MATCH = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.\d+)?(\.\w+)?$",
    re.ASCII,
)


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


class SizeAndTimeRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate on weekly boundary or maxBytes; rename with copy+truncate fallback."""

    def __init__(
        self,
        filename: str,
        *,
        when: str = "W0",
        interval: int = 1,
        backupCount: int = _DEFAULT_BACKUP_COUNT,
        maxBytes: int = _DEFAULT_MAX_BYTES,
        encoding: str | None = "utf-8",
        delay: bool = False,
        utc: bool = False,
        atTime=None,
    ) -> None:
        super().__init__(
            filename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            utc=utc,
            atTime=atTime,
        )
        self.maxBytes = maxBytes
        # Unique stamp so mid-week size rolls do not collide with a prior archive.
        self.suffix = _SIZE_TIME_SUFFIX
        self.extMatch = _SIZE_TIME_EXT_MATCH

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if super().shouldRollover(record):
            return True
        return self._size_exceeded()

    def _size_exceeded(self) -> bool:
        if self.maxBytes <= 0:
            return False
        if self.stream is None:
            self.stream = self._open()
        try:
            self.stream.seek(0, os.SEEK_END)
            return self.stream.tell() >= self.maxBytes
        except OSError:
            return False

    def rotate(self, source: str, dest: str) -> None:
        if not os.path.exists(source):
            return
        try:
            os.rename(source, dest)
            return
        except OSError as rename_exc:
            self._rotate_via_copy(source, dest, rename_exc)

    def _rotate_via_copy(
        self, source: str, dest: str, rename_exc: OSError
    ) -> None:
        try:
            shutil.copy2(source, dest)
            with open(
                source,
                "w",
                encoding=self.encoding or "utf-8",
                newline="\n",
            ):
                pass
        except OSError as copy_exc:
            logging.getLogger(__name__).warning(
                "Log rollover failed for %s -> %s (rename: %s; copy: %s)",
                source,
                dest,
                rename_exc,
                copy_exc,
            )
            raise copy_exc from rename_exc

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


def setup_logging(log_file="earnie.log", level=logging.INFO):
    """
    Konfiguriert das globale Logging-System für das gesamte Projekt.
    Erzeugt eine saubere Ausgabe auf der Konsole und schreibt rotierende
    Details in eine Log-Datei (5 MB oder wöchentlich, bis zu 8 Archive).
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

    # --- 1. FILE HANDLER (5 MB oder wöchentlich Mo 00:00, max. 8 Archive) ---
    file_handler = SizeAndTimeRotatingFileHandler(
        log_file,
        when="W0",
        interval=1,
        maxBytes=_DEFAULT_MAX_BYTES,
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
        "Logging-System initialisiert. Log-Datei: '%s' (5 MB oder woechentlich, max %d Archive)",
        log_file,
        _DEFAULT_BACKUP_COUNT,
    )
