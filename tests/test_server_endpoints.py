"""Production HTTPS base URL and TLS-loud post_json."""
from __future__ import annotations

import logging
from ssl import SSLCertVerificationError
from unittest.mock import patch
from urllib.error import URLError

from runtime_store.server_endpoints import (
    PATH_PING,
    PATH_REVIEW,
    post_json,
    url_for,
)


def test_url_for_ping_is_https_without_port() -> None:
    assert url_for(PATH_PING) == "https://cloudserver.earnie-hems.com/ping"


def test_url_for_review_is_https_without_port() -> None:
    assert url_for(PATH_REVIEW) == "https://cloudserver.earnie-hems.com/review"


def test_post_json_logs_certificate_error_loud(caplog) -> None:
    url = url_for(PATH_PING)
    cert_err = SSLCertVerificationError("certificate verify failed")
    with patch(
        "runtime_store.server_endpoints.urllib_request.urlopen",
        side_effect=URLError(cert_err),
    ) as mock_open:
        with caplog.at_level(logging.ERROR, logger="runtime_store.server_endpoints"):
            status = post_json(url, b"{}", 5.0, log_name="usage_ping")
    assert status == 0
    assert mock_open.call_args.args[0].full_url == url
    assert "usage_ping: certificate error" in caplog.text
    assert "http://" not in mock_open.call_args.args[0].full_url
