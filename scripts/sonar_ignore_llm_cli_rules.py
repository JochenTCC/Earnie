#!/usr/bin/env python3
"""Ignore pythonsecurity S8707/S8705 (agentic LLM CLI taint) on Earnie.

Sets Project Analysis Scope → Ignore Issues on Multiple Criteria via the
SonarCloud Web API. Requires SONAR_TOKEN with Administer permission.

Usage:
    set SONAR_TOKEN=...
    python -m scripts.sonar_ignore_llm_cli_rules
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ORG = "jochentcc"
PROJECT = "JochenTCC_Earnie"
BASE = "https://sonarcloud.io/api"
RULES = (
    ("pythonsecurity:S8707", "**/*"),
    ("pythonsecurity:S8705", "**/*"),
)


def _token() -> str:
    token = (os.environ.get("SONAR_TOKEN") or os.environ.get("SONARCLOUD_TOKEN") or "").strip()
    if not token:
        raise SystemExit(
            "Set SONAR_TOKEN (or SONARCLOUD_TOKEN) with Administer rights on "
            f"{PROJECT}, then re-run."
        )
    return token


def _request(method: str, path: str, token: str, data: dict | None = None) -> dict | None:
    url = f"{BASE}{path}"
    body = None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {path}: {detail}") from exc


def main() -> int:
    token = _token()
    field_values = [
        json.dumps({"ruleKey": rule, "resourceKey": resource}) for rule, resource in RULES
    ]
    _request(
        "POST",
        "/settings/set",
        token,
        {
            "component": PROJECT,
            "key": "sonar.issue.ignore.multicriteria",
            "fieldValues": field_values,
        },
    )
    print(f"Set sonar.issue.ignore.multicriteria on {PROJECT}:")
    for rule, resource in RULES:
        print(f"  - {rule} @ {resource}")
    print("Next SonarCloud analysis will ignore new issues for these rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
