import logging
import socket

import numpy as np
from ledfx_senders.encoders import encode_openrgb
from openrgb import OpenRGBClient
from pydantic import Field

from ledfx.configuration.fields import X_REQUIRED
from ledfx.configuration.plugin import TypedConfig
from ledfx.devices import NetworkedDevice

_LOGGER = logging.getLogger(__name__)


class OpenRGB(NetworkedDevice):
    """OpenRGB protocol device support"""

    class Config(NetworkedDevice.Config):
        name: str = Field(
            description="Friendly name for the device",
            json_schema_extra={X_REQUIRED: True},
        )
        openrgb_id: int = Field(
            0,
            description="ID of OpenRGB device (within OpenRGB).",
            ge=0,
            json_schema_extra={X_REQUIRED: True},
        )
        pixel_count: int = Field(
            1,
            description="Number of individual pixels",
            ge=1,
            json_schema_extra={X_REQUIRED: True},
        )
        port: int = Field(
            6742,
            description="Port for the UDP device",
            ge=1,
            le=65535,
            json_schema_extra={X_REQUIRED: True},
        )

    config = TypedConfig(Config)

    def __init__(self, ledfx, config):
        """Initializes an OpenRGB device."""
        super().__init__(ledfx, config)
        self._device_type = "OpenRGB"
        self._ledfx = ledfx
        self.ip_address = self.config.ip_address
        self.port = self.config.port
        self.openrgb_device_id = self.config.openrgb_id

    def activate(self):
        """Activates the OpenRGB device."""
        try:
            self.openrgb_device = OpenRGBClient(
                self.ip_address,
                self.port,
                self.name,
                3,  # protocol_version
            )
            self.openrgb_device = self.openrgb_device.devices[self.openrgb_device_id]

        except (ConnectionRefusedError, TimeoutError):
            _LOGGER.warning(
                "OpenRGB server %s:%s not reachable for device %s. Is OpenRGB server running?",
                self.ip_address,
                self.port,
                self.openrgb_device_id,
            )
            self.set_offline()
            return

        except IndexError:
            _LOGGER.warning(
                "Couldn't find OpenRGB device ID: %s", self.openrgb_device_id
            )
            self.set_offline()
            return

        device_supports_direct = False
        for mode in self.openrgb_device.modes:
            if mode.name.lower() == "direct":
                device_supports_direct = True
        if not device_supports_direct:
            _LOGGER.warning(
                "%s doesn't support direct mode - not supported by LedFx.",
                self.openrgb_device_id,
            )
            self.set_offline()
            return
        else:
            self._online = True
            super().activate()

    def deactivate(self):
        """Deactivates the OpenRGB device."""
        super().deactivate()

    def flush(self, data: np.ndarray):
        """Flush LED data to the OpenRGB device."""
        try:
            OpenRGB.send_out(
                self.openrgb_device.comms.sock,
                data,
                self.openrgb_device.id,
            )
        except AttributeError:
            self.activate()

        except (
            ConnectionAbortedError,
            ConnectionResetError,
            BrokenPipeError,
        ) as e:
            _LOGGER.warning(
                "Device %s connection issue (%s): %s",
                self.name,
                type(e).__name__,
                e,
            )
            self.set_offline()

    @staticmethod
    def send_out(sock: socket.socket, data: np.ndarray, device_id: int):
        """Sends the given data to the specified device using the provided socket."""
        packet = encode_openrgb(data, device_id)
        # TCP may accept only part of a large frame in one send().
        sock.sendall(packet)
