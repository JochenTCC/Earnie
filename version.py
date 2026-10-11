"""Zentrale App-Version (Semantic Versioning)."""

from __future__ import annotations

import re
from pathlib import Path

# Local/UI may append a temporary debug id after -dev.N (e.g. 2.7.0-dev.48D1).
# Image/packaging always normalize that away via normalize_for_image_build().
__version__ = "2.7.0-dev.50"

# SemVer core + optional pre-release used for community candidates.
# Trailing debug letters on -dev.N (e.g. D1) are intentionally not captured.
_IMAGE_VERSION_RE = re.compile(
    r"^(\d+\.\d+\.\d+(?:-(?:alpha|beta|rc|dev)\.\d+)?)",
)


def display_version() -> str:
    """UI label; community pre-releases are marked as release candidates."""
    # Local/dev builds (incl. debug suffix) keep the raw string; alpha/beta/rc get "(candidate)".
    if "-" in __version__ and not ("-dev." in __version__):
        return f"{__version__} (candidate)"
    return __version__


def normalize_for_image_build(raw: str) -> str:
    """Keep X.Y.Z or X.Y.Z-(alpha|beta|rc|dev).N; strip debug ids and junk like `` (wip)``."""
    match = _IMAGE_VERSION_RE.match(str(raw or "").strip())
    return match.group(1) if match else "0.0.0"


# setuptools / PEP 440 cannot use letter suffixes on -dev.N; Docker rewrite uses the same core.
__version_pkg__ = normalize_for_image_build(__version__)


def rewrite_version_file_for_image(path: str | Path = "version.py") -> str:
    """Rewrite only the ``__version__`` assignment in place (keeps helpers)."""
    file_path = Path(path).resolve()
    if file_path.name != "version.py":
        raise ValueError(f"Refusing to rewrite non-version file: {file_path.name}")
    text = file_path.read_text(encoding="utf-8")
    match = re.search(
        r"""(__version__\s*=\s*['"])([^'"]+)(['"])""",
        text,
    )
    if not match:
        ver = "0.0.0"
        file_path.write_text(f'__version__ = "{ver}"\n', encoding="utf-8")
        return ver
    ver = normalize_for_image_build(match.group(2))
    updated = text[: match.start(2)] + ver + text[match.end(2) :]
    file_path.write_text(updated, encoding="utf-8")
    return ver
