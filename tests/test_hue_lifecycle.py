"""Exercise Hue startup and failure paths without a bridge or UDP traffic."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from ledfx.devices.hue import HueDevice


@pytest.fixture
def device(monkeypatch):
    # Skip registration/DTLS key setup, keeping the real lifecycle and base
    # set_offline implementation (which calls the subclass's deactivate).
    dev = object.__new__(HueDevice)
    dev._config = {
        "name": "Test Hue",
        "group_name": "Test area",
        "ip_address": "192.0.2.1",
        "udp_port": 2100,
        "entertainment_id": "00000000-0000-0000-0000-000000000001",
        "pixel_count": 2,
        "username": "test-application-key",
        "clientkey": "00" * 16,
    }
    dev._id = "test-hue"
    dev._active = False
    dev._online = True
    dev._pixels = None
    dev._sock = None
    dev._stream_started = False
    dev._channel_ids = [0, 1]
    dev._destination = "192.0.2.1"
    dev._ledfx = SimpleNamespace(devices={}, events=MagicMock())
    dev._dtls_client_context = MagicMock()
    dev._stream_request = MagicMock(return_value=[])
    monkeypatch.setattr("ledfx.devices.hue.time.sleep", lambda _: None)
    monkeypatch.setattr("ledfx.devices.hue.socket.socket", MagicMock())
    yield dev
    if dev.is_active():
        dev.deactivate()


def test_valid_saved_credentials_accept_v1_object_response(device):
    device._hue_request = MagicMock(
        return_value=({"config": {}, "lights": {}, "groups": {}}, {})
    )
    device._hue_register()
    assert device._config["username"] == "test-application-key"


def test_invalid_saved_credentials_request_registration(device):
    device._hue_request = MagicMock(return_value=([{"error": {"type": 1}}], {}))
    device.update_config = lambda values: device._config.update(values)
    with pytest.raises(Exception, match="Bridge Link Button"):
        device._hue_register()
    assert device._config["username"] is None
    assert device._config["clientkey"] is None


def test_successful_stream_handshakes_once_then_releases(device):
    transport = device._dtls_client_context.wrap_socket.return_value
    device.activate()
    assert device.is_active()
    transport.do_handshake.assert_called_once()
    device.deactivate()
    assert not device.is_active()
    transport.close.assert_called_once()
    assert [c.args[0] for c in device._stream_request.call_args_list] == [
        "start",
        "stop",
    ]


def test_refused_stream_does_not_stop_another_apps_session(device):
    device._stream_request.return_value = ["entertainment service busy"]
    device.activate()
    assert not device.is_active()
    assert not device.is_online()
    device._stream_request.assert_called_once_with("start")
    device._dtls_client_context.wrap_socket.assert_not_called()


def test_bridge_connection_failure_does_not_attempt_stop(device):
    device._stream_request.side_effect = requests.ConnectionError("offline")
    device.activate()
    assert not device.is_online()
    device._stream_request.assert_called_once_with("start")


def test_socket_connect_failure_releases_accepted_stream(device):
    transport = device._dtls_client_context.wrap_socket.return_value
    transport.connect.side_effect = OSError("network unreachable")
    device.activate()
    assert not device.is_online()
    assert not device.is_active()
    transport.close.assert_called_once()
    assert [c.args[0] for c in device._stream_request.call_args_list] == [
        "start",
        "stop",
    ]


def test_failed_handshake_releases_stream_and_socket(device):
    transport = device._dtls_client_context.wrap_socket.return_value
    transport.do_handshake.side_effect = OSError("handshake timeout")
    device.activate()
    assert not device.is_online()
    assert not device.is_active()
    assert transport.do_handshake.call_count == 10
    transport.close.assert_called_once()
    assert [c.args[0] for c in device._stream_request.call_args_list] == [
        "start",
        "stop",
    ]


def test_reconnect_closes_old_socket_before_starting_again(device):
    first, second = MagicMock(), MagicMock()
    device._dtls_client_context.wrap_socket.side_effect = [first, second]
    device.activate()
    first.send.side_effect = OSError("lost connection")
    device.flush([(1, 2, 3), (4, 5, 6)])
    first.close.assert_called_once()
    assert device._sock is second
    assert device.is_active()
    assert [c.args[0] for c in device._stream_request.call_args_list] == [
        "start",
        "stop",
        "start",
    ]


def test_socket_wrap_failure_closes_raw_socket(device, monkeypatch):
    raw = MagicMock()
    monkeypatch.setattr("ledfx.devices.hue.socket.socket", MagicMock(return_value=raw))
    device._dtls_client_context.wrap_socket.side_effect = OSError("TLS error")
    device.activate()
    raw.close.assert_called_once()
    assert not device.is_active()
    assert not device.is_online()
    assert [c.args[0] for c in device._stream_request.call_args_list] == [
        "start",
        "stop",
    ]


def test_stopping_never_started_device_does_not_stop_bridge(device):
    device.deactivate()
    device._stream_request.assert_not_called()


def test_second_zone_is_refused_without_touching_bridge(device):
    active = object.__new__(HueDevice)
    active._config = {"name": "First zone", "ip_address": "192.0.2.1"}
    active._active = True
    device._ledfx.devices["first"] = active
    try:
        device.activate()
        assert not device.is_active()
        device._stream_request.assert_not_called()
        assert active.is_active()
    finally:
        active._active = False
