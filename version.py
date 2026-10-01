"""Zentrale App-Version (Semantic Versioning)."""

from __future__ import annotations

import re
from pathlib import Path

__version__ = "2.7.0-dev.6"

# SemVer core + optional pre-release used for community candidates.
_IMAGE_VERSION_RE = re.compile(
    r"^(\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?)",
)


def display_version() -> str:
    """UI label; pre-releases are marked as release candidates."""
    if "-" in __version__:
        return f"{__version__} (candidate)"
    return __version__


def normalize_for_image_build(raw: str) -> str:
    """Keep X.Y.Z or X.Y.Z-(alpha|beta|rc).N; strip junk like `` (wip)`` for setuptools."""
    match = _IMAGE_VERSION_RE.match(str(raw or "").strip())
    return match.group(1) if match else "0.0.0"


def rewrite_version_file_for_image(path: str | Path = "version.py") -> str:
    """Rewrite only the ``__version__`` assignment in place (keeps helpers)."""
    file_path = Path(path)
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
