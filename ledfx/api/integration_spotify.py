import copy
import logging
from json import JSONDecodeError

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.integrations.spotify import Spotify

_LOGGER = logging.getLogger(__name__)


class QLCEndpoint(RestEndpoint):
    """REST end-point for querying and managing a Spotify integration"""

    ENDPOINT_PATH = "/api/integrations/spotify/{integration_id}"

    def _save_triggers(self, integration: Spotify) -> None:
        for entry in self._ledfx.config.integrations:
            if entry.id == integration.id:
                entry.data = copy.deepcopy(integration.triggers)
        self._ledfx.config_store.request_save()

    async def _trigger_fields(
        self, data: dict[str, object]
    ) -> tuple[object, ...] | web.Response:
        """(scene_id, song_id, song_name, song_position) from a request body, or the
        failure response if one is missing or the scene is unknown.
        """
        fields = ("scene_id", "song_id", "song_name", "song_position")
        missing = [field for field in fields if data.get(field) is None]
        if missing:
            return await self.invalid_request(
                f"Required attributes {', '.join(missing)} were not provided"
            )
        if data["scene_id"] not in self._ledfx.config.scenes:
            return await self.invalid_request(
                f"Scene {data['scene_id']} does not exist"
            )
        return tuple(data[field] for field in fields)

    async def get(self, integration_id) -> web.Response:
        """Get all song triggers"""
        if integration_id is None:
            return await self.invalid_request(
                'Required attribute "integration_id" was not provided'
            )
        integration = self._ledfx.integrations.get(integration_id)
        if (integration is None) or (integration.type != "spotify"):
            return await self.invalid_request(
                f"{integration_id} was not found or was not type spotify"
            )

        response = integration.get_triggers()
        return await self.bare_request_success(response)

    async def put(self, integration_id, request) -> web.Response:
        """Move a Spotify song trigger to another scene"""
        if integration_id is None:
            return await self.invalid_request(
                'Required attribute "integration_id" was not provided'
            )
        integration = self._ledfx.integrations.get(integration_id)
        if (integration is None) or (integration.type != "spotify"):
            return await self.invalid_request(
                f"{integration_id} was not found or was not type spotify"
            )

        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()
        trigger = await self._trigger_fields(data)
        if isinstance(trigger, web.Response):
            return trigger

        scene_id, song_id, song_name, song_position = trigger
        trigger_id = f"{song_id}-{song_position!s}"  # as add_trigger names it
        if not any(trigger_id in t for t in integration.triggers.values()):
            return await self.invalid_request(f"Trigger {trigger_id} does not exist")

        integration.delete_trigger(trigger_id)
        integration.add_trigger(scene_id, song_id, song_name, song_position)
        self._save_triggers(integration)
        return await self.request_success()

    async def post(self, integration_id, request) -> web.Response:
        """Add Spotify song trigger"""
        if integration_id is None:
            return await self.invalid_request(
                'Required attribute "integration_id" was not provided'
            )
        integration = self._ledfx.integrations.get(integration_id)
        if (integration is None) or (integration.type != "spotify"):
            return await self.invalid_request(
                f"{integration_id} was not found or was not type spotify"
            )

        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()
        trigger = await self._trigger_fields(data)
        if isinstance(trigger, web.Response):
            return trigger

        scene_id, song_id, _, song_position = trigger
        trigger_id = f"{song_id}-{song_position!s}"  # as add_trigger names it
        for other, triggers in integration.triggers.items():
            if other != scene_id and trigger_id in triggers:
                return await self.invalid_request(
                    f"Trigger {trigger_id} already belongs to scene {other}; "
                    "use PUT to move it"
                )

        integration.add_trigger(*trigger)
        self._save_triggers(integration)
        return await self.request_success()

    async def delete(self, integration_id, request) -> web.Response:
        """Delete a Spotify song trigger"""
        integration = self._ledfx.integrations.get(integration_id)
        if (integration is None) or (integration.type != "spotify"):
            return await self.invalid_request(
                f"{integration_id} was not found or was not type spotify"
            )

        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()
        trigger_id = data.get("trigger_id")

        if trigger_id is None:
            return await self.invalid_request(
                'Required attribute "trigger_id" was not provided'
            )

        integration.delete_trigger(trigger_id)
        self._save_triggers(integration)
        return await self.request_success()
