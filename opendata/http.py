"""HTTP layer: one retry policy for every public data feed.

Retries HTTP 429 / 502 / 503 / 504 with exponential backoff (``Retry-After`` wins when the server
sends it), raises the last error when the attempts are used up, and raises
:class:`ApiUnreachableError` at the first connection error or timeout (asking again only repeats
the wait). :func:`fetch_budget` caps all requests inside a block, retries and waits included.
:meth:`Session.get_json_cached` serves settled archive days from the disk cache (:mod:`opendata.cache`).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

from opendata.cache import ResponseCache, settled_through

RETRY_STATUS = frozenset({429, 502, 503, 504})
RETRY_ATTEMPTS = 5
RETRY_BASE_SECONDS = 2.0


class ApiUnreachableError(RuntimeError):
    """Connection-level failure (no route, timeout, DNS): the host is not answering.

    Raised at the first failed attempt and never retried: every further request of
    the same run would only wait for the next timeout.
    """


class FetchBudgetExceeded(RuntimeError):
    """The requests inside :func:`fetch_budget` did not finish within its budget."""


class Response(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


# (url, params, timeout seconds) -> response
Transport = Callable[[str, dict[str, Any], float], Response]


def requests_transport(url: str, params: dict[str, Any], timeout_s: float) -> Response:
    return requests.get(url, params=params, timeout=timeout_s)


_deadline: ContextVar[tuple[float, float] | None] = ContextVar("opendata_fetch_deadline", default=None)


@contextmanager
def fetch_budget(seconds: float) -> Iterator[None]:
    """Cap all requests inside the block (retries and waits included) at ``seconds``.

    Interactive pages use this so a slow or rate-limited service ends in a visible error
    instead of minutes of retries. Cache hits are unaffected.
    """
    token = _deadline.set((time.monotonic() + seconds, seconds))
    try:
        yield
    finally:
        _deadline.reset(token)


def _remaining_budget_s() -> float | None:
    state = _deadline.get()
    return None if state is None else state[0] - time.monotonic()


def _budget_exceeded(last_error: Exception | None) -> FetchBudgetExceeded:
    state = _deadline.get()
    seconds = state[1] if state is not None else 0.0
    detail = f" Letzter Fehler: {last_error}" if last_error is not None else ""
    return FetchBudgetExceeded(
        f"Klima- und Marktdaten konnten nicht innerhalb von {seconds:.0f} s geladen werden "
        f"(langsames Netz oder Ratenlimit).{detail} Bitte später erneut versuchen."
    )


def _retry_after_s(response: Response | None) -> float | None:
    if response is None:
        return None
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None  # HTTP date form: fall back to the backoff


class Session:
    """GET JSON with the shared retry policy.

    ``pause_after_s`` maps a host name to a pause after each successful request (rate limits of
    services that are asked many times in a row). Without ``cache_dir`` nothing is cached.
    """

    def __init__(
        self,
        *,
        timeout_s: float,
        transport: Transport = requests_transport,
        pause_after_s: Mapping[str, float] | None = None,
        attempts: int = RETRY_ATTEMPTS,
        base_wait_s: float = RETRY_BASE_SECONDS,
        cache_dir: Path | None = None,
    ) -> None:
        self.timeout_s = float(timeout_s)
        self.transport = transport
        self.pause_after_s = dict(pause_after_s or {})
        self.attempts = attempts
        self.base_wait_s = base_wait_s
        self.cache = ResponseCache(cache_dir) if cache_dir is not None else None

    def get_json_cached(
        self,
        url: str,
        params: dict[str, Any],
        *,
        last_day: date,
        settle_days: int,
        timeout_s: float | None = None,
    ) -> Any:
        """Like :meth:`get_json`; a request whose ``last_day`` is settled is cached on disk."""
        if self.cache is None or last_day > settled_through(settle_days):
            return self.get_json(url, params, timeout_s=timeout_s)
        payload = self.cache.load(url, params)
        if payload is None:
            payload = self.get_json(url, params, timeout_s=timeout_s)
            self.cache.store(url, params, payload)
        return payload

    def get_json(self, url: str, params: dict[str, Any], *, timeout_s: float | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            timeout = self.timeout_s if timeout_s is None else float(timeout_s)
            remaining = _remaining_budget_s()
            if remaining is not None:
                if remaining <= 0:
                    raise _budget_exceeded(last_error)
                timeout = min(timeout, remaining)
            response: Response | None = None
            try:
                response = self.transport(url, params, timeout)
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    payload = response.json()
                    self._pause(url)
                    return payload
                last_error = requests.HTTPError(f"{response.status_code} for url: {url}", response=response)
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise ApiUnreachableError(f"API nicht erreichbar ({url}): {type(exc).__name__}") from exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status not in RETRY_STATUS:
                    raise
                last_error = exc
                response = exc.response
            except requests.RequestException as exc:
                last_error = exc
            if attempt + 1 < self.attempts:
                wait = _retry_after_s(response)
                self._sleep(self.base_wait_s * (2**attempt) if wait is None else wait, last_error)
        assert last_error is not None  # every non-returning attempt sets it
        raise last_error

    def _pause(self, url: str) -> None:
        pause = self.pause_after_s.get(urlsplit(url).hostname or "")
        if pause:
            time.sleep(pause)

    @staticmethod
    def _sleep(seconds: float, last_error: Exception | None) -> None:
        remaining = _remaining_budget_s()
        if remaining is not None and seconds >= remaining:
            raise _budget_exceeded(last_error)
        time.sleep(seconds)
