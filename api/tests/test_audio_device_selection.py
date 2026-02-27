from __future__ import annotations

from grumpyreachy.app import _device_info, _find_device_index, _parse_device_preferences


def test_parse_device_preferences() -> None:
    assert _parse_device_preferences("respeaker, seeed-4mic, ,ac108") == [
        "respeaker",
        "seeed-4mic",
        "ac108",
    ]


def test_find_device_index_prefers_first_match_with_channels() -> None:
    devices = [
        {"name": "Reachy Mini Audio", "max_input_channels": 2, "max_output_channels": 2},
        {"name": "seeed-4mic-voicecard", "max_input_channels": 4, "max_output_channels": 0},
    ]
    idx = _find_device_index(
        devices,
        io_type="input",
        preferences=["respeaker", "seeed-4mic", "reachy mini"],
    )
    assert idx == 1


def test_find_device_index_ignores_devices_without_required_channels() -> None:
    devices = [
        {"name": "seeed-4mic-voicecard", "max_input_channels": 0, "max_output_channels": 0},
        {"name": "Reachy Mini Audio", "max_input_channels": 2, "max_output_channels": 2},
    ]
    idx = _find_device_index(
        devices,
        io_type="input",
        preferences=["seeed-4mic", "reachy mini"],
    )
    assert idx == 1


def test_device_info_bounds() -> None:
    devices = [
        {
            "name": "seeed-4mic-voicecard",
            "max_input_channels": 4,
            "max_output_channels": 0,
            "default_samplerate": 44100.0,
        }
    ]
    assert _device_info(devices, None) is None
    assert _device_info(devices, -1) is None
    assert _device_info(devices, 8) is None
    assert _device_info(devices, 0) == {
        "id": 0,
        "name": "seeed-4mic-voicecard",
        "max_input_channels": 4,
        "max_output_channels": 0,
        "default_samplerate": 44100.0,
    }
