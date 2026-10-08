import logging

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.devices import available_com_ports

_LOGGER = logging.getLogger(__name__)


class InfoEndpoint(RestEndpoint):
    ENDPOINT_PATH = "/api/comports"

    async def get(self) -> web.Response:
        """Get the list of available COM ports."""
        return await self.bare_request_success([p for p in available_com_ports() if p])
