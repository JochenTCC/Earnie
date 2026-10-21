"""Fixed earnie-server base URL and path constants.

Production posts go to ``SERVER_BASE`` (HTTPS via Caddy, no port) plus a path.
Tests inject a full URL via ``endpoint_url`` / ``resolve_endpoint`` and stay
offline. ``post_json`` POSTs with default certificate verification (no
``verify=False``) and never falls back to HTTP.
"""
from __future__ import annotations

import logging
import ssl
from urllib import error as urllib_error
from urllib import request as urllib_request

SERVER_BASE = "https://cloudserver.earnie-hems.com"
PATH_PING = "/ping"
PATH_REVIEW = "/review"

logger = logging.getLogger(__name__)


def url_for(path: str) -> str:
    """Compose ``SERVER_BASE`` + path. ``path`` must start with ``/``."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"path must start with '/', got {path!r}")
    return f"{SERVER_BASE.rstrip('/')}{path}"


def resolve_endpoint(path: str, override: str | None) -> str:
    """Return the production URL for ``path``, or a non-empty ``override``.

    ``override is None`` → ``url_for(path)``. A blank string raises ``ValueError``
    (tests must pass a real URL or omit the argument).
    """
    if override is None:
        return url_for(path)
    text = str(override).strip()
    if not text:
        raise ValueError("endpoint_url override must be a non-empty URL")
    return text


def _is_ssl_failure(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, urllib_error.URLError):
        return isinstance(exc.reason, ssl.SSLError)
    return False


def post_json(url: str, body: bytes, timeout: float, *, log_name: str) -> int:
    """POST JSON body; return HTTP status or 0 on transport failure.

    Uses the default SSL context (certificate verification on). Certificate
    errors are logged at ERROR; other transport failures at WARNING. Never
    rewrites the URL to HTTP.
    """
    request = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return int(response.getcode())
    except urllib_error.HTTPError as exc:
        return int(exc.code)
    except (urllib_error.URLError, TimeoutError, OSError, ValueError, ssl.SSLError) as exc:
        if _is_ssl_failure(exc):
            logger.error("%s: certificate error: %s", log_name, exc)
            return 0
        logger.warning("%s: transport failed: %s", log_name, exc)
        return 0
