"""Host clock-skew diagnostics from HTTP ``Date`` headers (spec early-start-scheduling §7).

No extra request: a hook on ``requests.Session.send``
(installed once by the daemon, :func:`install_requests_hook`) reads the
``Date`` header of every HTTPS response from a public host the cycle already
receives (ENTSO-E, Energy-Charts, Open-Meteo, forecast.solar …).

One sample = server time − local time at the request/response midpoint:

    offset = (Date + 0.5 s) − (received − elapsed / 2)

``Date`` has 1 s resolution (truncated, hence +0.5 s); ``elapsed`` is the time
to the response headers. The estimate is the median of recent samples; each
sample's uncertainty is 0.5 s + elapsed / 2, and slow responses are dropped.

Diagnostics only — no gate: the hold writes at the system-clock tick either
way, and the punctuality log measures against the same clock.
"""
from __future__ import annotations

import ipaddress
import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

logger = logging.getLogger("clock_skew")

WARN_ABOVE_SEC = 2.0
MIN_SAMPLES = 3
MAX_SAMPLES = 30
SAMPLE_MAX_AGE_SEC = 3600.0
# Responses slower than this give too wide a window for a 1 s-resolution clock.
MAX_ELAPSED_SEC = 2.0
# Repeat an unchanged warning at most this often.
WARN_REPEAT_SEC = 3600.0


@dataclass(frozen=True)
class SkewSample:
    at_epoch: float
    offset_sec: float
    uncertainty_sec: float
    host: str


@dataclass(frozen=True)
class SkewEstimate:
    offset_sec: float
    samples: int
    hosts: tuple[str, ...]


_lock = threading.Lock()
_samples: deque[SkewSample] = deque(maxlen=MAX_SAMPLES)
_last_warned_at: float | None = None
_hook_installed = False


def _public_https_host(url: str) -> str | None:
    """Host of an HTTPS URL on the public internet, else None (LAN devices have own clocks)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    host = parts.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".local", ".lan", ".home", ".internal")):
            return None
        return host
    return None if (address.is_private or address.is_loopback or address.is_link_local) else host


def sample_from_response(
    date_header: str, *, received_epoch: float, elapsed_sec: float, host: str
) -> SkewSample | None:
    """One offset sample, or None if the header is unusable or the response too slow."""
    if elapsed_sec < 0 or elapsed_sec > MAX_ELAPSED_SEC:
        return None
    try:
        server = parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError):
        return None
    if server is None or server.tzinfo is None:
        return None
    local_mid = received_epoch - elapsed_sec / 2.0
    return SkewSample(
        at_epoch=received_epoch,
        offset_sec=server.timestamp() + 0.5 - local_mid,
        uncertainty_sec=0.5 + elapsed_sec / 2.0,
        host=host,
    )


def record_sample(sample: SkewSample) -> None:
    with _lock:
        _samples.append(sample)


def observe_response(url: str, headers, elapsed_sec: float, received_epoch: float | None = None) -> None:
    """Record a sample from a response's ``Date`` header (public HTTPS hosts only)."""
    host = _public_https_host(url)
    date_header = headers.get("Date") if headers is not None else None
    if host is None or not date_header:
        return
    sample = sample_from_response(
        date_header,
        received_epoch=time.time() if received_epoch is None else received_epoch,
        elapsed_sec=elapsed_sec,
        host=host,
    )
    if sample is not None:
        record_sample(sample)


def current_estimate(now_epoch: float | None = None) -> SkewEstimate | None:
    """Median offset of recent samples; None with fewer than ``MIN_SAMPLES``."""
    now = time.time() if now_epoch is None else now_epoch
    with _lock:
        recent = [s for s in _samples if now - s.at_epoch <= SAMPLE_MAX_AGE_SEC]
    if len(recent) < MIN_SAMPLES:
        return None
    return SkewEstimate(
        offset_sec=round(statistics.median(s.offset_sec for s in recent), 2),
        samples=len(recent),
        hosts=tuple(sorted({s.host for s in recent})),
    )


def maybe_warn(estimate: SkewEstimate | None, now_epoch: float | None = None) -> bool:
    """Log a warning when |offset| > ``WARN_ABOVE_SEC`` (at most hourly). Returns True if logged."""
    global _last_warned_at
    if estimate is None or abs(estimate.offset_sec) <= WARN_ABOVE_SEC:
        return False
    now = time.time() if now_epoch is None else now_epoch
    if _last_warned_at is not None and now - _last_warned_at < WARN_REPEAT_SEC:
        return False
    _last_warned_at = now
    direction = "nach" if estimate.offset_sec > 0 else "vor"
    logger.warning(
        "Systemuhr geht ca. %.1f s %s (Median aus %d HTTP-Antworten von %s). "
        "Viertelstunden-Takt und Sollwerte richten sich nach der Systemuhr — "
        "Zeitsynchronisation (NTP) des Hosts prüfen.",
        abs(estimate.offset_sec),
        direction,
        estimate.samples,
        ", ".join(estimate.hosts),
    )
    return True


def reset() -> None:
    """Forget samples and warning state (tests)."""
    global _last_warned_at
    with _lock:
        _samples.clear()
    _last_warned_at = None


def install_requests_hook() -> None:
    """Observe ``Date`` headers of all ``requests`` responses (idempotent).

    Wraps ``requests.Session.send`` (``requests.get`` goes through it too);
    ``Response.elapsed`` is set there. A failure inside the observer never
    affects the response.
    """
    global _hook_installed
    if _hook_installed:
        return
    import requests

    original = requests.Session.send

    def send(self, request, **kwargs):
        response = original(self, request, **kwargs)
        try:
            observe_response(
                str(response.url or request.url or ""),
                response.headers,
                response.elapsed.total_seconds() if response.elapsed is not None else -1.0,
            )
        except Exception:  # noqa: BLE001 — diagnostics must never break a request
            logger.debug("clock_skew: observe failed", exc_info=True)
        return response

    requests.Session.send = send  # type: ignore[method-assign]
    _hook_installed = True
