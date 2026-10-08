from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.configuration.fields import VirtualIdStr


class EffectsEndpoint(RestEndpoint):
    ENDPOINT_PATH = "/api/virtuals/{virtual_id}/fallback"

    async def get(self, virtual_id: str) -> web.Response:
        """Fires a fallback trigger which will cause a virtual to return to its
        default effect
        """
        if self._ledfx.virtuals.get(virtual_id) is None:
            return await self.invalid_request(f"Virtual with ID {virtual_id} not found")

        self._ledfx.virtuals.fire_fallback(VirtualIdStr(virtual_id))
        response = {"status": "success"}
        return await self.bare_request_success(response)
