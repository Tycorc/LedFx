from unittest.mock import MagicMock

from ledfx.events import EventListener, Events


class TestEventListener:
    def test_filter_independence_without_args(self):
        """Default filters must be independent to prevent mutable-default state
        pollution.
        """
        callback1 = MagicMock()
        callback2 = MagicMock()

        listener1 = EventListener(callback1)
        assert listener1.filter == {}

        listener1.filter["type"] = "device"
        listener1.filter["status"] = "active"

        listener2 = EventListener(callback2)

        assert listener2.filter == {}, (
            f"Expected empty filter for listener2, got {listener2.filter}. "
            "This indicates mutable default argument bug."
        )

        assert listener1.filter == {"type": "device", "status": "active"}

    def test_explicit_filter_works(self):
        callback = MagicMock()
        custom_filter = {"event_type": "virtual_update"}

        listener = EventListener(callback, custom_filter)

        assert listener.filter is custom_filter
        assert listener.filter == {"event_type": "virtual_update"}

    def test_empty_dict_passed_explicitly(self):
        callback = MagicMock()
        explicit_empty = {}

        listener = EventListener(callback, explicit_empty)

        assert listener.filter is explicit_empty


class TestEventsAddListener:
    def test_add_listener_filter_independence(self):
        """Default filters must remain independent through Events.add_listener."""
        ledfx_mock = MagicMock()
        ledfx_mock.loop = MagicMock()
        events = Events(ledfx_mock)

        callback1 = MagicMock()
        callback2 = MagicMock()

        events.add_listener(callback1, "device_update")

        listener1 = events._listeners["device_update"][0]
        listener1.filter["source"] = "api"

        events.add_listener(callback2, "virtual_update")

        listener2 = events._listeners["virtual_update"][0]

        assert listener2.filter == {}, (
            f"Expected empty filter for listener2, got {listener2.filter}. "
            "Filter pollution from listener1 detected."
        )

        assert listener1.filter == {"source": "api"}

    def test_add_listener_with_explicit_filter(self):
        ledfx_mock = MagicMock()
        ledfx_mock.loop = MagicMock()
        events = Events(ledfx_mock)

        callback = MagicMock()
        custom_filter = {"device_id": "123"}

        events.add_listener(callback, "device_update", custom_filter)

        listener = events._listeners["device_update"][0]
        assert listener.filter == {"device_id": "123"}
