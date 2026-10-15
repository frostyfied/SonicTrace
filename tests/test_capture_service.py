"""Unit tests for the audio capture service and queue interactions."""

from __future__ import annotations

import queue
import time

from src.audio_capture.service import AudioCaptureService
from src.audio_capture.types import CaptureState, DeviceInfo, StatusEvent
from src.config.settings import AudioConfig, MeterConfig


def test_queue_overflow_eviction() -> None:
    # Service with small queue maxsize
    q: queue.Queue = queue.Queue(maxsize=3)
    service = AudioCaptureService(event_queue=q)

    # Push 5 events - queue should not block or exceed 3 items
    for i in range(5):
        event = StatusEvent(
            timestamp=time.time(),
            state=CaptureState.ACTIVE,
            device_name=f"dev_{i}",
            message=f"msg_{i}",
        )
        service._push_queue(event)

    assert q.qsize() == 3
    # The oldest items (0, 1) should have been evicted; remaining should be 2, 3, 4
    items = []
    while not q.empty():
        items.append(q.get_nowait())

    assert len(items) == 3
    assert items[-1].device_name == "dev_4"
    assert items[0].device_name == "dev_2"


def test_list_playback_devices_structure() -> None:
    devices = AudioCaptureService.list_playback_devices()
    assert isinstance(devices, list)
    # On a Windows machine with audio, at least one device should be found
    for dev in devices:
        assert isinstance(dev, DeviceInfo)
        assert isinstance(dev.name, str)
        assert isinstance(dev.id, str)
        assert isinstance(dev.is_default, bool)


def test_service_initial_state() -> None:
    service = AudioCaptureService()
    assert service.state == CaptureState.STOPPED
    assert service.active_device_name == "None"


def test_silence_state_transition() -> None:
    from unittest.mock import MagicMock, patch
    import numpy as np

    service = AudioCaptureService(
        audio_config=AudioConfig(sample_rate=48000, block_size=2048, silence_threshold_db=-50.0)
    )

    observed_states = []

    def mock_record(numframes: int) -> np.ndarray:
        time.sleep(0.02)
        observed_states.append(service.state)
        return np.zeros((numframes, 2), dtype=np.float32)

    mock_recorder = MagicMock()
    mock_recorder.record.side_effect = mock_record
    mock_recorder.__enter__.return_value = mock_recorder
    mock_recorder.__exit__.return_value = None

    mock_mic = MagicMock()
    mock_mic.name = "Mock Speaker Loopback"
    mock_mic.recorder.return_value = mock_recorder

    with patch.object(service, "_resolve_loopback_device", return_value=mock_mic):
        service.start()
        # 11 frames needed for silence at 48kHz / 2048 block size; 0.02s * 15 = 0.3s
        time.sleep(0.35)
        service.stop()

    assert service._active_device_name == "Mock Speaker Loopback"
    assert CaptureState.SILENCE in observed_states

