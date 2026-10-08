from json import JSONDecodeError

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.utils import async_fire_and_forget, set_name_to_icon


def handle_exception(future):
    future.exception()


class FindDevicesEndpoint(RestEndpoint):
    """REST end-point for detecting and adding wled devices"""

    ENDPOINT_PATH = "/api/find_devices"

    async def post(self, request: web.Request) -> web.Response:
        """Find and add all WLED devices on the LAN."""
        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()

        name_to_icon = data.get("name_to_icon")

        if name_to_icon is None:
            return await self.invalid_request(
                'Required attribute "name_to_icon" was not provided'
            )
        set_name_to_icon(name_to_icon)

        async_fire_and_forget(
            self._ledfx.zeroconf.discover_wled_devices(),
            loop=self._ledfx.loop,
            exc_handler=handle_exception,
        )
        return await self.request_success()

    async def get(self) -> web.Response:
        """Handle HTTP GET requests."""
        async_fire_and_forget(
            self._ledfx.zeroconf.discover_wled_devices(),
            loop=self._ledfx.loop,
            exc_handler=handle_exception,
        )
        return await self.request_success()
