import os
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Config dir of the live LedFx; its ledfx.log and ledfx-stdout.log land here.
# CI sets LEDFX_TEST_CONFIG_DIR so it can upload them. Otherwise each pytest
# process gets its own dir, so a second run can't delete the first one's config.
# Named, not created, here: pytest imports this module twice (it matches test_*.py).
TEST_CONFIG_DIR = os.environ.get("LEDFX_TEST_CONFIG_DIR") or os.path.join(
    tempfile.gettempdir(), f"ledfx-test-{os.getpid()}"
)


@dataclass
class APITestCase:
    """API assertion data; response keys/values may be subsets and order is per
    group.
    """

    execution_order: int
    method: Literal["GET", "POST", "PUT", "DELETE"]
    api_endpoint: str
    expected_return_code: int
    payload_to_send: dict[str, object] | None = None
    expected_response_keys: list[str] = None
    expected_response_values: list[dict[str, object]] | None = None
    sleep_after_test: float = 0


class HTTPSession:
    def __init__(
        self,
        retries=5,
        backoff_factor=0.25,
        status_forcelist=(500, 502, 504),
        allowed_methods=frozenset(
            ["HEAD", "TRACE", "GET", "PUT", "POST", "OPTIONS", "DELETE"]
        ),
    ):
        """Initialize the RetrySession object."""
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.status_forcelist = status_forcelist
        self.allowed_methods = allowed_methods
        self.session = self.requests_retry_session()

    def requests_retry_session(self):
        """Creates a session object with retry functionality for making HTTP
        requests.
        """
        session = requests.Session()
        retry = Retry(
            total=None,
            read=self.retries,
            connect=self.retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.status_forcelist,
            allowed_methods=self.allowed_methods,
            raise_on_status=False,
            other=self.retries,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def send_test_api_request(self, url, method, payload: str | dict | None = None):
        """Sends a test API request to the specified URL using the specified HTTP
        method.
        """
        headers = {"Content-Type": "application/json"}
        try:
            if method == "GET":
                response = self.session.get(url, headers=headers)
            elif method == "POST":
                response = self.session.post(url, json=payload, headers=headers)
            elif method == "PUT":
                response = self.session.put(url, json=payload, headers=headers)
            elif method == "DELETE":
                response = self.session.delete(url, json=payload, headers=headers)
            else:
                raise ValueError(f"Invalid method: {method}")
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"An error occurred while sending the API request: {e!s}")
        return response


class SystemInfo:
    @staticmethod
    def calc_available_fps():
        """Calculate the available frames per second (fps) based on the system's
        clock resolution. Note: This comes from the ledfx/utils.py file
        """
        if (sys.version_info[0] == 3 and sys.version_info[1] >= 11) or sys.version_info[  # noqa: YTT201, YTT203
            0
        ] >= 4:
            clock_source = "perf_counter"
        else:
            clock_source = "monotonic"
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

    @staticmethod
    def default_fps():
        available_fps = SystemInfo.calc_available_fps()
        default_fps = next(
            (f for f in available_fps if f >= 60), list(available_fps)[-1]
        )
        return default_fps
