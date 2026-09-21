"""HA add-on Ingress nginx template rendering (packaging/homeassistant-addon)."""
from __future__ import annotations

from pathlib import Path

_ADDON = Path(__file__).resolve().parents[1] / "packaging" / "homeassistant-addon" / "earnie"
_RUN_SH = _ADDON / "run.sh"
_TEMPLATE = _ADDON / "nginx" / "ingress.conf.template"
_STARTING_HTML = _ADDON / "nginx" / "earnie-starting.html"

# Realistic Supervisor ingress_entry (token shape from dogfood log 20b22c55_…).
_SAMPLE_ENTRY = "/api/hassio_ingress/ybwsM4ii2jvfpzSaw4gJyFT7Z2jkuEc371s-YiRJH7M"


def test_run_sh_renders_nginx_conf_with_python_not_sed() -> None:
    text = _RUN_SH.read_text(encoding="utf-8")
    assert "_sed_entry=" not in text
    assert 'sed "s|' not in text
    assert 'text.replace("__INGRESS_ENTRY__", entry)' in text


def test_ingress_template_placeholder_replaced() -> None:
    raw = _TEMPLATE.read_text(encoding="utf-8")
    assert "__INGRESS_ENTRY__" in raw
    rendered = raw.replace("__INGRESS_ENTRY__", _SAMPLE_ENTRY)
    assert "__INGRESS_ENTRY__" not in rendered
    assert f"rewrite ^ {_SAMPLE_ENTRY}$request_uri break;" in rendered
    assert "location ~ ^/api/hassio_ingress/[^/]+" in rendered


def test_ingress_startup_page_mapped_to_http_200() -> None:
    raw = _TEMPLATE.read_text(encoding="utf-8")
    assert "error_page 502 503 504 =200 /earnie-starting.html;" in raw
    assert "alias /etc/earnie-addon/nginx/earnie-starting.html;" in raw
    html = _STARTING_HTML.read_text(encoding="utf-8")
    assert "Earnie startet noch" in html
    assert 'http-equiv="refresh"' in html
