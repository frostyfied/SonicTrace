"""Unit tests for transient sound event detection using synthetic signals."""

from __future__ import annotations

import numpy as np
import pytest

from src.config.settings import DetectorConfig, SpatialConfig
from src.event_detection.detector import TransientEventDetector
from tests.conftest import (
    make_burst_sequence,
    make_crescendo,
    make_isolated_impulse,
    make_sine_wave,
    make_stereo_signal,
)


def _feed_in_chunks(
    detector: TransientEventDetector,
    signal: np.ndarray,
    chunk_size: int = 2048,
    sample_rate: int = 48000,
) -> list:
    """Helper to stream an audio buffer through the detector in realistic chunks."""
    all_events = []
    num_samples = len(signal)
    chunk_dur = chunk_size / float(sample_rate)

    t = 0.0
    for start in range(0, num_samples, chunk_size):
        chunk = signal[start : start + chunk_size]
        events = detector.process_chunk(chunk, timestamp=t)
        all_events.extend(events)
        t += chunk_dur

    return all_events


def test_isolated_impulse_triggers_single_event() -> None:
    config = DetectorConfig(
        sta_window_ms=20.0,
        lta_window_ms=300.0,
        threshold_ratio=2.5,
        min_trigger_db=-40.0,
        cooldown_ms=80.0,
    )
    detector = TransientEventDetector(config=config, sample_rate=48000)

    # 350ms quiet baseline, 20ms loud impulse (-3 dBFS), 350ms quiet baseline
    signal = make_isolated_impulse(
        sample_rate=48000,
        pre_baseline_s=0.35,
        impulse_s=0.02,
        post_baseline_s=0.35,
        baseline_amp=0.003,
        impulse_amp=0.707,
    )

    events = _feed_in_chunks(detector, signal)

    assert len(events) == 1
    event = events[0]
    assert event.event_id == "evt_1"
    assert event.energy_ratio >= 2.5
    assert event.peak_db > -10.0
    # Balanced stereo input -> center bias
    assert abs(event.channel_bias) < 0.15


def test_cooldown_suppresses_rapid_retrigger() -> None:
    # Cooldown of 80ms. Two bursts separated by only 30ms (within cooldown)
    config = DetectorConfig(
        sta_window_ms=20.0,
        lta_window_ms=300.0,
        threshold_ratio=2.5,
        cooldown_ms=80.0,
    )
    detector = TransientEventDetector(config=config, sample_rate=48000)

    # Burst 1, 30ms gap (should be suppressed by cooldown), then return to baseline
    signal = make_burst_sequence(
        sample_rate=48000,
        delays_between_bursts_s=[0.030],
        burst_dur_s=0.015,
        burst_amp=0.6,
    )

    events = _feed_in_chunks(detector, signal)
    # Only the first burst should trigger
    assert len(events) == 1


def test_distinct_bursts_trigger_multiple_events() -> None:
    # Cooldown of 60ms. Two bursts separated by 140ms (exceeding cooldown)
    config = DetectorConfig(
        sta_window_ms=20.0,
        lta_window_ms=300.0,
        threshold_ratio=2.5,
        cooldown_ms=60.0,
    )
    detector = TransientEventDetector(config=config, sample_rate=48000)

    signal = make_burst_sequence(
        sample_rate=48000,
        delays_between_bursts_s=[0.140],
        burst_dur_s=0.015,
        burst_amp=0.6,
    )

    events = _feed_in_chunks(detector, signal)
    # Both bursts should trigger as separate events
    assert len(events) == 2
    assert events[0].event_id == "evt_1"
    assert events[1].event_id == "evt_2"
    assert events[1].timestamp > events[0].timestamp


def test_gradual_crescendo_no_false_positives() -> None:
    config = DetectorConfig(
        sta_window_ms=20.0,
        lta_window_ms=300.0,
        threshold_ratio=2.5,
    )
    detector = TransientEventDetector(config=config, sample_rate=48000)

    # Gradual volume swell from 0.005 to 0.035 (+17 dB) over 1.5 seconds
    signal = make_crescendo(sample_rate=48000, duration_s=1.5, start_amp=0.005, end_amp=0.035)

    events = _feed_in_chunks(detector, signal)
    # LTA smoothly adapts; no sudden ratio spikes >= 2.5
    assert len(events) == 0


def test_steady_continuous_tone_no_events() -> None:
    config = DetectorConfig(threshold_ratio=2.5)
    detector = TransientEventDetector(config=config, sample_rate=48000)

    # Steady 1kHz sine wave for 1 second
    mono = make_sine_wave(frequency_hz=1000.0, amplitude=0.4, duration_s=1.0)
    signal = make_stereo_signal(mono, mono)

    events = _feed_in_chunks(detector, signal)
    # Steady energy -> STA ≈ LTA -> ratio ≈ 1.0 -> 0 events
    assert len(events) == 0


def test_directional_stereo_bias() -> None:
    config = DetectorConfig(threshold_ratio=2.5, cooldown_ms=50.0)
    detector = TransientEventDetector(config=config, sample_rate=48000)

    # 1. Hard Left Transient
    pre_quiet = np.zeros((int(0.3 * 48000), 2), dtype=np.float32) + 0.002
    burst_l = make_sine_wave(1200.0, 0.7, 0.02, 48000)
    burst_r = np.zeros_like(burst_l)
    burst_left_stereo = np.column_stack((burst_l, burst_r))
    post_quiet = np.zeros((int(0.2 * 48000), 2), dtype=np.float32) + 0.002

    left_signal = np.concatenate([pre_quiet, burst_left_stereo, post_quiet])
    left_events = _feed_in_chunks(detector, left_signal)

    assert len(left_events) == 1
    # Channel bias should be strongly negative (Left)
    assert left_events[0].channel_bias < -0.8

    detector.reset()

    # 2. Hard Right Transient
    burst_r = make_sine_wave(1200.0, 0.7, 0.02, 48000)
    burst_l = np.zeros_like(burst_r)
    burst_right_stereo = np.column_stack((burst_l, burst_r))

    right_signal = np.concatenate([pre_quiet, burst_right_stereo, post_quiet])
    right_events = _feed_in_chunks(detector, right_signal)

    assert len(right_events) == 1
    # Channel bias should be strongly positive (Right)
    assert right_events[0].channel_bias > 0.8


def test_detector_reset() -> None:
    detector = TransientEventDetector()
    detector._event_counter = 5
    detector._sta_energy = 0.5
    detector._lta_energy = 0.5
    detector._last_event_time = 100.0

    detector.reset()
    assert detector._event_counter == 0
    assert detector._last_event_time == -1.0
    assert detector._sta_energy == 1e-6
    assert detector._lta_energy == 1e-6


def test_self_echo_lockout_suppression() -> None:
    fs = 48000
    config = DetectorConfig(
        sta_window_ms=20.0,
        lta_window_ms=300.0,
        threshold_ratio=2.5,
        cooldown_ms=50.0,
    )
    spatial_cfg = SpatialConfig(
        bilateral_self_threshold_db=-4.0,
        self_echo_lockout_ms=180.0,
        suppress_self_sounds=False,
        require_mouse_for_self=False,
    )
    detector = TransientEventDetector(
        config=config,
        spatial_config=spatial_cfg,
        sample_rate=fs,
    )

    # Burst 1: Point-blank self shot at amp 0.95 (exceeds -4.0 dBFS)
    # Burst 2: Wall reflection echo 120ms later at amp 0.40 (-7.9 dBFS)
    # Without self lockout, the 120ms delay exceeds the 50ms standard cooldown.
    # With 180ms self lockout, the reflection echo MUST be suppressed!
    pre_quiet = np.zeros((int(0.20 * fs), 2), dtype=np.float32)
    shot = np.ones((int(0.015 * fs), 2), dtype=np.float32) * 0.95
    inter_gap = np.zeros((int(0.120 * fs), 2), dtype=np.float32)
    echo = np.ones((int(0.015 * fs), 2), dtype=np.float32) * 0.40
    post_quiet = np.zeros((int(0.20 * fs), 2), dtype=np.float32)

    signal = np.concatenate([pre_quiet, shot, inter_gap, echo, post_quiet])
    events = _feed_in_chunks(detector, signal)

    # Only the initial self gunshot should trigger; the wall echo is suppressed by lockout
    assert len(events) == 1
    assert events[0].direction.is_self_sound

