import logging
from json import JSONDecodeError
from typing import TYPE_CHECKING

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.api.v1_compat import v1_color
from ledfx.color import validate_gradient

if TYPE_CHECKING:
    from ledfx.core import LedFxCore
    from ledfx.utils import UserDefaultCollection

_LOGGER = logging.getLogger(__name__)


def _deletable(collection: "UserDefaultCollection", key: str) -> bool:
    builtin, user = collection.get_all()
    return key in user and key not in builtin


def deletion_error(ledfx: "LedFxCore", key: str) -> str | None:
    """Why a color or gradient cannot be deleted, or None if it can."""
    collections = (ledfx.colors, ledfx.gradients)
    if any(_deletable(c, key) for c in collections):
        return None
    if any(key in c.get_all()[0] for c in collections):
        return f"Cannot delete built-in color or gradient: {key}"
    return f"Color or gradient {key} not found"


class ColorEndpoint(RestEndpoint):
    OBJECT_BODY_METHODS = ("PUT", "POST")
    ENDPOINT_PATH = "/api/colors"

    async def get(self) -> web.Response:
        """Get LedFx colors and gradients"""
        response = {
            "colors": dict(zip(("builtin", "user"), self._ledfx.colors.get_all())),
            "gradients": dict(
                zip(("builtin", "user"), self._ledfx.gradients.get_all())
            ),
        }
        return await self.bare_request_success(response)

    async def delete(self, request: web.Request) -> web.Response:
        """Deletes a user defined color or gradient Request body is a string of the
        color key to delete eg. [\"my_red_color\"]
        """

        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()
        if not isinstance(data, list) or not all(isinstance(k, str) for k in data):
            return await self.invalid_request(
                "Request body must be a JSON list of color names"
            )

        for key in data:
            if reason := deletion_error(self._ledfx, key):
                return await self.invalid_request(reason)
        for key in data:
            for collection in (self._ledfx.colors, self._ledfx.gradients):
                if _deletable(collection, key):
                    del collection[key]

        keys_str = ", ".join(data)
        return await self.request_success("success", f"Deleted {keys_str}")

    async def post(self, request: web.Request) -> web.Response:
        """Creates or updates existing colors or gradients."""
        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()
        if data is None:
            return await self.invalid_request("Required attribute was not provided")

        staged = []
        for key, val in data.items():
            try:
                # v1-compat: a colour may be an [r, g, b] list.
                # The collection normalises it once.
                v1_color(val)
                collection, noun = self._ledfx.colors, "color"
            except ValueError:
                try:
                    validate_gradient(val)
                except ValueError:
                    return await self.invalid_request(
                        f"{key} is not a valid color or gradient"
                    )
                collection, noun = self._ledfx.gradients, "gradient"
            if key in collection.get_all()[0]:
                return await self.invalid_request(
                    f"Cannot overwrite built-in {noun}: {key}"
                )
            staged.append((collection, key, val))
        for collection, key, val in staged:
            collection[key] = val

        keys_str = ", ".join(data)
        return await self.request_success("success", f"Saved {keys_str}")
