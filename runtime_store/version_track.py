"""Track last-run app version; warn on downgrade (2.6.k)."""
from __future__ import annotations

import logging
import re
from functools import total_ordering

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

LAST_RUN_VERSION_FILE = "last_run_version"
_PENDING_WARNING: str | None = None

_SEMVER_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$"
)


@total_ordering
class _SemVer:
    """Minimal SemVer for downgrade detection (release > pre-release of same core)."""

    __slots__ = ("major", "minor", "patch", "pre")

    def __init__(self, text: str) -> None:
        match = _SEMVER_RE.match(text.strip())
        if not match:
            raise ValueError(f"invalid SemVer: {text!r}")
        self.major = int(match.group(1))
        self.minor = int(match.group(2))
        self.patch = int(match.group(3))
        self.pre = match.group(4)  # None for official

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _SemVer):
            return NotImplemented
        return (
            self.major,
            self.minor,
            self.patch,
            self.pre,
        ) == (other.major, other.minor, other.patch, other.pre)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _SemVer):
            return NotImplemented
        core_self = (self.major, self.minor, self.patch)
        core_other = (other.major, other.minor, other.patch)
        if core_self != core_other:
            return core_self < core_other
        # Official (pre is None) is greater than any pre-release of same core.
        if self.pre is None and other.pre is None:
            return False
        if self.pre is None:
            return False
        if other.pre is None:
            return True
        return self.pre < other.pre


def last_run_version_path() -> str:
    return runtime_path(LAST_RUN_VERSION_FILE)


def _read_stored() -> str | None:
    path = last_run_version_path()
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return None
    return text or None


def _write_stored(version: str) -> None:
    path = last_run_version_path()
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(version.strip() + "\n")


def is_downgrade(current: str, previous: str) -> bool:
    """True when *current* is older than *previous* (SemVer)."""
    try:
        return _SemVer(current) < _SemVer(previous)
    except ValueError:
        return False


def check_and_record_version(current: str | None = None) -> str | None:
    """Compare *current* to ``runtime/last_run_version``; update the file.

    Returns a German warning string if this start is a downgrade, else None.
    Also stashes the warning for :func:`consume_downgrade_warning` (UI).
    """
    global _PENDING_WARNING
    if current is None:
        from version import __version__

        current = __version__

    previous = _read_stored()
    warning: str | None = None
    if previous and is_downgrade(current, previous):
        warning = (
            f"Downgrade erkannt: zuletzt lief Earnie {previous}, jetzt {current}. "
            "Konfiguration und Sidecars können bereits für die neuere Version "
            "migriert sein. Vor dem Weiterarbeiten ein Backup empfehlen."
        )
        logger.warning("%s", warning)
    try:
        _write_stored(current)
    except OSError as exc:
        logger.warning("last_run_version konnte nicht geschrieben werden: %s", exc)
    _PENDING_WARNING = warning
    return warning


def consume_downgrade_warning() -> str | None:
    """Return and clear the pending downgrade warning (for Streamlit once)."""
    global _PENDING_WARNING
    message = _PENDING_WARNING
    _PENDING_WARNING = None
    return message
