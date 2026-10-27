"""Disk cache for archive responses of settled days.

One JSON file per request (URL and parameters), holding the payload exactly as the service sent
it, so a cache hit returns the same bytes as a new request. Only requests whose last day is
settled are stored (:func:`settled_through`): services revise their most recent values, and those
are always fetched. Writes are atomic (temp file + ``os.replace``), so parallel processes can share
the directory.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Windows denies opening a file while another process replaces it.
READ_ATTEMPTS = 20
READ_RETRY_S = 0.05


def settled_through(settle_days: int) -> date:
    """Last UTC day that ended more than ``settle_days`` days ago."""
    return datetime.now(timezone.utc).date() - timedelta(days=settle_days + 1)


def _params_key(params: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in sorted(params.items())}


class ResponseCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, url: str, params: dict[str, Any]) -> Path:
        parts = urlsplit(url)
        name = "&".join(f"{k}={v}" for k, v in _params_key(params).items())
        return self.root.joinpath(parts.hostname or "", *parts.path.strip("/").split("/"), f"{name}.json")

    def load(self, url: str, params: dict[str, Any]) -> Any | None:
        path = self.path(url, params)
        for attempt in range(READ_ATTEMPTS):
            try:
                with path.open(encoding="utf-8") as fh:
                    entry = json.load(fh)
                break
            except FileNotFoundError:
                return None
            except PermissionError as exc:
                if attempt + 1 == READ_ATTEMPTS:
                    raise RuntimeError(f"Cache-Datei {path} ist nicht lesbar ({exc}).") from exc
                time.sleep(READ_RETRY_S)
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"Cache-Datei {path} ist nicht lesbar ({exc}); bitte löschen.") from exc
        if entry.get("url") != url or entry.get("params") != _params_key(params):
            raise RuntimeError(f"Cache-Datei {path} gehört zu einer anderen Anfrage; bitte löschen.")
        return entry["payload"]

    def store(self, url: str, params: dict[str, Any], payload: Any) -> None:
        path = self.path(url, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "url": url,
            "params": _params_key(params),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "payload": payload,
        }
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem[:40]}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh, separators=(",", ":"))
            os.replace(tmp, path)
        except OSError as exc:
            # Windows refuses the replace while another process reads the target; the next
            # request of the same range writes it again.
            Path(tmp).unlink(missing_ok=True)
            logger.warning("Cache-Datei %s nicht geschrieben (%s).", path, exc)
