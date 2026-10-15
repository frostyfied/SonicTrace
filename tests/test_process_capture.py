"""Unit tests for per-application audio session scanning and isolated process loopback capture."""

from __future__ import annotations

import sys
if not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 0

import queue
import unittest.mock as mock
import numpy as np
import pytest

from src.audio_capture.process_scanner import (
    AudioProcessInfo,
    find_process_by_name,
    find_process_by_pid,
    list_active_audio_processes,
)
from src.audio_capture.service import AudioCaptureService
from src.audio_capture.types import CaptureState, StatusEvent
from src.audio_processing.types import LevelMetrics
from src.config.settings import AudioConfig


def test_process_scanner_listing_and_deduplication() -> None:
    """Verify that process scanner enumerates, deduplicates, and sorts audio sessions."""
    # Create fake session objects with mock Process
    mock_proc1 = mock.MagicMock()
    mock_proc1.pid = 1001
    mock_proc1.name.return_value = "Discord.exe"

    mock_proc2 = mock.MagicMock()
    mock_proc2.pid = 2002
    mock_proc2.name.return_value = "TslGame.exe"

    # Duplicate session for Discord (e.g. multi-channel/renderer session)
    mock_proc1_dup = mock.MagicMock()
    mock_proc1_dup.pid = 1001
    mock_proc1_dup.name.return_value = "Discord.exe"

    session1 = mock.MagicMock()
    session1.Process = mock_proc1
    session1.State = 1

    session2 = mock.MagicMock()
    session2.Process = mock_proc2
    session2.State = 1

    session3 = mock.MagicMock()
    session3.Process = mock_proc1_dup
    session3.State = 0

    with mock.patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=[session1, session2, session3]):
        processes = list_active_audio_processes()

    # Must be deduplicated (2 unique processes)
    assert len(processes) == 2
    # Must be sorted alphabetically
    assert processes[0].process_name == "Discord.exe"
    assert processes[0].pid == 1001
    assert processes[0].display_name == "Discord.exe (PID: 1001)"
    assert processes[0].is_active is True

    assert processes[1].process_name == "TslGame.exe"
    assert processes[1].pid == 2002


def test_find_process_by_pid_and_name() -> None:
    """Verify helper lookup functions for process info."""
    fake_procs = [
        AudioProcessInfo(pid=5000, process_name="VALORANT.exe", display_name="VALORANT.exe (PID: 5000)", is_active=True),
        AudioProcessInfo(pid=6000, process_name="Spotify.exe", display_name="Spotify.exe (PID: 6000)", is_active=False),
    ]

    with mock.patch("src.audio_capture.process_scanner.list_active_audio_processes", return_value=fake_procs):
        # By PID
        match_pid = find_process_by_pid(5000)
        assert match_pid is not None
        assert match_pid.process_name == "VALORANT.exe"

        none_pid = find_process_by_pid(9999)
        assert none_pid is None

        # By Name (case-insensitive)
        match_name = find_process_by_name("valorant.exe")
        assert match_name is not None
        assert match_name.pid == 5000

        none_name = find_process_by_name("unknown.exe")
        assert none_name is None


def test_capture_service_target_process_switching() -> None:
    """Verify that setting and clearing target process updates properties and triggers switch event."""
    service = AudioCaptureService()
    assert not service.is_process_mode
    assert service.target_pid is None
    assert service.target_process_name is None

    # Set target process to PUBG
    service.set_target_process(pid=6724, name="TslGame.exe")
    assert service.is_process_mode
    assert service.target_pid == 6724
    assert service.target_process_name == "TslGame.exe"
    assert service.audio_config.target_pid == 6724
    assert service.audio_config.target_process_name == "TslGame.exe"
    assert service._switch_event.is_set()

    # Revert to Master Loopback
    service._switch_event.clear()
    service.set_target_process(pid=None, name=None)
    assert not service.is_process_mode
    assert service.target_pid is None
    assert service.target_process_name is None
    assert service.audio_config.target_pid is None
    assert service._switch_event.is_set()


def test_capture_service_process_loop_data_flow() -> None:
    """Verify that _run_process_capture properly ingests raw PCM, converts to numpy, and pushes metrics."""
    test_queue = queue.Queue(maxsize=50)
    service = AudioCaptureService(event_queue=test_queue)
    service.set_target_process(pid=9999, name="Game.exe")

    # Generate synthetic float32 stereo audio block (256 frames * 2 channels * 4 bytes = 2048 bytes)
    samples = np.full((256, 2), 0.25, dtype=np.float32)
    raw_pcm = samples.tobytes()

    mock_tap = mock.MagicMock()
    # Return one block of audio, then set stop_event
    def mock_read(timeout=0.15):
        service._stop_event.set()
        return raw_pcm

    mock_tap.read.side_effect = mock_read

    with mock.patch("psutil.pid_exists", return_value=True), \
         mock.patch("proctap.ProcessAudioCapture", return_value=mock_tap):
        service._run_process_capture(pid=9999)

    # Tap must have started, stopped, and closed cleanly
    mock_tap.start.assert_called_once()
    mock_tap.stop.assert_called_once()
    mock_tap.close.assert_called_once()

    # Items in queue must include StatusEvents and at least one LevelMetrics
    items = []
    while not test_queue.empty():
        items.append(test_queue.get_nowait())

    metrics_items = [it for it in items if isinstance(it, LevelMetrics)]
    assert len(metrics_items) >= 1
    assert metrics_items[0].left.peak_db > -20.0
    assert metrics_items[0].right.peak_db > -20.0


def test_capture_service_process_termination_handling() -> None:
    """Verify that if the target game process closes, the service detects it and transitions to SILENCE."""
    test_queue = queue.Queue(maxsize=50)
    service = AudioCaptureService(event_queue=test_queue)
    service.set_target_process(pid=8888, name="ExitingGame.exe")

    mock_tap = mock.MagicMock()
    mock_tap.read.return_value = None  # No audio returned when process terminates

    # First call pid_exists -> True (attaching), second call -> False (process closed)
    with mock.patch("psutil.pid_exists", side_effect=[True, False]), \
         mock.patch("proctap.ProcessAudioCapture", return_value=mock_tap):
        service._run_process_capture(pid=8888)

    # Must transition to SILENCE status indicating app closed
    status_events = []
    while not test_queue.empty():
        it = test_queue.get_nowait()
        if isinstance(it, StatusEvent):
            status_events.append(it)

    silence_events = [ev for ev in status_events if ev.state == CaptureState.SILENCE]
    assert len(silence_events) >= 1
    assert "closed" in silence_events[0].message.lower()
