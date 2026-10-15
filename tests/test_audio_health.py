"""Unit tests for audio health, mono audio detection, and digital clipping."""

from __future__ import annotations

import numpy as np
import pytest

from src.audio_processing.metrics import LevelMetricsCalculator
from tests.conftest import make_sine_wave, make_stereo_signal


def test_stereo_nominal_audio_health() -> None:
    """Distinct stereo signals should maintain healthy correlation and is_mono=False."""
    # Left: 440 Hz sine, Right: 880 Hz sine
    left = make_sine_wave(frequency_hz=440.0, amplitude=0.5, duration_s=0.5)
    right = make_sine_wave(frequency_hz=880.0, amplitude=0.5, duration_s=0.5)
    stereo = make_stereo_signal(left, right)

    calculator = LevelMetricsCalculator(mono_duration_threshold_s=1.0)
    metrics = calculator.compute_levels(stereo, timestamp=1.0)

    assert not metrics.is_silent
    assert not metrics.is_mono
    assert not metrics.is_clipping
    # Orthogonal frequencies have near-zero correlation
    assert abs(metrics.channel_correlation) < 0.2


def test_centered_stereo_audio_does_not_false_trigger_mono() -> None:
    """Centered dialogue or mono-mastered YouTube audio in stereo should NOT trigger is_mono=True."""
    mono = make_sine_wave(frequency_hz=440.0, amplitude=0.5, duration_s=0.1)
    identical_stereo = make_stereo_signal(mono, mono)

    calculator = LevelMetricsCalculator(mono_duration_threshold_s=1.0)

    # Over extended duration, centered stereo tracks should track correlation but never falsely flag mono
    m1 = calculator.compute_levels(identical_stereo, timestamp=0.0)
    assert not m1.is_mono
    assert m1.channel_correlation == pytest.approx(1.0, abs=0.001)

    m2 = calculator.compute_levels(identical_stereo, timestamp=2.5)
    assert not m2.is_mono
    assert m2.channel_correlation == pytest.approx(1.0, abs=0.001)


def test_hardware_single_channel_mono_detection() -> None:
    """A 1-channel mono input buffer immediately accumulates towards mono detection."""
    mono_1ch = make_sine_wave(frequency_hz=440.0, amplitude=0.5, duration_s=0.1).reshape(-1, 1)

    calculator = LevelMetricsCalculator(mono_duration_threshold_s=0.5)
    calculator.compute_levels(mono_1ch, timestamp=0.0)
    m2 = calculator.compute_levels(mono_1ch, timestamp=0.6)

    assert m2.is_mono


def test_digital_clipping_detection() -> None:
    """Full-scale square wave or 1.0 peak samples should trigger clipping flag."""
    clipped_mono = np.ones(512, dtype=np.float32)
    clipped_stereo = make_stereo_signal(clipped_mono, clipped_mono)

    calculator = LevelMetricsCalculator()
    metrics = calculator.compute_levels(clipped_stereo, timestamp=1.0)

    assert metrics.is_clipping
