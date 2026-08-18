"""Unit tests for integration_scanner (no real network I/O — see conftest offline setup)."""
from __future__ import annotations

import os
import socket
from unittest.mock import MagicMock, patch

os.environ.setdefault("EARNIE_OFFLINE", "1")

from integrations import integration_scanner as scanner


class TestHaServiceInfoMapping:
    def _fake_info(self, **overrides):
        info = MagicMock()
        info.addresses = [socket.inet_aton("192.168.178.34")]
        info.port = 80
        info.name = "Home._home-assistant._tcp.local."
        info.properties = {
            b"location_name": b"Home",
            b"uuid": b"4c3da01c696e44c0b07a69072ebb4a3f",
            b"version": b"2026.8.2",
            b"external_url": None,
            b"internal_url": b"http://192.168.178.34",
            b"base_url": b"http://192.168.178.34",
        }
        for key, value in overrides.items():
            setattr(info, key, value)
        return info

    def test_maps_address_and_properties(self):
        backend = scanner._ha_service_info_to_backend(self._fake_info())
        assert backend.kind == "home_assistant"
        assert backend.host == "192.168.178.34"
        assert backend.method == "mdns"
        assert backend.name == "Home"
        assert backend.extra["base_url"] == "http://192.168.178.34"
        assert backend.extra["uuid"] == "4c3da01c696e44c0b07a69072ebb4a3f"

    def test_no_addresses_returns_none(self):
        info = self._fake_info(addresses=[])
        assert scanner._ha_service_info_to_backend(info) is None

    def test_falls_back_to_service_name_without_location_name(self):
        info = self._fake_info(properties={})
        backend = scanner._ha_service_info_to_backend(info)
        assert backend.name == "Home"


class TestSsdpParsing:
    _LOXONE_RESPONSE = (
        "HTTP/1.1 200 OK\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        "EXT:\r\n"
        "CACHE-CONTROL: max-age=100\r\n"
        "LOCATION: http://192.168.178.20:80/upnp.xml\r\n"
        "SERVER: Loxone Miniserver Miniserver-Gen2 UPnP/1.0\r\n"
        "ST: upnp:rootdevice\r\n"
        "USN: uuid:ecec3020-f7d6-4e34-9309-729b438c7ec0::upnp:rootdevice\r\n"
        "\r\n"
    ).encode("utf-8")

    _OTHER_RESPONSE = (
        "HTTP/1.1 200 OK\r\n"
        "CACHE-CONTROL: max-age=1800\r\n"
        "LOCATION: http://192.168.178.1:49000/igddesc.xml\r\n"
        "SERVER: FRITZ!Box 7530 AX UPnP/1.0 AVM FRITZ!Box 7530 AX 256.08.25\r\n"
        "ST: upnp:rootdevice\r\n"
        "\r\n"
    ).encode("utf-8")

    def test_parses_headers_case_insensitively(self):
        headers = scanner._parse_ssdp_headers(self._LOXONE_RESPONSE)
        assert headers["server"] == "Loxone Miniserver Miniserver-Gen2 UPnP/1.0"
        assert headers["location"] == "http://192.168.178.20:80/upnp.xml"

    def test_loxone_signature_matches(self):
        headers = scanner._parse_ssdp_headers(self._LOXONE_RESPONSE)
        backend = scanner._ssdp_response_to_backend("192.168.178.20", headers)
        assert backend is not None
        assert backend.kind == "loxone"
        assert backend.host == "192.168.178.20"
        assert backend.port == 80
        assert backend.method == "ssdp"

    def test_non_loxone_signature_is_ignored(self):
        headers = scanner._parse_ssdp_headers(self._OTHER_RESPONSE)
        assert scanner._ssdp_response_to_backend("192.168.178.1", headers) is None

    def test_missing_location_defaults_to_port_80(self):
        headers = {"server": "Loxone Miniserver Test UPnP/1.0"}
        backend = scanner._ssdp_response_to_backend("10.0.0.5", headers)
        assert backend.port == 80

    def test_malformed_location_falls_back_to_port_80(self):
        headers = {
            "server": "Loxone Miniserver Test UPnP/1.0",
            "location": "not-a-url",
        }
        backend = scanner._ssdp_response_to_backend("10.0.0.5", headers)
        assert backend.port == 80


class TestOpenemsFelixSignature:
    def test_www_authenticate_felix_matches(self):
        assert scanner._looks_like_felix_console(
            {"www-authenticate": 'Basic realm="Apache Felix Web Console"'}, ""
        )

    def test_body_felix_matches(self):
        assert scanner._looks_like_felix_console({}, "<title>Apache Felix</title>")

    def test_unrelated_response_does_not_match(self):
        assert not scanner._looks_like_felix_console({}, "<title>Hello</title>")


class TestDiscoverHomeAssistant:
    def test_wraps_zeroconf_browse_and_dedupes(self):
        info = MagicMock()
        info.addresses = [socket.inet_aton("192.168.178.34")]
        info.port = 80
        info.name = "Home._home-assistant._tcp.local."
        info.properties = {b"location_name": b"Home"}

        zc_instance = MagicMock()
        zc_instance.get_service_info.return_value = info

        def fake_browser(zc, service_type, listener):
            listener.add_service(zc, service_type, "Home._home-assistant._tcp.local.")
            listener.add_service(zc, service_type, "Home._home-assistant._tcp.local.")
            return MagicMock()

        fake_zeroconf_module = MagicMock()
        fake_zeroconf_module.Zeroconf.return_value = zc_instance
        fake_zeroconf_module.ServiceBrowser.side_effect = fake_browser

        with patch.dict("sys.modules", {"zeroconf": fake_zeroconf_module}), patch(
            "time.sleep"
        ):
            results = scanner.discover_home_assistant(timeout_sec=0.01)

        assert len(results) == 1
        assert results[0].host == "192.168.178.34"

    def test_oserror_returns_empty_list(self):
        fake_zeroconf_module = MagicMock()
        fake_zeroconf_module.Zeroconf.side_effect = OSError("no network")
        with patch.dict("sys.modules", {"zeroconf": fake_zeroconf_module}):
            assert scanner.discover_home_assistant(timeout_sec=0.01) == []


class TestDiscoverLoxone:
    def test_collects_and_dedupes_matching_responses(self):
        responses = [
            (TestSsdpParsing._LOXONE_RESPONSE, ("192.168.178.20", 1900)),
            (TestSsdpParsing._LOXONE_RESPONSE, ("192.168.178.20", 1900)),
            (TestSsdpParsing._OTHER_RESPONSE, ("192.168.178.1", 1900)),
        ]

        class _FakeSocket:
            def __init__(self):
                self._responses = list(responses)

            def settimeout(self, _value):
                pass

            def setsockopt(self, *_args):
                pass

            def sendto(self, *_args):
                pass

            def recvfrom(self, _bufsize):
                if not self._responses:
                    raise socket.timeout()
                return self._responses.pop(0)

            def close(self):
                pass

        with patch("socket.socket", return_value=_FakeSocket()), patch(
            "time.monotonic", side_effect=[0, 0, 1, 2, 3]
        ):
            results = scanner.discover_loxone(timeout_sec=3.0)

        assert len(results) == 1
        assert results[0].host == "192.168.178.20"

    def test_oserror_on_send_returns_empty_list(self):
        class _FakeSocket:
            def settimeout(self, _value):
                pass

            def setsockopt(self, *_args):
                pass

            def sendto(self, *_args):
                raise OSError("network unreachable")

            def close(self):
                pass

        with patch("socket.socket", return_value=_FakeSocket()):
            assert scanner.discover_loxone(timeout_sec=1.0) == []


class TestDiscoverOpenems:
    def test_reports_open_ports_without_felix_confirmation(self):
        with patch.object(scanner, "_tcp_port_open", return_value=True), patch.object(
            scanner, "_probe_felix_console", return_value=False
        ):
            results = scanner.discover_openems(["10.0.0.5"], timeout_sec=0.1)
        assert len(results) == 1
        assert results[0].kind == "openems"
        assert results[0].extra["open_ports"] == [8080, 8085]
        assert results[0].extra["felix_console_confirmed"] is False

    def test_no_open_ports_yields_no_hit(self):
        with patch.object(scanner, "_tcp_port_open", return_value=False):
            assert scanner.discover_openems(["10.0.0.5"], timeout_sec=0.1) == []

    def test_felix_confirmation_only_checked_when_8080_open(self):
        def port_open(host, port, *, timeout_sec):
            return port == 8085

        with patch.object(scanner, "_tcp_port_open", side_effect=port_open), patch.object(
            scanner, "_probe_felix_console"
        ) as felix_probe:
            results = scanner.discover_openems(["10.0.0.5"], timeout_sec=0.1)
        felix_probe.assert_not_called()
        assert results[0].extra["felix_console_confirmed"] is False


class TestLocalIpv4HostsForScan:
    def test_builds_254_candidates_excluding_self(self):
        fake_probe = MagicMock()
        fake_probe.getsockname.return_value = ("192.168.178.137", 12345)
        with patch("socket.socket", return_value=fake_probe):
            hosts = scanner.local_ipv4_hosts_for_scan()
        assert len(hosts) == 253
        assert "192.168.178.137" not in hosts
        assert "192.168.178.1" in hosts
        assert "192.168.178.254" in hosts

    def test_oserror_returns_empty_list(self):
        fake_probe = MagicMock()
        fake_probe.connect.side_effect = OSError("no route")
        with patch("socket.socket", return_value=fake_probe):
            assert scanner.local_ipv4_hosts_for_scan() == []

    def test_rejects_non_24_subnet(self):
        import pytest

        with pytest.raises(ValueError):
            scanner.local_ipv4_hosts_for_scan(subnet_size=16)


class TestScanForBackends:
    def test_full_passive_runs_ha_and_loxone_but_not_openems(self):
        with patch.object(
            scanner, "discover_home_assistant", return_value=["ha"]
        ) as ha_mock, patch.object(
            scanner, "discover_loxone", return_value=["lox"]
        ) as lox_mock, patch.object(
            scanner, "discover_openems", return_value=["openems"]
        ) as openems_mock:
            results = scanner.scan_for_backends("full_passive")
        assert results == ["ha", "lox"]
        ha_mock.assert_called_once()
        lox_mock.assert_called_once()
        openems_mock.assert_not_called()

    def test_full_active_also_runs_openems(self):
        with patch.object(scanner, "discover_home_assistant", return_value=[]), patch.object(
            scanner, "discover_loxone", return_value=[]
        ), patch.object(
            scanner, "discover_openems", return_value=["openems"]
        ) as openems_mock:
            results = scanner.scan_for_backends("full_active")
        assert results == ["openems"]
        openems_mock.assert_called_once()

    def test_targeted_filters_to_only_kinds(self):
        with patch.object(
            scanner, "discover_home_assistant", return_value=["ha"]
        ) as ha_mock, patch.object(scanner, "discover_loxone", return_value=["lox"]) as lox_mock:
            results = scanner.scan_for_backends("targeted", only_kinds=["home_assistant"])
        assert results == ["ha"]
        ha_mock.assert_called_once()
        lox_mock.assert_not_called()

    def test_targeted_without_kinds_falls_back_to_both_passive(self):
        with patch.object(
            scanner, "discover_home_assistant", return_value=["ha"]
        ) as ha_mock, patch.object(scanner, "discover_loxone", return_value=["lox"]) as lox_mock:
            results = scanner.scan_for_backends("targeted", only_kinds=None)
        assert results == ["ha", "lox"]
        ha_mock.assert_called_once()
        lox_mock.assert_called_once()

    def test_targeted_openems_not_run_even_if_requested(self):
        """OpenEMS is active-only — targeted mode must never trigger a port scan."""
        with patch.object(scanner, "discover_openems") as openems_mock:
            scanner.scan_for_backends("targeted", only_kinds=["openems"])
        openems_mock.assert_not_called()
