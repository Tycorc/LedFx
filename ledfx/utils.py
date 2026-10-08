import asyncio
import concurrent.futures
import csv
import datetime
import importlib
import io
import ipaddress
import logging
import math
import os
import pkgutil
import re
import socket
import sys
import time
import timeit
import urllib.parse
import urllib.request
from abc import ABC
from collections import deque
from collections.abc import Callable, MutableMapping
from contextlib import suppress
from datetime import UTC
from functools import lru_cache
from importlib import metadata
from itertools import chain
from logging.handlers import QueueHandler
from platform import (
    processor,
    python_build,
    python_implementation,
    python_version,
    release,
    system,
)
from typing import TYPE_CHECKING, ClassVar

import netifaces
import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image, ImageFont

from ledfx.color import (
    LEDFX_COLORS,
    LEDFX_GRADIENTS,
    coerce_color,
    parse_color,
    parse_gradient,
    validate_gradient,
)
from ledfx.consts import LEDFX_ASSETS_PATH, PROJECT_VERSION
from ledfx.events import ColorsUpdatedEvent
from ledfx.libraries.cache import ImageCache
from ledfx.utilities.security_utils import (
    DOWNLOAD_TIMEOUT,
    MAX_IMAGE_SIZE_BYTES,
    build_browser_request,
    is_allowed_image_extension,
    resolve_safe_path_in_directory,
    safe_urlopen,
    validate_image_mime_type,
    validate_local_path,
    validate_pil_image,
    validate_url_safety,
)

if TYPE_CHECKING:
    from ledfx.configuration.lenient import Quarantine
    from ledfx.configuration.models import DeviceEntry, EffectEntry, IntegrationEntry
    from ledfx.configuration.plugin import PluginConfig
    from ledfx.core import LedFxCore


_LOGGER = logging.getLogger(__name__)


clock_source = "perf_counter"


def calc_available_fps():
    """Calculates the available frames per second (FPS) based on the sleep resolution
    of the clock source.
    """
    sleep_res = time.get_clock_info(clock_source).resolution

    if sleep_res < 0.001:
        mult = int(0.001 / sleep_res)
    else:
        mult = 1

    max_fps_target = 126
    min_fps_target = 10

    max_fps_ticks = np.ceil((1 / max_fps_target) / (sleep_res * mult)).astype(int)
    min_fps_ticks = np.ceil((1 / min_fps_target) / (sleep_res * mult)).astype(int)
    tick_range = reversed(range(max_fps_ticks, min_fps_ticks))
    return {int(1 / (sleep_res * mult * i)): i * mult for i in tick_range}


AVAILABLE_FPS = calc_available_fps()


@lru_cache(maxsize=32)
def fps_to_sleep_interval(fps):
    """Converts frames per second (fps) to a sleep interval in seconds."""
    sleep_res = time.get_clock_info(clock_source).resolution
    sleep_ticks = next(
        (t for f, t in AVAILABLE_FPS.items() if f >= fps),
        list(AVAILABLE_FPS.values())[-1],
    )
    return max(0.001, sleep_res * (sleep_ticks - 1))


def async_fire_and_forget(coro, loop, exc_handler=None):
    """Run some code in the core event loop without a result"""

    if not asyncio.coroutines.iscoroutine(coro):
        raise TypeError(f"A coroutine object is required: {coro}")

    def callback():
        """Handle the firing of a coroutine."""
        task = asyncio.create_task(coro)
        if exc_handler is not None:
            task.add_done_callback(exc_handler)

    loop.call_soon_threadsafe(callback)


def get_local_ip():
    """Uses a socket to find the first non-loopback ip address"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            return "127.0.0.1"


def check_if_ip_is_broadcast(thisip):
    """Check if provided IP is the broadcast address of one of the network interfaces"""
    try:
        for iface in netifaces.interfaces():
            iface = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in iface:
                for ip in iface[netifaces.AF_INET]:
                    if "broadcast" in ip and ip["broadcast"] == thisip:
                        return True

        return False

    except OSError as e:
        _LOGGER.warning("Unable to check if ip is a broadcast address: %s", e)
        return False


def async_fire_and_return(coro, callback, timeout=10):
    """Run some async code in the core event loop with a callback to handle the
    result
    """
    if not asyncio.coroutines.iscoroutine(coro):
        raise TypeError(f"A coroutine object is required: {coro}")

    def _callback(future):
        exc = future.exception()
        if exc:
            if isinstance(exc, TimeoutError):
                _LOGGER.warning("Coroutine %s timed out.", future)
            else:
                _LOGGER.error("%s", exc)
        else:
            callback(future.result())

    future = asyncio.create_task(asyncio.wait_for(coro, timeout=timeout))
    future.add_done_callback(_callback)


def async_callback(loop, callback, *args):
    """Run a callback in the event loop with access to the result"""

    future = concurrent.futures.Future()

    def run_callback():
        try:
            future.set_result(callback(*args))
        # pylint: disable=broad-except
        except Exception as e:
            if future.set_running_or_notify_cancel():
                future.set_exception(e)
            else:
                _LOGGER.warning("Exception on lost future: ", exc_info=True)

    loop.call_soon(run_callback)
    return future


class WLED:
    """A collection of WLED helper functions"""

    SYNC_MODES: ClassVar[dict[str, int]] = {"DDP": 4048, "E131": 5568, "ARTNET": 6454}

    def __init__(self, ip_address):
        self.ip_address = ip_address
        self.reboot_flag = False

    async def get_sync_settings(self):
        self.sync_settings = await WLED._get_sync_settings(self.ip_address)

    @staticmethod
    async def _wled_request(method, ip_address, endpoint, timeout=0.5, **kwargs):
        url = f"http://{ip_address}/{endpoint}"

        try:
            response = method(url, timeout=timeout, **kwargs)

        except requests.exceptions.RequestException:
            msg = f"WLED {ip_address}: Failed to connect"
            raise ValueError(msg)

        if not response.ok:
            msg = f"WLED {ip_address}: API Error - {response.status_code}"
            raise ValueError(msg)

        return response

    @staticmethod
    async def _get_sync_settings(ip_address):
        response = await WLED._wled_request(requests.get, ip_address, "json/cfg")
        return response.json()

    async def flush_sync_settings(self):
        """JSON API call to flush wled sync settings to the device. Will reboot if
        required.
        """
        await WLED._wled_request(
            requests.post,
            self.ip_address,
            "json/cfg",
            data=self.sync_settings,
        )
        self.reboot_flag = False

    async def get_config(self):
        """Return WLED-compatible config; brand must exist but need not equal WLED."""
        _LOGGER.info("WLED %s: Attempting to contact device...", self.ip_address)
        response = await WLED._wled_request(requests.get, self.ip_address, "json/info")

        wled_config = response.json()

        if "brand" not in wled_config:
            raise ValueError(f"WLED {self.ip_address}: Device is not WLED compatible")

        _LOGGER.info(
            "WLED compatible device brand:%s at %s configuration received",
            wled_config["brand"],
            self.ip_address,
        )

        return wled_config

    async def get_nodes(self):
        """Uses a JSON API call to pull WLED nodes from the known WLED instance
        Returns: nodes: dict, with all wled nodes info
        """
        _LOGGER.info("WLED %s: Attempting to get nodes...", self.ip_address)
        response = await WLED._wled_request(requests.get, self.ip_address, "json/nodes")

        wled_nodes = response.json()

        _LOGGER.debug("WLED %s: Received config %s", self.ip_address, wled_nodes)

        return wled_nodes

    async def get_state(self):
        """Uses a JSON API call to determine the full WLED device state"""
        response = await WLED._wled_request(requests.get, self.ip_address, "json/state")

        return response.json()

    async def get_power_state(self):
        """Uses a JSON API call to determine the WLED device power state (on/off)"""
        return (await self.get_state())["on"]

    async def get_segments(self):
        """Uses a JSON API call to determine the WLED segment setup"""
        res = await self.get_state()
        return res["seg"]

    async def set_power_state(self, state):
        """Uses a JSON API post call to set the power of a WLED compatible device
        on/off
        """
        power = {"on": bool(state)}
        await WLED._wled_request(
            requests.post, self.ip_address, "/json/state", data=power
        )

        _LOGGER.info("WLED %s: Turned %s.", self.ip_address, "on" if state else "off")

    async def set_brightness(self, brightness):
        """Uses a JSON API post call to adjust a WLED compatible device's brightness"""
        brightness = max(0, max(int(brightness), 255))
        bri = {"bri": brightness}

        await WLED._wled_request(
            requests.post, self.ip_address, "/json/state", data=bri
        )

        _LOGGER.info("WLED %s: Set brightness to %s.", self.ip_address, brightness)

    def enable_realtime_gamma(self):
        """Updates internal sync settings to enable realtime gamma"""

        self.sync_settings["if"]["live"]["no-gc"] = False

        _LOGGER.info("WLED %s: Enabled realtime gamma correction", self.ip_address)

    def force_max_brightness(self):
        """Updates internal sync settings to enable \"Force Max Brightness\""""
        self.sync_settings["if"]["live"]["maxbri"] = True

        _LOGGER.info("WLED %s: Enabled force max brightness", self.ip_address)

    def multirgb_dmx_mode(self):
        """Updates DMX mode to \"Multi RGB\""""
        self.sync_settings["if"]["live"]["dmx"]["mode"] = 4

        _LOGGER.info("WLED %s: Enabled Multi RGB", self.ip_address)

    def first_universe(self):
        """Updates first universe to \"1\""""
        self.sync_settings["if"]["live"]["dmx"]["uni"] = 1

        _LOGGER.info("WLED %s: Set first Universe = 1", self.ip_address)

    def first_dmx_address(self):
        """Updates first dmx address to \"1\""""
        self.sync_settings["if"]["live"]["dmx"]["addr"] = 1

        _LOGGER.info("WLED %s: Set first DMX address = 1", self.ip_address)

    def get_inactivity_timeout(self):
        """Get inactivity timeout from internal sync settings"""
        return self.sync_settings["if"]["live"]["timeout"]

    def set_inactivity_timeout(self, timeout=2.5):
        """Updates internal sync settings to set timeout for wled effect virtual
        after ledfx streaming finishes
        """
        tout = self.sync_settings["if"]["live"]["timeout"]
        if tout * 10 == timeout:
            return

        self.sync_settings["if"]["live"]["timeout"] = timeout * 10

        _LOGGER.info("Set WLED device at %s timeout to %ss", self.ip_address, timeout)

    def set_sync_mode(self, mode):
        """Updates internal sync settings to set sync mode"""
        mode = mode.upper()

        assert mode in WLED.SYNC_MODES

        if mode == "udp":
            if self.sync_settings["if"]["live"]["en"]:
                return
            else:
                self.sync_settings["if"]["live"]["en"] = True

        else:
            if mode == self.get_sync_mode():
                return
            port = WLED.SYNC_MODES[mode]
            self.sync_settings["if"]["live"]["port"] = port

        self.reboot_flag = True

        _LOGGER.info("Set WLED device at %s to sync mode '%s'", self.ip_address, mode)

    def get_sync_mode(self):
        """Reverse dict lookup of current sync mode by port"""
        sync_port = self.sync_settings["if"]["live"]["port"]

        return next(key for key, value in WLED.SYNC_MODES.items() if value == sync_port)

    async def reboot(self):
        """JSON API Post to reboot wled device"""
        reboot = {"rb": True}
        await WLED._wled_request(
            requests.post,
            self.ip_address,
            "/json/state",
            timeout=3,
            data=reboot,
        )


def empty_queue(queue: asyncio.Queue):
    """Empty an asyncio queue"""
    for _ in range(queue.qsize()):
        queue.get_nowait()
        queue.task_done()


async def resolve_destination(loop, executor, destination, port=7777, timeout=3):
    """Uses asyncio's non blocking DNS funcs to attempt domain lookup"""
    try:
        ipaddress.ip_address(destination)
        return destination

    except ValueError:
        cleaned_dest = destination.rstrip(".")
        try:
            dest = await loop.run_in_executor(
                executor, socket.gethostbyname, cleaned_dest
            )
            _LOGGER.debug("Resolved %s to %s", cleaned_dest, dest)
            return dest
        except socket.gaierror:
            raise ValueError(f"Failed to resolve destination {cleaned_dest}")


def read_ledfx_dotenv():
    """Load packaged release metadata from ledfx.env; absent in normal development."""
    extDataDir = os.path.dirname(os.path.realpath(__file__))

    if currently_frozen():
        extDataDir = sys._MEIPASS
        path_to_load = os.path.join(extDataDir, "ledfx.env")
    else:
        parent_dir = os.path.dirname(extDataDir)
        path_to_load = os.path.join(parent_dir, "ledfx.env")
    if os.path.exists(path_to_load):
        load_dotenv(dotenv_path=path_to_load)
        _LOGGER.debug("Loaded dotenv from %s", path_to_load)


def currently_frozen():
    """Checks to see if running in a frozen environment such as pyinstaller created
    binaries Args: Nil
    """
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_icon_path(icon_filename) -> str:
    """Returns fully qualified path for the tray icon Assumes that the file is within
    ledfx_assets folder
    """

    icon_location = os.path.normpath(os.path.join(LEDFX_ASSETS_PATH, icon_filename))

    if not os.path.isfile(icon_location):
        _LOGGER.error("No icon found at %s", icon_location)

    return icon_location


def generate_id(name):
    """Converts a name to an ID."""
    part1 = re.sub("[^a-zA-Z0-9]", " ", name).lower()
    result = re.sub(" +", " ", part1).strip().replace(" ", "-")
    if result == "":
        result = "default"
    return result


def generate_title(id):
    """Converts an id to a more human readable title."""
    return re.sub("[^a-zA-Z0-9]", " ", id).title()


def is_gap_device(device) -> bool:
    """Return true only for dummy devices whose IDs start with gap-."""
    if device is None:
        return False
    return device.id.startswith("gap-") and device.type == "dummy"


class UserDefaultCollection(MutableMapping):
    """A collection of default values and user defined values."""

    def __init__(
        self,
        ledfx,
        collection_name: str,
        defaults: dict,
        user: dict[str, str],
        validator: callable = lambda x: x,
        parser: callable = lambda x: x,
    ):
        """collection_name: friendly description of the collection defaults: dict of
        default values user: the live config dict of user values (e.g.
        config.user_colors)
        """
        self._ledfx = ledfx
        self._collection_name = collection_name
        self._default_vals = defaults
        self._user_vals = user
        self._validator = validator
        self._parser = parser

    def get_all(self, merged=False):
        if merged:
            return self._default_vals | self._user_vals
        else:
            return self._default_vals, self._user_vals

    def __getitem__(self, key):
        val = self._default_vals.get(key) or self._user_vals.get(key)
        if val:
            return self._parser(val)
        raise KeyError(f"Unknown {self._collection_name}: {key}")

    def __delitem__(self, key):
        noun = self._collection_name.lower().rstrip("s")
        if key in self._default_vals:
            raise ValueError(f"Cannot delete built-in {noun}: {key}")
        del self._user_vals[key]
        _LOGGER.info("Deleted %s: %s", noun, key)
        self._ledfx.config_store.request_save()
        if self._collection_name in ("Colors", "Gradients"):
            self._ledfx.events.fire_event(ColorsUpdatedEvent())

    def __setitem__(self, key, value):
        noun = self._collection_name.lower().rstrip("s")
        if key in self._default_vals:
            raise ValueError(f"Cannot overwrite built-in {noun}: {key}")
        self._user_vals[key] = self._validator(value)
        _LOGGER.info("Saved %s: %s", noun, key)
        self._ledfx.config_store.request_save()
        if self._collection_name in ("Colors", "Gradients"):
            self._ledfx.events.fire_event(ColorsUpdatedEvent())

    def __iter__(self):
        return chain(self._default_vals, self._user_vals)

    def __len__(self):
        return len(self._default_vals) + len(self._user_vals)


def build_user_collections(
    ledfx: "LedFxCore",
) -> tuple[UserDefaultCollection, UserDefaultCollection]:
    """The colours and gradients collections over the user_colors and
    user_gradients config sections. The one place that picks their validators:
    colours stay lenient (v1 clients send list colours)."""
    colors = UserDefaultCollection(
        ledfx,
        "Colors",
        LEDFX_COLORS,
        ledfx.config.user_colors,
        coerce_color,
        parse_color,
    )
    gradients = UserDefaultCollection(
        ledfx,
        "Gradients",
        LEDFX_GRADIENTS,
        ledfx.config.user_gradients,
        validate_gradient,
        parse_gradient,
    )
    return colors, gradients


class RollingQueueHandler(QueueHandler):
    """A custom logging handler that extends the QueueHandler class."""

    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except asyncio.QueueFull:
            self.queue.get_nowait()
            self.enqueue(record)


class BaseRegistry(ABC):
    """Register plugins by module name; use no_registration for abstract effect
    bases.
    """

    @classmethod
    def config_model(cls) -> "type[PluginConfig]":
        """The pydantic model for this class's config (its declared ``Config``)."""
        model = getattr(cls, "Config", None)
        if model is None:
            raise TypeError(f"{cls.__name__} declares no Config model")
        return model

    def _set_config_values(self, **changes: object) -> None:
        """Change derived config values (e.g. discovered pixel_count) and persist
        them.
        """
        config = self._config.with_values(**changes)
        if config == self._config:
            return  # e.g. WLED re-reporting the same values on every boot
        self._config = config
        store = getattr(getattr(self, "_ledfx", None), "config_store", None)
        if store is None or not self.id:
            return
        entry = store.device_entry(self.id)
        if entry is not None:
            entry.config = self._config.as_dict()
            store.request_save()

    def __init_subclass__(cls, **kwargs):
        """Automatically register the class"""
        super().__init_subclass__(**kwargs)

        if not hasattr(cls, "_registry"):
            cls._registry = {}

        name = cls.__module__.split(".")[-1]
        cls._registry[name] = cls

    @classmethod
    def no_registration(self, cls):
        """Clear registration entity based on special declarator"""

        name = cls.__module__.split(".")[-1]
        del cls._registry[name]
        return cls

    @classmethod
    def registry(self):
        """Returns all the subclasses in the registry"""

        return self._registry

    @property
    def id(self) -> str:
        """Returns the id for the object"""
        return getattr(self, "_id", None)

    @property
    def type(self) -> str:
        """Returns the type for the object"""
        return getattr(self, "_type", None)


class RegistryLoader:
    """Manages loading of components for a given registry"""

    def __init__(self, ledfx, cls, package):
        self._package = package
        self._cls = cls
        self._objects = {}
        self._object_id = 1

        self._ledfx = ledfx
        self.import_registry(package)

    def import_registry(self, package):
        """Imports all the modules in the package thus hydrating the registry for the
        class
        """

        found = self.discover_modules(package)
        _LOGGER.debug("Importing %s modules from %s", len(found), package)
        for name in found:
            try:
                importlib.import_module(name)
            except ModuleNotFoundError as e:
                _LOGGER.warning("Failed to import %s from %s: %s", name, package, e)
        _LOGGER.debug("Finished importing from %s", package)

    def discover_modules(self, package):
        """Discovers all modules in the package"""
        module = importlib.import_module(package)

        found = []
        for _, name, _ in pkgutil.iter_modules(module.__path__, package + "."):
            found.append(name)

        return found

    def __iter__(self):
        return iter(self._objects)

    def types(self):
        """Returns all the type strings in the registry"""
        return list(self._cls.registry().keys())

    def classes(self):
        """Returns all the classes in the registry"""
        return self._cls.registry()

    def get_class(self, type):
        return self._cls.registry()[type]

    def values(self):
        """Returns all the created objects"""
        return self._objects.values()

    def create(self, type, id=None, *args, **kwargs):
        """Loads and creates an object from the registry by type. If type is missing,
        logs a warning and returns None instead of raising.
        """
        if type not in self._cls.registry():
            _LOGGER.warning(
                "Couldn't find '%s' in the %s registry. Skipping creation.",
                type,
                self._cls.__name__.lower(),
            )
            return None

        id = id or type

        dupe_id = id
        dupe_index = 1
        while id in self._objects:
            id = f"{dupe_id}-{dupe_index}"
            dupe_index = dupe_index + 1

        _cls = self._cls.registry().get(type)
        _config = kwargs.pop("config", None)
        lenient = kwargs.pop("lenient", None)
        lenient_path = kwargs.pop("lenient_path", None)
        lenient_entry = kwargs.pop("lenient_entry", None)
        if _config is not None:
            from ledfx.configuration.plugin import PluginConfig

            raw = (
                _config.as_dict()
                if isinstance(_config, PluginConfig)
                else dict(_config)
            )
            if lenient is None:
                _config = _cls.config_model().model_validate(raw)
            else:
                _config = self.validate_leniently(
                    _cls, type, id, raw, lenient, lenient_path, lenient_entry
                )
                if _config is None:
                    return None
            obj = _cls(config=_config, *args, **kwargs)  # noqa: B026
        else:
            obj = _cls(*args, **kwargs)

        obj._id = id
        obj._type = type

        self._objects[id] = obj
        return obj

    def validate_leniently(
        self,
        _cls: type[BaseRegistry],
        type: str,
        id: str,
        raw: dict[str, object],
        quarantine: "Quarantine",
        path: str | None,
        entry: "DeviceEntry | IntegrationEntry | EffectEntry | None",
    ) -> "PluginConfig | None":
        """Startup load: default and quarantine bad values instead of dropping the
        plugin, and write the repaired config back to its store entry so the next
        boot finds nothing to quarantine.
        """
        from pydantic import ValidationError

        from ledfx.configuration.lenient import lenient_validate

        model = _cls.config_model()
        with suppress(ValidationError):
            return model.model_validate(raw)
        path = path or f"{self._cls.__name__.lower()}s.{id}.config"
        repairs = 0

        def counted(record_path: str, value: object, errors: list[str]) -> None:
            nonlocal repairs
            repairs += 1
            quarantine(record_path, value, errors)

        config = lenient_validate(model, raw, path, counted)
        if config is None:
            _LOGGER.warning("Skipping %s '%s': its config is unusable.", type, id)
        elif repairs and entry is not None:
            if self._ledfx.config_store.quarantine_failed:
                _LOGGER.error(
                    "Not saving the repaired %s '%s' config: its invalid values "
                    "could not be quarantined.",
                    type,
                    id,
                )
            else:
                entry.config = config.as_dict()
                self._ledfx.config_store.request_save()
        return config

    def destroy(self, id):
        if id not in self._objects:
            raise AttributeError(f"Object with id '{id}' does not exist.")
        del self._objects[id]

    def get(self, *args):
        return self._objects.get(*args)


class Plot_range:
    def __init__(self, key, birth, points=1000):
        self.key = key
        self.xs = deque(maxlen=points)
        self.ys = deque(maxlen=points)
        self.birth = birth

    def append(self, y):
        self.xs.append(timeit.default_timer() - self.birth)
        self.ys.append(y)

    def list_x(self):
        return list(self.xs)

    def list_y(self):
        return list(self.ys)


class Tag:
    def __init__(self, x, y, text, color="black"):
        self.x = x
        self.y = y
        self.text = text
        self.color = color


class Graph:
    """Plot named time-series and tags with optional Bokeh browser output."""

    def __init__(
        self,
        title,
        keys,
        points=1000,
        tags=10,
        y_title="plumbus",
        y_axis_max=None,
    ):
        """Creates a graph instance, sets X axis to 0 seconds"""
        self.title = title
        self.y_title = y_title
        self.y_axis_max = y_axis_max
        self.ranges = {}
        self.keys = keys
        self.birth = timeit.default_timer()
        for key in keys:
            self.ranges[key] = Plot_range(key, self.birth, points=points)
        self.tags = deque(maxlen=tags)

    def append_by_key(self, key, value):
        """Appends a value into range ring buffer associated with axis key, timestamp
        is applied in second since graph creation
        """
        self.ranges[key].append(value)

    def append_tag(self, text, y, color="black"):
        """Appends a text tag into tag ring buffer, timestamp is applied in seconds
        since graph creation
        """

        self.tags.append(Tag(timeit.default_timer() - self.birth, y, text, color=color))

    def dump_graph(self, sub_title=None, jitter=False, only_jitter=False):
        """Will spawn an interaction graph session into the browser"""
        try:
            from itertools import cycle

            from bokeh.io import output_file, show
            from bokeh.layouts import column
            from bokeh.models import Label
            from bokeh.palettes import Category10
            from bokeh.plotting import figure

            from ledfx.configuration.paths import get_default_config_directory
        except ImportError:
            _LOGGER.info("Bokeh is not available, dump is disabled")
            return

        if sub_title:
            compound = f"{self.title} : {sub_title}"
        else:
            compound = self.title

        _LOGGER.info("Attempting to dump graph %s", compound)
        TOOLS = "xpan,xwheel_zoom,box_zoom,reset,save,box_select"
        colors = cycle(Category10[10])

        vals_fig = figure(
            title=compound,
            x_axis_label="sec since start",
            y_axis_label=self.y_title,
            tools=TOOLS,
            active_scroll="xwheel_zoom",
            width=1200,
            height=600,
        )

        for a_range in self.ranges.values():
            if len(a_range.list_x()) > 0:
                vals_fig.line(
                    a_range.list_x(),
                    a_range.list_y(),
                    legend_label=a_range.key,
                    line_width=2,
                    color=next(colors),
                )

        for tag in self.tags:
            label = Label(
                x=tag.x,
                y=tag.y,
                text=tag.text,
                text_font_size="12pt",
                text_color=tag.color,
                angle=1.57,
            )
            vals_fig.add_layout(label)

        if self.y_axis_max is not None:
            vals_fig.y_range.end = self.y_axis_max

        vals_fig.legend.click_policy = "hide"

        if jitter or only_jitter:
            jitter_title = f"{compound} jitter"

            jitter_fig = figure(
                title=jitter_title,
                x_axis_label="sec since start",
                x_range=vals_fig.x_range,
                y_axis_label="periodic secs",
                tools=TOOLS,
                active_scroll="xwheel_zoom",
                width=1200,
                height=600,
            )

            for a_range in self.ranges.values():
                x = a_range.list_x()
                if len(x) > 0:
                    jitter = [x[i + 1] - x[i] for i in range(len(x) - 1)]
                    jitter.insert(0, 0.0)
                    jitter_fig.scatter(
                        a_range.list_x(),
                        jitter,
                        legend_label=a_range.key,
                        size=3,
                        color=next(colors),
                    )

            for tag in self.tags:
                label = Label(
                    x=tag.x,
                    y=0.001,
                    text=tag.text,
                    text_font_size="12pt",
                    text_color=tag.color,
                    angle=1.57,
                    text_baseline="middle",
                )

                jitter_fig.add_layout(label)

            jitter_fig.legend.click_policy = "hide"

        if only_jitter:
            p = column(jitter_fig)
        elif jitter:
            p = column(vals_fig, jitter_fig)
        else:
            p = column(vals_fig)

        save_as = os.path.join(
            get_default_config_directory(),
            f"{re.sub('[^A-Za-z0-9]+', '_', compound)}.html",
        )
        output_file(filename=save_as, title=compound)
        show(p)


def wled_support_DDP(build) -> bool:
    return build >= 2110060


def clean_ip(ip_address):
    """Strip common error input from IP copy from chrome that is actually a URL"""

    return ip_address.replace("https://", "").replace("http://", "").replace("/", "")


name_to_icon = {}


def set_name_to_icon(new_dict):
    global name_to_icon
    name_to_icon = new_dict


def get_icon_name(wled_name):
    for name, icon in name_to_icon.items():
        if name.lower() in wled_name.lower():
            return icon
    return "wled"


def extract_positive_integers(s):
    numbers = re.findall(r"\d+", s)

    return list({int(num) for num in numbers if int(num) >= 0})


def extract_uint8_seq(s):
    numbers = re.findall(r"\d+", s)
    return [int(num) for num in numbers if 0 <= int(num) <= 255]


def clip_at_limit(numbers, limit):
    return [num for num in numbers if num < limit]


_image_cache = None
_config_dir = None


def init_image_cache(config_dir: str, max_size_mb: int = 500, max_items: int = 500):
    """Initialize global image cache."""
    global _image_cache, _config_dir

    _config_dir = os.path.abspath(config_dir)
    _image_cache = ImageCache(config_dir, max_size_mb, max_items)
    _LOGGER.info("Image cache initialized: max %sMB, %s items", max_size_mb, max_items)


def get_image_cache():
    """Get the global image cache instance."""
    return _image_cache


def validate_local_image_path(file_path: str) -> tuple[bool, str | None]:
    """Validate that local image file path is within allowed directories (path
    traversal protection).
    """
    if not _config_dir:
        _LOGGER.warning("Config directory not initialized, rejecting local file access")
        return False, None

    return validate_local_path(file_path, [_config_dir, LEDFX_ASSETS_PATH])


def _validate_and_open_image(
    resolved_path: str, original_path: str, check_size: bool = True
) -> Image.Image | None:
    """Validate and open an image file with security checks."""
    if not os.path.exists(resolved_path):
        _LOGGER.warning("File not found: %s", original_path)
        return None

    if not os.path.isfile(resolved_path):
        _LOGGER.warning("Path is not a file: %s", original_path)
        return None

    if not is_allowed_image_extension(resolved_path):
        _LOGGER.warning("Invalid image extension: %s", original_path)
        return None

    if check_size:
        file_size = os.path.getsize(resolved_path)
        if file_size > MAX_IMAGE_SIZE_BYTES:
            _LOGGER.warning(
                "File too large: %s bytes (max %s)",
                file_size,
                MAX_IMAGE_SIZE_BYTES,
            )
            return None

    if not validate_image_mime_type(resolved_path):
        _LOGGER.warning("Invalid image MIME type: %s", original_path)
        return None

    try:
        gif = Image.open(resolved_path)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to open image: %s : %s", original_path, e)
        return None

    if not validate_pil_image(gif):
        _LOGGER.warning("Invalid PIL format or dimensions: %s", original_path)
        return None

    if not hasattr(gif, "n_frames"):
        gif.n_frames = 1

    return gif


def open_gif(gif_path, force_refresh=False, config_dir=None):
    """Open a GIF image from a URL or local file path with file type validation."""
    gif_path = gif_path.strip()

    try:
        if gif_path.startswith("./ledfx_assets/gifs/"):
            actual_path = gif_path[20:]  # Remove "./ledfx_assets/gifs/"
            gif_path = f"builtin://{actual_path}"
        elif gif_path.startswith("ledfx_assets/gifs/"):
            actual_path = gif_path[18:]  # Remove "ledfx_assets/gifs/"
            gif_path = f"builtin://{actual_path}"

        if gif_path.startswith("builtin://"):
            actual_path = gif_path[10:]  # Remove "builtin://" prefix
            gifs_root = os.path.join(LEDFX_ASSETS_PATH, "gifs")

            is_valid, resolved_path, error = resolve_safe_path_in_directory(
                gifs_root,
                actual_path,
                create_dirs=False,
                directory_name="built-in assets",
            )
            if not is_valid:
                _LOGGER.warning("Built-in asset path validation failed: %s", error)
                return None

            return _validate_and_open_image(resolved_path, gif_path, check_size=False)

        if gif_path.startswith(("http://", "https://")):
            if _image_cache and not force_refresh:
                cached_path = _image_cache.get(gif_path)
                if cached_path:
                    try:
                        gif = Image.open(cached_path)
                        if validate_pil_image(gif):
                            if not hasattr(gif, "n_frames"):
                                gif.n_frames = 1
                            return gif
                        else:
                            _LOGGER.warning(
                                "Cached GIF failed validation, re-downloading: %s",
                                gif_path,
                            )
                            _image_cache.delete(gif_path)
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "Error reading cached GIF, re-downloading: %s : %s",
                            gif_path,
                            e,
                        )
                        _image_cache.delete(gif_path)

            if not is_allowed_image_extension(gif_path):
                _LOGGER.warning("URL has invalid image extension: %s", gif_path)
                return None

            is_safe, error_msg = validate_url_safety(gif_path)
            if not is_safe:
                _LOGGER.warning(
                    "URL blocked for security: %s - %s", gif_path, error_msg
                )
                return None

            req = build_browser_request(gif_path)
            with safe_urlopen(req, timeout=DOWNLOAD_TIMEOUT) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_IMAGE_SIZE_BYTES:
                    _LOGGER.warning(
                        "Image too large: %s bytes (max %s)",
                        content_length,
                        MAX_IMAGE_SIZE_BYTES,
                    )
                    return None

                data = response.read(MAX_IMAGE_SIZE_BYTES + 1)
                if len(data) > MAX_IMAGE_SIZE_BYTES:
                    _LOGGER.warning("Image exceeded size limit during download")
                    return None

                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                content_type = response.headers.get("Content-Type", "image/jpeg")
                content_type = content_type.split(";")[0].strip().lower()

                gif = Image.open(io.BytesIO(data))

                if not validate_pil_image(gif):
                    _LOGGER.warning("Invalid PIL format or dimensions: %s", gif_path)
                    return None

                if not hasattr(gif, "n_frames"):
                    gif.n_frames = 1

                if _image_cache:
                    _image_cache.put(gif_path, data, content_type, etag, last_modified)

                return gif
        else:
            parsed = urllib.parse.urlparse(gif_path)
            if parsed.scheme and len(parsed.scheme) > 1:
                _LOGGER.warning(
                    "Invalid URL scheme '%s' for local file: %s",
                    parsed.scheme,
                    gif_path,
                )
                return None

            if config_dir and not os.path.isabs(gif_path):
                assets_root = os.path.join(config_dir, "assets")

                is_valid, resolved_path, error = resolve_safe_path_in_directory(
                    assets_root,
                    gif_path,
                    create_dirs=False,
                    directory_name="user assets",
                )
                if not is_valid:
                    _LOGGER.warning("User asset path validation failed: %s", error)
                    return None

                gif = _validate_and_open_image(resolved_path, gif_path, check_size=True)
                return gif if gif else None
            else:
                is_valid, validated_path = validate_local_image_path(gif_path)
                if not is_valid:
                    _LOGGER.warning(
                        "Path traversal blocked or path outside config directory: %s",
                        gif_path,
                    )
                    return None

                gif = _validate_and_open_image(
                    validated_path, gif_path, check_size=True
                )
                return gif if gif else None

    except urllib.error.HTTPError as e:
        _LOGGER.warning("HTTP error fetching %s: %s %s", gif_path, e.code, e.reason)
        return None
    except urllib.error.URLError as e:
        _LOGGER.warning("URL error fetching %s: %s", gif_path, e.reason)
        return None
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to open gif: %s : %s", gif_path, e)
        return None


def open_image(image_path, force_refresh=False, config_dir=None):
    """Open an image from a URL or local file path with file type validation."""
    image_path = image_path.strip()

    try:
        if image_path.startswith("builtin://"):
            actual_path = image_path[10:]  # Remove "builtin://" prefix
            images_root = os.path.join(LEDFX_ASSETS_PATH, "test_images")

            is_valid, resolved_path, error = resolve_safe_path_in_directory(
                images_root,
                actual_path,
                create_dirs=False,
                directory_name="built-in images",
            )
            if not is_valid:
                _LOGGER.warning("Built-in image path validation failed: %s", error)
                return None

            return _validate_and_open_image(resolved_path, image_path, check_size=False)

        if image_path.startswith(("http://", "https://")):
            if _image_cache and not force_refresh:
                cached_path = _image_cache.get(image_path)
                if cached_path:
                    try:
                        image = Image.open(cached_path)
                        if validate_pil_image(image):
                            return image
                        else:
                            _LOGGER.warning(
                                "Cached image failed validation, re-downloading: %s",
                                image_path,
                            )
                            _image_cache.delete(image_path)
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "Error reading cached image, re-downloading: %s : %s",
                            image_path,
                            e,
                        )
                        _image_cache.delete(image_path)

            if not is_allowed_image_extension(image_path):
                _LOGGER.warning("URL has invalid image extension: %s", image_path)
                return None

            is_safe, error_msg = validate_url_safety(image_path)
            if not is_safe:
                _LOGGER.warning(
                    "URL blocked for security: %s - %s", image_path, error_msg
                )
                return None

            req = build_browser_request(image_path)
            with safe_urlopen(req, timeout=DOWNLOAD_TIMEOUT) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_IMAGE_SIZE_BYTES:
                    _LOGGER.warning(
                        "Image too large: %s bytes (max %s)",
                        content_length,
                        MAX_IMAGE_SIZE_BYTES,
                    )
                    return None

                data = response.read(MAX_IMAGE_SIZE_BYTES + 1)
                if len(data) > MAX_IMAGE_SIZE_BYTES:
                    _LOGGER.warning("Image exceeded size limit during download")
                    return None

                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                content_type = response.headers.get("Content-Type", "image/jpeg")
                content_type = content_type.split(";")[0].strip().lower()

                image = Image.open(io.BytesIO(data))

                if not validate_pil_image(image):
                    _LOGGER.warning("Invalid PIL format or dimensions: %s", image_path)
                    return None

                if _image_cache:
                    _image_cache.put(
                        image_path, data, content_type, etag, last_modified
                    )

                return image
        else:
            parsed = urllib.parse.urlparse(image_path)
            if parsed.scheme and len(parsed.scheme) > 1:
                _LOGGER.warning(
                    "Invalid URL scheme '%s' for local file: %s",
                    parsed.scheme,
                    image_path,
                )
                return None

            if config_dir and not os.path.isabs(image_path):
                assets_root = os.path.join(config_dir, "assets")

                is_valid, resolved_path, error = resolve_safe_path_in_directory(
                    assets_root,
                    image_path,
                    create_dirs=False,
                    directory_name="user assets",
                )
                if not is_valid:
                    _LOGGER.warning("User asset path validation failed: %s", error)
                    return None

                image = _validate_and_open_image(
                    resolved_path, image_path, check_size=True
                )
                return image if image else None
            else:
                is_valid, validated_path = validate_local_image_path(image_path)
                if not is_valid:
                    _LOGGER.warning(
                        "Path traversal blocked or path outside config directory: %s",
                        image_path,
                    )
                    return None

                image = _validate_and_open_image(
                    validated_path, image_path, check_size=True
                )
                return image if image else None

    except urllib.error.HTTPError as e:
        _LOGGER.warning("HTTP error fetching %s: %s %s", image_path, e.code, e.reason)
        return None
    except urllib.error.URLError as e:
        _LOGGER.warning("URL error fetching %s: %s", image_path, e.reason)
        return None
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to open image: %s : %s", image_path, e)
        return None


def get_mono_font(size):
    """Get a monospace font from a list of fonts common across platforms"""

    font_names = [
        "Courier New",
        "cour.ttf",
        "DejaVu Sans Mono",
        "DejaVuSansMono.ttf",
        "DejaVuSansMono-Regular.ttf",
        "Liberation Mono",
        "LiberationMono-Regular.ttf",
        "Consolas",
        "consola.ttf",
        "monospace",
    ]
    return get_font(font_names, size)


def get_font(font_list, size):
    """Get the first font from a list of fonts that is available on the system"""

    for font_name in font_list:
        try:
            font = ImageFont.truetype(font_name, size)
            _LOGGER.info("Found font: %s", font_name)
            return font
        except OSError:
            continue
    raise RuntimeError("None of the fonts are available on the system.")


def generate_default_config(ledfx_effects, effect_id):
    """Generate config out of the schema for an effect to use as a defualt"""
    config = ledfx_effects.get_class(effect_id).get_combined_default_schema()
    gradient = config.get("gradient", None)
    gradient_str = LEDFX_GRADIENTS.get(gradient, None)
    if gradient_str:
        config["gradient"] = gradient_str
        config["gradient_name"] = gradient
    return config


def inject_missing_default_keys(presets, defaults):
    """Inject missing keys from defaults into presets This happens when static or
    user presets are defined and there are new keys added to the effect config
    schema later Args: presets (dict): The current presets.
    """
    for preset in presets.values():
        default_preset = defaults["reset"]["config"]
        for key, value in default_preset.items():
            if key not in preset["config"]:
                preset["config"][key] = value
    return presets


def generate_defaults(ledfx_presets, ledfx_effects, effect_id):
    """Merge current effect defaults into presets when used, after effects are
    registered.
    """
    if effect_id in ledfx_presets:
        presets = ledfx_presets[effect_id]
    else:
        presets = {}

    default = {
        "reset": {
            "config": generate_default_config(ledfx_effects, effect_id),
            "name": "reset",
        }
    }

    presets = inject_missing_default_keys(presets, default)

    default.update(presets)
    return default


def log_packages():
    _LOGGER.debug("%s : %s : %s", system(), release(), processor())
    _LOGGER.debug(
        "%s : %s : %s",
        python_version(),
        python_build(),
        python_implementation(),
    )
    _LOGGER.debug("Packages")
    dists = list(metadata.distributions())
    dists.sort(key=lambda x: x.metadata["name"])
    for dist in dists:
        _LOGGER.debug("%s : %s", dist.metadata["name"], dist.version)


def is_package_installed(package_name: str, import_name: str | None = None) -> bool:
    """Check if a package is available in the environment."""
    import_name = import_name or package_name

    spec = importlib.util.find_spec(import_name)
    if spec is None:
        _LOGGER.debug(
            "Optional dependency '%s' not found (import name: '%s').",
            package_name,
            import_name,
        )
        return False

    try:
        version = metadata.version(package_name)
    except metadata.PackageNotFoundError:
        version = "unknown"

    path = spec.origin or "unknown"  # noqa: F841

    _LOGGER.debug(
        "Optional dependency '%s' is installed (version: %s)",
        package_name,
        version,
    )
    return True


def check_optional_dependencies():
    """Check for optional dependencies and log their availability, versions, and
    paths.
    """
    OPTIONAL_DEPENDENCIES = {
        "psutil": "psutil",
        "python-mbedtls": "mbedtls",
    }
    for package_name, import_name in OPTIONAL_DEPENDENCIES.items():
        is_package_installed(package_name, import_name)


class PerformanceAnalysis:
    """A class for comparing the performance of two functions."""

    _write_buffer: ClassVar[list[list]] = []
    _write_buffer_limit = 100

    @staticmethod
    def compare_functions(
        original_function: Callable,
        optimized_function: Callable,
        num_runs: int = 1,
    ):
        """Compare zero-argument callables over num_runs; wrap parameterized calls in
        lambdas.
        """
        original_time = PerformanceAnalysis._timer_wrapper(original_function, num_runs)
        optimized_time = PerformanceAnalysis._timer_wrapper(
            optimized_function, num_runs
        )

        if original_time < optimized_time:
            faster_method = "Original"
            percent_faster = ((optimized_time - original_time) / original_time) * 100
        else:
            faster_method = "Optimized"
            percent_faster = ((original_time - optimized_time) / optimized_time) * 100

        PerformanceAnalysis._write_to_csv(
            num_runs,
            faster_method,
            original_time,
            optimized_time,
            percent_faster,
        )

    @staticmethod
    def _timer_wrapper(func: Callable, num_runs: int) -> float:
        """Time a function over a number of runs."""
        start_time = time.perf_counter()
        for _ in range(num_runs):
            func()
        end_time = time.perf_counter()

        return (end_time - start_time) / num_runs

    @staticmethod
    def _write_to_csv(
        num_runs: int,
        faster_method: str,
        original_time: float,
        optimized_time: float,
        percent_faster: float,
    ):
        """Write the function comparison results to a CSV file - buffer 100 rows
        before writing to file to minimize disk writes and performance impact.
        """
        timestamp = (
            datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")
        )
        PerformanceAnalysis._write_buffer.append(
            [
                timestamp,
                num_runs,
                faster_method,
                original_time,
                optimized_time,
                f"{percent_faster}%",
            ]
        )

        if (
            len(PerformanceAnalysis._write_buffer)
            >= PerformanceAnalysis._write_buffer_limit
        ):
            with open("performance_analysis.csv", mode="a", newline="") as file:
                writer = csv.writer(file)
                writer.writerows(PerformanceAnalysis._write_buffer)
                PerformanceAnalysis._write_buffer.clear()


class UpdateChecker:
    _update_url = "https://api.github.com/repos/LedFx/LedFx/releases/latest"

    _latest_version = None
    _release_age = None
    _release_url = None
    _update_check_succeeded = None

    @staticmethod
    def get_release_information():
        try:
            response = requests.get(UpdateChecker._update_url, timeout=0.5)
            response.raise_for_status()
            data = response.json()
            UpdateChecker._latest_version = data["tag_name"].replace("v", "")
            UpdateChecker._release_age = (
                datetime.datetime.now(UTC)
                - datetime.datetime.strptime(
                    data["published_at"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=UTC)
            ).days
            UpdateChecker._release_url = data["html_url"]
            UpdateChecker._update_check_succeeded = True
        except requests.RequestException as e:
            _LOGGER.info("Failed to check for updates: %s", e)
            UpdateChecker._update_check_succeeded = False
            return False

        return True

    @staticmethod
    def _get_attribute_if_update_succeeded(attribute):
        if not UpdateChecker._update_check_succeeded:
            return None
        return attribute

    @staticmethod
    def get_latest_version():
        return UpdateChecker._get_attribute_if_update_succeeded(
            UpdateChecker._latest_version
        )

    @staticmethod
    def get_release_age():
        return UpdateChecker._get_attribute_if_update_succeeded(
            UpdateChecker._release_age
        )

    @staticmethod
    def get_release_url():
        return UpdateChecker._get_attribute_if_update_succeeded(
            UpdateChecker._release_url
        )

    @staticmethod
    def update_available():
        return UpdateChecker._get_attribute_if_update_succeeded(
            PROJECT_VERSION != UpdateChecker.get_latest_version()
        )


log_256 = np.log(256)


def pixels_boost(pixels, compression_factor, max_floor):
    floor = max_floor * compression_factor

    factor = 255 - floor
    blend_factor = 1 - compression_factor

    log_compressed = floor + (np.log1p(pixels) / log_256) * factor

    boosted = np.where(
        pixels > 1,
        blend_factor * pixels + compression_factor * log_compressed,
        pixels,
    )

    return boosted


def dump_pixels(pixels, shape):
    """Dump a RGB pixels np array into a PIL image and launch a window to display it.
    This is for adhoc debug only
    """

    reshaped_pixels = pixels.reshape((shape[0], shape[1], 3))
    image = Image.fromarray(reshaped_pixels.astype(np.uint8), "RGB")

    image.show()


def resize_pixels(pixels, old_shape, new_shape):
    """Resizes a 1D pixel array that represents a for 1D or 2D image by interpolating
    it in 2D space using PIL.
    """
    pixel_matrix = pixels.reshape((old_shape[0], old_shape[1], 3)).astype(np.uint8)

    image = Image.fromarray(pixel_matrix)

    resized_image = image.resize((new_shape[1], new_shape[0]), Image.BILINEAR)

    resized_pixel_matrix = np.array(resized_image)

    return resized_pixel_matrix.reshape(-1, 3)


def shape_to_fit_len(max_len, shape, pixels_len):
    """Fit visualization to max_len pixels with each dimension at most 64."""

    if shape[0] > 1:
        pixels_len = shape[0] * shape[1]
        reduction_ratio = math.sqrt(pixels_len / max_len)
        new_rows = shape[0] / reduction_ratio
        new_cols = shape[1] / reduction_ratio

        if new_rows > 64:
            reduction_ratio = 64 / new_rows
            new_rows = 64
            new_cols = new_cols * reduction_ratio
        elif new_cols > 64:
            reduction_ratio = 64 / new_cols
            new_cols = 64
            new_rows = new_rows * reduction_ratio

        if new_rows < 1.0:
            new_shape = (1, new_cols)
        elif new_cols < 1.0:
            new_shape = (new_rows, 1)
        else:
            new_shape = (
                int(new_rows),
                int(new_cols),
            )
    else:
        new_shape = (1, max_len)

    return new_shape, pixels_len


class Teleplot:
    """Send diagnostic values to the VS Code Teleplot UDP listener."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    @staticmethod
    def send(string):
        """Send string to teleplot"""

        try:
            Teleplot.sock.sendto(string.encode(), ("127.0.0.1", 47269))
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to send data to teleplot: %s", e)


def aggressive_top_end_bias(x, boost):
    """Apply an aggressive top-end bias to input values."""

    aggressive_curve = 1 - (1 - x) ** 4  # Adjust power for curve steepness
    return (1 - boost) * x + boost * aggressive_curve


def get_sorted_physical_ips() -> list[str]:
    """Returns a sorted list of local non-loopback IPv4 addresses from physical
    interfaces.
    """
    try:
        import psutil

        ip_usage_list = []

        physical_keywords = [
            "eth",
            "en",
            "ens",
            "eno",
            "enp",
            "wlan",
            "wl",  # Linux
            "Wi-Fi",
            "Ethernet",
            "Local Area",  # Windows
            "en",
            "bridge",  # macOS
        ]

        _LOGGER.debug("Starting local IP discovery")

        stats = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)

        for iface_name, iface_addrs in psutil.net_if_addrs().items():
            if not any(keyword in iface_name for keyword in physical_keywords):
                _LOGGER.debug("Skipping non-physical interface: %s", iface_name)
                continue
            if iface_name not in stats or not stats[iface_name].isup:
                _LOGGER.debug("Skipping inactive interface: %s", iface_name)
                continue

            _LOGGER.debug("Inspecting interface: %s", iface_name)
            for addr in iface_addrs:
                if addr.family == socket.AF_INET:
                    if addr.address.startswith("127."):
                        _LOGGER.debug(
                            "Skipping loopback address on %s: %s",
                            iface_name,
                            addr.address,
                        )
                        continue
                    counter = counters.get(iface_name)
                    usage = (counter.bytes_sent + counter.bytes_recv) if counter else 0
                    _LOGGER.debug(
                        "Discovered IP %s on %s with usage %s",
                        addr.address,
                        iface_name,
                        usage,
                    )
                    ip_usage_list.append((usage, addr.address))
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to get network interface info: %s", e)
        primary_ip = get_primary_ip()
        if primary_ip:
            return [primary_ip]
        else:
            _LOGGER.warning(
                "No network interfaces found and primary IP detection failed."
            )
            return []

    ip_usage_list.sort(reverse=True)
    sorted_ips = [ip for _, ip in ip_usage_list]

    primary_ip = get_primary_ip()

    if primary_ip is not None:
        if primary_ip in sorted_ips:
            sorted_ips.remove(primary_ip)
        sorted_ips.insert(0, primary_ip)

    _LOGGER.info("Final sorted IP list: %s", sorted_ips)
    return sorted_ips


def get_primary_ip() -> str:
    """Returns the primary local IPv4 address used for outbound traffic. This works
    across Windows, macOS, Linux, and Android (Termux, etc.).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))  # Doesn't send packets; just gets routing info
        ip = s.getsockname()[0]
        s.close()
        _LOGGER.debug("Primary outbound IP detected: %s", ip)
        return ip
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Primary IP detection via socket failed: %s", e)
        return None  # no fallback


def nonlinear_log(x, power=3):
    """Apply a nonlinear logarithmic transformation to the input value(s)."""
    return np.sign(x) * (abs(x) ** power)
