"""Pytest fixtures and synthetic audio generators."""

from __future__ import annotations

import sys

# Ensure COM apartment initialization mode is APARTMENTTHREADED for pycaw / comtypes
if not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 0

import numpy as np
import pytest


def make_sine_wave(
    frequency_hz: float = 1000.0,
    amplitude: float = 1.0,
    duration_s: float = 0.1,
    sample_rate: int = 48000,
) -> np.ndarray:
    """Generate a single-channel sinusoidal audio buffer."""
    num_samples = int(duration_s * sample_rate)
    t = np.linspace(0.0, duration_s, num_samples, endpoint=False, dtype=np.float32)
    return amplitude * np.sin(2.0 * np.pi * frequency_hz * t).astype(np.float32)


def make_stereo_signal(
    left_samples: np.ndarray,
    right_samples: np.ndarray,
) -> np.ndarray:
    """Combine two mono arrays into an interleaved (N, 2) stereo array."""
    return np.column_stack((left_samples, right_samples)).astype(np.float32)


def make_isolated_impulse(
    sample_rate: int = 48000,
    pre_baseline_s: float = 0.35,
    impulse_s: float = 0.02,
    post_baseline_s: float = 0.35,
    baseline_amp: float = 0.003,  # ~ -50 dBFS
    impulse_amp: float = 0.707,   # ~ -3 dBFS
) -> np.ndarray:
    """Generate a steady low ambient baseline with a single sharp burst in the middle."""
    pre = make_sine_wave(frequency_hz=440.0, amplitude=baseline_amp, duration_s=pre_baseline_s, sample_rate=sample_rate)
    impulse = make_sine_wave(frequency_hz=1200.0, amplitude=impulse_amp, duration_s=impulse_s, sample_rate=sample_rate)
    post = make_sine_wave(frequency_hz=440.0, amplitude=baseline_amp, duration_s=post_baseline_s, sample_rate=sample_rate)

    mono = np.concatenate([pre, impulse, post])
    return make_stereo_signal(mono, mono)


def make_burst_sequence(
    sample_rate: int = 48000,
    delays_between_bursts_s: list[float] = [0.14],
    burst_dur_s: float = 0.015,
    burst_amp: float = 0.6,
    baseline_amp: float = 0.003,
) -> np.ndarray:
    """Generate a sequence of bursts with varying inter-burst intervals."""
    parts = []
    # Initial baseline
    parts.append(make_sine_wave(440.0, baseline_amp, 0.35, sample_rate))

    # First burst
    parts.append(make_sine_wave(1000.0, burst_amp, burst_dur_s, sample_rate))

    for delay in delays_between_bursts_s:
        # Silence/baseline gap between bursts
        parts.append(make_sine_wave(440.0, baseline_amp, delay, sample_rate))
        # Subsequent burst
        parts.append(make_sine_wave(1000.0, burst_amp, burst_dur_s, sample_rate))

    # Post-burst baseline
    parts.append(make_sine_wave(440.0, baseline_amp, 0.3, sample_rate))
    mono = np.concatenate(parts)
    return make_stereo_signal(mono, mono)


def make_crescendo(
    sample_rate: int = 48000,
    duration_s: float = 1.5,
    start_amp: float = 0.005,
    end_amp: float = 0.035,
) -> np.ndarray:
    """Generate a smooth gradual volume ramp without sudden transients."""
    num_samples = int(duration_s * sample_rate)
    t = np.linspace(0.0, duration_s, num_samples, endpoint=False, dtype=np.float32)
    envelope = np.linspace(start_amp, end_amp, num_samples, dtype=np.float32)
    mono = envelope * np.sin(2.0 * np.pi * 500.0 * t).astype(np.float32)
    return make_stereo_signal(mono, mono)


@pytest.fixture
def sine_0dbfs_stereo() -> np.ndarray:
    """Full-scale (amplitude 1.0) 1kHz stereo sine wave."""
    mono = make_sine_wave(frequency_hz=1000.0, amplitude=1.0, duration_s=0.05)
    return make_stereo_signal(mono, mono)


@pytest.fixture
def silence_stereo() -> np.ndarray:
    """Zero-amplitude digital silence buffer."""
    num_samples = 2048
    return np.zeros((num_samples, 2), dtype=np.float32)


@pytest.fixture
def hard_panned_left() -> np.ndarray:
    """Full-scale signal on left channel and silence on right channel."""
    left = make_sine_wave(frequency_hz=1000.0, amplitude=1.0, duration_s=0.05)
    right = np.zeros_like(left)
    return make_stereo_signal(left, right)


@pytest.fixture
def hard_panned_right() -> np.ndarray:
    """Silence on left channel and full-scale signal on right channel."""
    right = make_sine_wave(frequency_hz=1000.0, amplitude=1.0, duration_s=0.05)
    left = np.zeros_like(right)
    return make_stereo_signal(left, right)
