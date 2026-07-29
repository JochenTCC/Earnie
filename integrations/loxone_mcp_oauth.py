"""Headless OAuth 2.1 for the official Loxone 17.1 MCP plugin.

Mirrors the flow documented by community clients (dynamic registration, HTML
login form + PKCE, token exchange). Credentials are the same Miniserver user
as local HTTP Basic (``LOXONE_USER`` / ``LOXONE_PASS``).
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import uuid
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests

_FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_INPUT_TAG_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""(\w+)\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


class McpOAuthError(RuntimeError):
    """OAuth probe failed (credentials, relay, or protocol)."""


def entry_origin_from_mcp_url(mcp_url: str) -> str:
    parsed = urlparse(str(mcp_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise McpOAuthError(f"invalid MCP URL for OAuth: {mcp_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def obtain_access_token(
    entry_origin: str,
    username: str,
    password: str,
    *,
    timeout_sec: float = 20.0,
    redirect_port: int = 41678,
    client_name: str = "earnie-mcp-probe",
    session: requests.Session | None = None,
) -> str:
    """Run headless OAuth against a resolved relay origin; return access_token."""
    user = str(username or "").strip()
    if not user:
        raise McpOAuthError("MCP OAuth requires username")
    origin = str(entry_origin or "").rstrip("/")
    if not origin.lower().startswith("https://"):
        raise McpOAuthError(f"MCP OAuth refuses non-HTTPS origin: {origin}")
    redirect_uri = f"http://localhost:{int(redirect_port)}/callback"
    http = session or requests.Session()
    resource = _discover_resource(http, origin, timeout_sec)
    client_id = _register_client(
        http, origin, redirect_uri, client_name, timeout_sec
    )
    verifier, challenge = _pkce_pair()
    code = _login_for_code(
        http,
        origin,
        username=user,
        password=str(password or ""),
        client_id=client_id,
        challenge=challenge,
        resource=resource,
        redirect_uri=redirect_uri,
        timeout_sec=timeout_sec,
    )
    return _exchange_code(
        http,
        origin,
        client_id=client_id,
        code=code,
        verifier=verifier,
        resource=resource,
        redirect_uri=redirect_uri,
        timeout_sec=timeout_sec,
    )


def _discover_resource(
    http: requests.Session, origin: str, timeout_sec: float
) -> str:
    url = f"{origin}/mcp/.well-known/oauth-protected-resource"
    response = _request(http, "GET", url, timeout_sec=timeout_sec)
    if response.status_code >= 400:
        raise McpOAuthError(
            f"protected-resource metadata HTTP {response.status_code}"
        )
    body = _json_object(response)
    resource = str(body.get("resource") or "").strip()
    if not resource:
        raise McpOAuthError('protected-resource metadata missing "resource"')
    return resource


def _register_client(
    http: requests.Session,
    origin: str,
    redirect_uri: str,
    client_name: str,
    timeout_sec: float,
) -> str:
    url = f"{origin}/mcp/oauth/register"
    payload = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    response = _request(
        http,
        "POST",
        url,
        timeout_sec=timeout_sec,
        json_body=payload,
        headers={"Content-Type": "application/json"},
    )
    if response.status_code >= 400:
        raise McpOAuthError(f"client registration HTTP {response.status_code}")
    body = _json_object(response)
    client_id = str(body.get("client_id") or "").strip()
    if not client_id:
        raise McpOAuthError("registration response missing client_id")
    return client_id


def _login_for_code(
    http: requests.Session,
    origin: str,
    *,
    username: str,
    password: str,
    client_id: str,
    challenge: str,
    resource: str,
    redirect_uri: str,
    timeout_sec: float,
) -> str:
    authorize = (
        f"{origin}/mcp/oauth/authorize"
        f"?response_type=code"
        f"&client_id={requests.utils.quote(client_id)}"
        f"&redirect_uri={requests.utils.quote(redirect_uri, safe='')}"
        f"&code_challenge={requests.utils.quote(challenge)}"
        f"&code_challenge_method=S256"
        f"&state={uuid.uuid4()}"
        f"&resource={requests.utils.quote(resource, safe='')}"
    )
    form_resp = _request(
        http,
        "GET",
        authorize,
        timeout_sec=timeout_sec,
        headers={"Accept": "text/html"},
        allow_redirects=False,
    )
    if form_resp.status_code != 200:
        raise McpOAuthError(
            f"authorize returned HTTP {form_resp.status_code}; expected login form"
        )
    form = _parse_login_form(form_resp.text or "")
    if form is None:
        raise McpOAuthError("could not locate login form on authorize page")
    body = _fill_login_form(form["inputs"], username=username, password=password)
    action = urljoin(authorize, form["action"] or authorize)
    method = str(form["method"] or "POST").upper()
    post = _request(
        http,
        method,
        action,
        timeout_sec=timeout_sec,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        allow_redirects=False,
    )
    location = post.headers.get("Location") or post.headers.get("location")
    if not location:
        if post.status_code == 200:
            raise McpOAuthError(
                "login was rejected (form re-rendered) — check LOXONE_USER/"
                "LOXONE_PASS; MCP plugin may require HTTP port 80"
            )
        raise McpOAuthError(
            f"login POST HTTP {post.status_code} with no redirect"
        )
    callback = urlparse(urljoin(action, location))
    params = parse_qs(callback.query)
    if params.get("error"):
        err = params["error"][0]
        desc = (params.get("error_description") or [""])[0]
        raise McpOAuthError(f"authorization failed: {err} {desc}".strip())
    codes = params.get("code") or []
    if not codes or not codes[0]:
        raise McpOAuthError("no authorization code in login callback")
    return codes[0]


def _exchange_code(
    http: requests.Session,
    origin: str,
    *,
    client_id: str,
    code: str,
    verifier: str,
    resource: str,
    redirect_uri: str,
    timeout_sec: float,
) -> str:
    url = f"{origin}/mcp/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": resource,
    }
    response = _request(
        http,
        "POST",
        url,
        timeout_sec=timeout_sec,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code >= 400:
        raise McpOAuthError(f"token exchange HTTP {response.status_code}")
    body = _json_object(response)
    token = str(body.get("access_token") or "").strip()
    if not token:
        raise McpOAuthError("token response missing access_token")
    return token


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, _b64url(digest)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_login_form(html: str) -> dict[str, Any] | None:
    tag_match = _FORM_TAG_RE.search(html or "")
    if not tag_match:
        return None
    tag = tag_match.group(0)
    attrs = dict(_ATTR_RE.findall(tag))
    inputs: list[dict[str, str]] = []
    for match in _INPUT_TAG_RE.finditer(html or ""):
        inp_attrs = {k.lower(): v for k, v in _ATTR_RE.findall(match.group(0))}
        inputs.append(
            {
                "name": inp_attrs.get("name") or "",
                "type": (inp_attrs.get("type") or "text").lower(),
                "value": inp_attrs.get("value") or "",
            }
        )
    return {
        "action": attrs.get("action") or attrs.get("Action") or "",
        "method": attrs.get("method") or attrs.get("Method") or "POST",
        "inputs": inputs,
    }


def _fill_login_form(
    inputs: list[dict[str, str]],
    *,
    username: str,
    password: str,
) -> dict[str, str]:
    body: dict[str, str] = {}
    for inp in inputs:
        name = str(inp.get("name") or "").strip()
        if not name:
            continue
        kind = str(inp.get("type") or "text").lower()
        if kind == "password":
            body[name] = password
        elif kind in ("text", "email") or re.search(r"user|name|login", name, re.I):
            body[name] = username
        else:
            body[name] = str(inp.get("value") or "")
    return body


def _json_object(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise McpOAuthError("OAuth endpoint returned non-JSON") from exc
    if not isinstance(body, dict):
        raise McpOAuthError("OAuth JSON root is not an object")
    return body


def _request(
    http: requests.Session,
    method: str,
    url: str,
    *,
    timeout_sec: float,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    data: Any = None,
    allow_redirects: bool = True,
) -> requests.Response:
    try:
        return http.request(
            method,
            url,
            headers=headers,
            json=json_body,
            data=data,
            timeout=timeout_sec,
            allow_redirects=allow_redirects,
        )
    except requests.RequestException as exc:
        raise McpOAuthError(f"OAuth HTTP error: {exc}") from exc
