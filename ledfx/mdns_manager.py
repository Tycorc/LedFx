import asyncio
import logging

from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

from ledfx.events import Event
from ledfx.utils import async_fire_and_forget

_LOGGER = logging.getLogger(__name__)


class ZeroConfRunner:
    """Manage zeroconf discovery and WLED registration."""

    def __init__(self, ledfx):
        self.aiobrowser = None
        self.aiozc = None
        self._closing: set[asyncio.Task[None]] = set()
        self._ledfx = ledfx

        def on_shutdown(e):
            async_fire_and_forget(self.async_close(), self._ledfx.loop)

        self._ledfx.events.add_listener(on_shutdown, Event.LEDFX_SHUTDOWN)

    def on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ):
        """Callback function for service state change."""
        async_fire_and_forget(
            self.async_on_service_state_change(
                zeroconf=zeroconf,
                service_type=service_type,
                name=name,
                state_change=state_change,
            ),
            self._ledfx.loop,
        )

    async def async_on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ):
        """Asynchronous function for handling service state change."""
        _LOGGER.debug(
            "Service %s of type %s state changed: %s",
            name,
            service_type,
            state_change,
        )
        if state_change is not ServiceStateChange.Added:
            return

        async_fire_and_forget(
            self.add_wled_device(zeroconf, service_type, name),
            self._ledfx.loop,
        )

    async def add_wled_device(
        self, zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:
        """Forward discoveries to add_new_device, which handles duplicates."""
        info = AsyncServiceInfo(service_type, name)
        await info.async_request(zeroconf, 3000)
        if info.server:
            hostname = str(info.server).rstrip(".")
            _LOGGER.info("Found WLED device: %s", hostname)

            device_type = "wled"
            device_config = {"ip_address": hostname}

            def handle_exception(future):
                future.exception()

            async_fire_and_forget(
                self._ledfx.devices.add_new_device(device_type, device_config),
                loop=self._ledfx.loop,
                exc_handler=handle_exception,
            )

    async def discover_wled_devices(self) -> None:
        """Asynchronous function for discovering WLED devices."""
        previous = self.aiobrowser, self.aiozc
        self.aiozc = AsyncZeroconf()
        services = ["_wled._tcp.local."]
        _LOGGER.info("Browsing for WLED devices...")
        self.aiobrowser = AsyncServiceBrowser(
            self.aiozc.zeroconf,
            services,
            handlers=[self.on_service_state_change],
        )
        # Close the previous scan's instance, or its sockets and thread leak.
        # It is swapped out before the await so overlapping scans can't leak
        # one, and the close is its own task so cancelling this scan can't
        # cut it short.
        task = asyncio.ensure_future(self._close(*previous))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)
        await asyncio.shield(task)

    async def async_close(self) -> None:
        """Asynchronous function for closing zeroconf listener."""
        await self._close(self.aiobrowser, self.aiozc)
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

    @staticmethod
    async def _close(
        aiobrowser: AsyncServiceBrowser | None, aiozc: AsyncZeroconf | None
    ) -> None:
        if aiobrowser and aiozc:
            _LOGGER.debug("Closing zeroconf listener.")
            try:
                await aiobrowser.async_cancel()
            finally:
                await aiozc.async_close()
            _LOGGER.debug("Zeroconf closed.")
