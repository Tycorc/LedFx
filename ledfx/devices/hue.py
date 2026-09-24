import logging
import math
import re
import socket
import time
from typing import Optional

import requests
import voluptuous as vol

# Try to import the optional package
try:
    import mbedtls.tls as tls

    MBEDTLS_AVAILABLE = True
except ImportError:
    MBEDTLS_AVAILABLE = False

from ledfx.devices import NetworkedDevice

_LOGGER = logging.getLogger(__name__)

# How the lights of an entertainment zone are laid out along the LedFx pixel
# strip. The Hue app assigns channel ids in the order lights were added to the
# zone, the other orders use the positions the user placed the lights at in
# the Hue app's entertainment area editor.
CHANNEL_ORDERS = [
    "Hue app",
    "Around the room",
    "Left to right",
    "Front to back",
    "Bottom to top",
]

# The v2 streaming protocol addresses channels with a single byte and the
# bridge caps an entertainment configuration at this many channels.
MAX_CHANNELS = 20


class HueDevice(NetworkedDevice):
    """
    Philips Hue device support (Entertainment Mode UDP streaming)
    """

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Required(
                "ip_address",
                description="Hostname or IP address of the Hue bridge",
            ): str,
            vol.Required(
                "group_name",
                description="Entertainment zone group name",
            ): str,
            vol.Optional(
                "channel_order",
                description="Order of the lights along the pixel strip, using the positions from the Hue app",
                default="Hue app",
            ): vol.In(CHANNEL_ORDERS),
            vol.Optional("udp_port", description="port", default=2100): int,
        }
    )

    status: dict[int, tuple[int, int, int]]
    _sock: Optional[socket.socket] = None

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        self._device_type = "Hue"
        self._channel_ids = None
        if not MBEDTLS_AVAILABLE:
            raise Exception(
                "You need to install the python-mbedtls package for Hue to work."
            )

        if "hue_application_id" in self._config:
            # since this is present the init gets called because the device is already known
            self._dtls_client_context = tls.ClientContext(
                tls.DTLSConfiguration(
                    pre_shared_key=(
                        self._config["hue_application_id"],
                        bytes.fromhex(self._config["clientkey"]),
                    ),
                    ciphers=["TLS-PSK-WITH-AES-128-GCM-SHA256"],
                    validate_certificates=False,
                )
            )
            self._apply_channel_order()
        else:
            # The device gets setup for the first time.
            # We call these functions here so the device does only get added if they both succeed!
            # If we won't do that then the device would already be added and a second try wouldn't work
            # until "ledfx" is restartet.
            # But this can't be called if the device is already setup since it would block and the event loop
            # would throw an error. In this case this would get executed in the "async_initialize"
            self._hue_register()
            self._check_hue_bridge()

        self.status = {}

    def config_updated(self, config):
        self._apply_channel_order()

    def _hue_register(self):
        if (self._config.get("username") is None) and (
            self._config.get("clientkey") is None
        ):
            # We need to register this device as application at the Hue Bridge.
            request_data = {
                "devicetype": f"LedFx#{self._config['group_name']}",
                "generateclientkey": True,
            }
            response, _ = self._hue_request("POST", "api", request_data)
            if "success" in response[0]:
                # We successfully registerd
                clientdata = response[0]["success"]
                self.update_config(
                    {
                        "username": clientdata["username"],
                        "clientkey": clientdata["clientkey"],
                    }
                )
            else:
                # The Bridge Link Button needs to be pressed
                raise Exception(
                    "You need to press the Bridge Link Button and retry that again."
                )
        else:
            # We need to check if the credentials are still valid for this device.
            response, _ = self._hue_request(
                "GET", f"api/{self._config['username']}"
            )
            if "error" in response[0]:
                # Credentials are no longer valid - need Bridge Link Button to be pressed and LedFx to be restarted.
                # We delete the invalid credentials here - after a restart a fresh registration will be tried.
                self.update_config({"username": None, "clientkey": None})
                raise Exception(
                    "You need to press the Bridge Link Button and restart LedFx."
                )

    def _check_hue_bridge(self):
        response, _ = self._hue_request("GET", "api/config")
        if response["swversion"] < "1948086000":
            raise Exception(
                "Your Hue Bridge has an outdated Firmware installed. Update it using the Hue App."
            )

    def _hue_request(self, method, api_endpoint, data=None):
        # The Hue Bridge Pro answers plain HTTP with a 301 to HTTPS, which turns the registration POST into a GET.
        url = f"https://{self._config['ip_address']}/{api_endpoint}"

        headers = {"hue-application-key": self._config.get("username")}

        # The bridge certificate is signed by the Hue root CA, not a public one, so verification is skipped
        response = getattr(requests, method.lower())(
            url, json=data, verify=False, headers=headers
        )

        return response.json(), response.headers

    @staticmethod
    def _response_errors(response):
        """Return the error descriptions of a CLIP v2 response, if any."""
        if not isinstance(response, dict):
            return []
        return [
            error.get("description", str(error))
            for error in response.get("errors", [])
        ]

    def _entertainment_groups(self):
        response, _ = self._hue_request(
            "GET", "/clip/v2/resource/entertainment_configuration"
        )

        all_groups = response["data"]
        entertainmentZonesCount = len(all_groups)

        if entertainmentZonesCount == 0:
            raise Exception(
                "You did not setup any Entertainment zones. Do that in the Hue App."
            )

        return {group["id"]: group for group in all_groups}

    def _lights_from_entertainment_group(self, entertainment_id):
        response, _ = self._hue_request(
            "GET",
            f"/clip/v2/resource/entertainment_configuration/{entertainment_id}",
        )
        lights = dict()
        for channel in response["data"][0]["channels"]:
            lights.update(
                {
                    str(channel["channel_id"]): [
                        channel["position"]["x"],
                        channel["position"]["y"],
                        channel["position"]["z"],
                    ]
                }
            )

        if len(lights) > MAX_CHANNELS:
            raise Exception(
                f"{len(lights)} channels found. A Hue entertainment zone can have at most {MAX_CHANNELS}."
            )

        return lights

    def _bridge_max_streams(self):
        """
        How many entertainment zones the bridge can stream at the same time.

        The bridge advertises this on its own entertainment service. Every
        bridge so far, the Bridge Pro included, reports 1.
        """
        try:
            response, _ = self._hue_request(
                "GET", "/clip/v2/resource/entertainment"
            )
            streams = [
                int(service["max_streams"])
                for service in response.get("data", [])
                if service.get("max_streams") is not None
            ]
        except Exception as e:
            _LOGGER.debug(
                "%s: could not read the bridge stream capacity: %s",
                self.name,
                e,
            )
            return 1
        return max(streams) if streams else 1

    def _get_application_id(self):
        _, headers = self._hue_request("GET", "/auth/v1")
        return headers.get("hue-application-id")

    @staticmethod
    def order_channels(lights, order):
        """
        Return the channel ids of an entertainment zone in pixel order.

        Args:
            lights: {channel id: [x, y, z]} as stored in the device config.
                Hue positions run from -1 to 1 with x left to right, y back
                to front and z floor to ceiling.
            order: one of CHANNEL_ORDERS.

        Ties, and "Hue app", fall back to ascending channel id.
        """
        channels = [
            (int(channel_id), [float(p) for p in position])
            for channel_id, position in lights.items()
        ]
        if not channels:
            return []

        if order == "Left to right":
            key = lambda item: (item[1][0], item[0])  # noqa: E731
        elif order == "Front to back":
            key = lambda item: (-item[1][1], item[0])  # noqa: E731
        elif order == "Bottom to top":
            key = lambda item: (item[1][2], item[0])  # noqa: E731
        elif order == "Around the room":
            # Clockwise seen from above with the front (TV side) at the top,
            # starting on the left: left, front, right, back.
            centre_x = sum(p[0] for _, p in channels) / len(channels)
            centre_y = sum(p[1] for _, p in channels) / len(channels)

            def key(item):
                x, y = item[1][0] - centre_x, item[1][1] - centre_y
                angle = math.atan2(y, x)
                return (round((math.pi - angle) % (2 * math.pi), 6), item[0])

        else:
            key = lambda item: item[0]  # noqa: E731

        return [channel_id for channel_id, _ in sorted(channels, key=key)]

    def _apply_channel_order(self):
        """Refresh the pixel to channel mapping from the stored light positions."""
        lights = self._config.get("pixel_lights")
        if not lights:
            self._channel_ids = None
            return
        self._channel_ids = self.order_channels(
            lights, self._config.get("channel_order", "Hue app")
        )
        _LOGGER.debug(
            "%s: channel order %s -> %s",
            self.name,
            self._config.get("channel_order"),
            self._channel_ids,
        )

    @staticmethod
    def build_frame(entertainment_id, pixels, channel_ids=None):
        """
        Build one HueStream v2 frame.

        Args:
            entertainment_id: id of the entertainment configuration.
            pixels: iterable of (r, g, b) in 0..255, floats allowed.
            channel_ids: channel id for each pixel, defaults to the pixel index.
        """
        frame = bytearray(b"HueStream")
        frame.append(2)  # Major version
        frame.append(0)  # Minor version
        frame.append(0)  # Sequence ID
        frame.append(0)  # Reserved
        frame.append(0)  # Reserved
        frame.append(0)  # Color Mode (0=RGB, 1=XY)
        frame.append(0)  # Reserved
        frame.extend(entertainment_id.encode("utf-8"))
        for index, pixel in enumerate(pixels):
            if channel_ids and index < len(channel_ids):
                channel = channel_ids[index]
            else:
                channel = index
            frame.append(channel)
            for value in pixel:
                # 8 bit colour scaled to the 16 bit big endian channel value
                byte = min(255, max(0, int(value)))
                frame.append(byte)
                frame.append(byte)
        return frame

    def _streams_in_use(self):
        """Other active Hue zones on this bridge that already hold a stream."""
        return [
            device
            for device in self._ledfx.devices.values()
            if isinstance(device, HueDevice)
            and device is not self
            and device.is_active()
            and device._config.get("ip_address") == self._config["ip_address"]
        ]

    def _stream_request(self, action):
        """Ask the bridge to start or stop streaming to this zone."""
        response, _ = self._hue_request(
            "PUT",
            f"/clip/v2/resource/entertainment_configuration/{self._config['entertainment_id']}",
            {"action": action},
        )
        return self._response_errors(response)

    def activate(self):
        max_streams = self._config.get("max_streams", 1)
        busy = self._streams_in_use()
        if len(busy) >= max_streams:
            _LOGGER.error(
                "%s: the Hue bridge at %s can stream to %d zone(s) at a time and %s is already streaming. Stop that virtual first.",
                self.name,
                self._config["ip_address"],
                max_streams,
                ", ".join(device.name for device in busy),
            )
            self.set_offline()
            return

        # activate streaming for entertainment zone
        try:
            errors = self._stream_request("start")
        except requests.RequestException as e:
            _LOGGER.warning(
                "%s: could not reach the Hue bridge to start streaming: %s",
                self.name,
                e,
            )
            self.set_offline()
            return
        if errors:
            _LOGGER.error(
                "%s: the Hue bridge refused to start streaming: %s",
                self.name,
                "; ".join(errors),
            )
            self.set_offline()
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        sock.setblocking(False)
        self._sock = self._dtls_client_context.wrap_socket(
            sock, self._config["ip_address"]
        )
        self._sock.connect(
            (self._config["ip_address"], self._config["udp_port"])
        )

        # Since UDP packets can get lost - we need to try handshaking a couple of times
        handshake_success = False
        for _ in range(10):
            try:
                time.sleep(0.2)
                self._sock.do_handshake()
                handshake_success = True
                break
            except Exception as e:
                _LOGGER.warning(
                    "Failed to establish TLS handshake when activating the UDP stream. Retrying. %s",
                    e,
                )

        if not handshake_success:
            _LOGGER.error(
                "%s: could not open the entertainment stream to the Hue bridge. Make sure nothing else is syncing to it, or disconnect and reconnect it from power.",
                self.name,
            )
            self.set_offline()
            return

        super().activate()

    def deactivate(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

        if "entertainment_id" in self._config:
            try:
                errors = self._stream_request("stop")
                if errors:
                    _LOGGER.warning(
                        "%s: stopping the stream returned: %s",
                        self.name,
                        "; ".join(errors),
                    )
            except requests.RequestException as e:
                _LOGGER.warning(
                    "%s: could not reach the Hue bridge to stop streaming: %s",
                    self.name,
                    e,
                )

        super().deactivate()

    def flush(self, data):
        if self._sock is None:
            return

        frame = self.build_frame(
            self._config["entertainment_id"], data, self._channel_ids
        )

        try:
            self._sock.send(frame)
        except Exception:
            self.activate()

    async def async_initialize(self):
        await super().async_initialize()

        # see "self.__init__" why we do this.
        if "hue_application_id" in self._config:
            self._hue_register()
            self._check_hue_bridge()
            hue_application_id = self._config["hue_application_id"]
        else:
            hue_application_id = self._get_application_id()
            self._dtls_client_context = tls.ClientContext(
                tls.DTLSConfiguration(
                    pre_shared_key=(
                        hue_application_id,
                        bytes.fromhex(self._config["clientkey"]),
                    ),
                    ciphers=["TLS-PSK-WITH-AES-128-GCM-SHA256"],
                )
            )

        entertainment_groups = self._entertainment_groups()
        entertainment_id = next(
            id
            for id in entertainment_groups
            if entertainment_groups[id].get("name", "").lower()
            == self._config.get("group_name", "").lower()
        )
        entertainment_group = entertainment_groups[entertainment_id]
        group_id = re.findall(r"\d+", entertainment_group["id_v1"])[0]

        lights = self._lights_from_entertainment_group(entertainment_id)

        config = {
            "group_id": group_id,
            "entertainment_id": entertainment_id,
            "hue_application_id": hue_application_id,
            "pixel_count": len(lights),
            # x, y, z of every channel, used by channel_order to lay the
            # lights out along the pixel strip
            "pixel_lights": lights,
            "max_streams": self._bridge_max_streams(),
            "refresh_rate": 30,
        }

        self.update_config(config)
