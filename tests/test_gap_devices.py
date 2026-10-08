from ledfx.utils import is_gap_device


class MockDevice:
    def __init__(self, device_id, device_type):
        self.id = device_id
        self.type = device_type


class TestGapDeviceIdentification:
    def test_gap_device_identification(self):
        assert is_gap_device(MockDevice("gap-", "dummy"))
        assert is_gap_device(MockDevice("gap-matrix", "dummy"))
        assert is_gap_device(MockDevice("gap-my-virtual", "dummy"))
        assert is_gap_device(MockDevice("gap-livingroom", "dummy"))
        assert is_gap_device(MockDevice("gap-mapping", "dummy"))

    def test_non_gap_device_identification(self):
        assert not is_gap_device(MockDevice("test-device", "dummy"))
        assert not is_gap_device(MockDevice("wled-device", "dummy"))
        assert not is_gap_device(MockDevice("dummy", "dummy"))
        assert not is_gap_device(MockDevice("", "dummy"))
        assert not is_gap_device(MockDevice("gapdevice", "dummy"))  # no hyphen
        assert not is_gap_device(
            MockDevice("my-gap-device", "dummy")
        )  # doesn't start with gap-

    def test_special_device_types(self):
        assert not is_gap_device(MockDevice("test-device-background", "dummy"))
        assert not is_gap_device(MockDevice("test-device-foreground", "dummy"))
        assert not is_gap_device(MockDevice("test-device-mask", "dummy"))

    def test_gap_device_with_dummy_type(self):
        assert is_gap_device(MockDevice("gap-test", "dummy"))
        assert is_gap_device(MockDevice("gap-matrix", "dummy"))
        assert is_gap_device(MockDevice("gap-my-virtual", "dummy"))

    def test_gap_device_with_wrong_type(self):
        assert not is_gap_device(MockDevice("gap-test", "wled"))
        assert not is_gap_device(MockDevice("gap-matrix", "e131"))

    def test_non_gap_device_with_any_type(self):
        assert not is_gap_device(MockDevice("test-device", "dummy"))
        assert not is_gap_device(MockDevice("wled-device", "wled"))
        assert not is_gap_device(MockDevice("my-device", "dummy"))


class TestGapDeviceIntegration:
    def test_validate_segment_logic(self):

        import ledfx.virtuals
        from ledfx.utils import is_gap_device

        assert hasattr(ledfx.virtuals, "is_gap_device")

        assert is_gap_device(MockDevice("gap-test", "dummy"))
        assert not is_gap_device(MockDevice("real-device", "wled"))

    def test_devices_module_imports(self):
        from ledfx.utils import is_gap_device

        assert is_gap_device(MockDevice("gap-test", "dummy"))
