import logging
from json import JSONDecodeError

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.api.websocket import WebsocketConnection
from ledfx.events import ClientSyncEvent

_LOGGER = logging.getLogger(__name__)

ACTIONS = ["sync"]


class ClientEndpoint(RestEndpoint):
    ENDPOINT_PATH = "/api/clients"

    async def get(self) -> web.Response:
        """Get the list of connected clients with metadata"""

        clients = await WebsocketConnection.get_all_clients_metadata()

        return await self.bare_request_success(clients)

    async def post(self, request: web.Request) -> web.Response:
        """Perform action for client"""

        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()

        action = data.get("action")

        if action is None:
            return await self.invalid_request(
                'Required attribute "action" was not provided'
            )

        if action not in ACTIONS:
            return await self.invalid_request(f"Action {action} is not in {ACTIONS}")

        if action == "sync":
            client_id = data.get("client_id", "unknown")
            self._ledfx.events.fire_event(ClientSyncEvent(client_id))

        response = {"status": "success", "action": action}
        return await self.bare_request_success(response)
