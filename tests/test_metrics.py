"""Unit tests for audio level metrics calculation and ballistics."""

from __future__ import annotations

import math
import numpy as np
import pytest

from src.audio_processing.metrics import LevelMetricsCalculator
from src.config.settings import MeterConfig
from tests.conftest import make_sine_wave, make_stereo_signal


def test_full_scale_sine_metrics(sine_0dbfs_stereo: np.ndarray) -> None:
    calculator = LevelMetricsCalculator()
    metrics = calculator.compute_levels(sine_0dbfs_stereo)

    assert not metrics.is_silent
    # Peak for full-scale sine should be ~0.0 dBFS
    assert metrics.left.peak_db == pytest.approx(0.0, abs=0.1)
    assert metrics.right.peak_db == pytest.approx(0.0, abs=0.1)

    # RMS of sine with amplitude 1.0 is 1/sqrt(2) ≈ -3.0103 dBFS
    expected_rms_db = 20.0 * math.log10(1.0 / math.sqrt(2))
    assert metrics.left.rms_db == pytest.approx(expected_rms_db, abs=0.2)
    assert metrics.right.rms_db == pytest.approx(expected_rms_db, abs=0.2)


def test_attenuated_sine_metrics() -> None:
    # 0.1 amplitude corresponds to -20 dBFS peak
    mono = make_sine_wave(amplitude=0.1, duration_s=0.05)
    stereo = make_stereo_signal(mono, mono)

    calculator = LevelMetricsCalculator()
    metrics = calculator.compute_levels(stereo)

    assert not metrics.is_silent
    assert metrics.left.peak_db == pytest.approx(-20.0, abs=0.2)
    expected_rms_db = -20.0 + 20.0 * math.log10(1.0 / math.sqrt(2))
    assert metrics.left.rms_db == pytest.approx(expected_rms_db, abs=0.3)


def test_digital_silence(silence_stereo: np.ndarray) -> None:
    config = MeterConfig(min_db=-60.0)
    calculator = LevelMetricsCalculator(meter_config=config, silence_threshold_db=-55.0)
    metrics = calculator.compute_levels(silence_stereo)

    assert metrics.is_silent
    assert metrics.left.rms_db == config.min_db
    assert metrics.right.rms_db == config.min_db
    assert metrics.left.peak_db == config.min_db
    assert metrics.right.peak_db == config.min_db


def test_default_silence_threshold(silence_stereo: np.ndarray) -> None:
    calculator = LevelMetricsCalculator()
    metrics = calculator.compute_levels(silence_stereo)
    assert metrics.is_silent


def test_stereo_channel_independence(
    hard_panned_left: np.ndarray,
    hard_panned_right: np.ndarray,
) -> None:
    config = MeterConfig(min_db=-60.0)
    calculator = LevelMetricsCalculator(meter_config=config)

    # 1. Hard Left Signal
    left_metrics = calculator.compute_levels(hard_panned_left)
    assert left_metrics.left.peak_db == pytest.approx(0.0, abs=0.1)
    assert left_metrics.right.peak_db == config.min_db
    assert not left_metrics.is_silent

    calculator.reset()

    # 2. Hard Right Signal
    right_metrics = calculator.compute_levels(hard_panned_right)
    assert right_metrics.right.peak_db == pytest.approx(0.0, abs=0.1)
    assert right_metrics.left.peak_db == config.min_db
    assert not right_metrics.is_silent


def test_instant_attack(silence_stereo: np.ndarray, sine_0dbfs_stereo: np.ndarray) -> None:
    calculator = LevelMetricsCalculator()
    # First frame is silence
    m1 = calculator.compute_levels(silence_stereo, timestamp=10.0)
    assert m1.left.rms_db == -60.0

    # Second frame is full scale - should attack immediately
    m2 = calculator.compute_levels(sine_0dbfs_stereo, timestamp=10.05)
    assert m2.left.rms_db > -4.0


def test_decay_ballistics(sine_0dbfs_stereo: np.ndarray, silence_stereo: np.ndarray) -> None:
    config = MeterConfig(min_db=-60.0, decay_rate_db_per_sec=40.0)
    calculator = LevelMetricsCalculator(meter_config=config)

    # Loud signal at t=1.0
    m_loud = calculator.compute_levels(sine_0dbfs_stereo, timestamp=1.0)
    loud_rms = m_loud.left.rms_db

    # Silence at t=1.5 (dt = 0.5s)
    # Expected decay: 40 dB/s * 0.5s = 20 dB drop
    m_decay = calculator.compute_levels(silence_stereo, timestamp=1.5)
    expected_decayed_rms = loud_rms - 20.0

    assert m_decay.left.rms_db == pytest.approx(expected_decayed_rms, abs=0.5)


def test_peak_hold_timing(sine_0dbfs_stereo: np.ndarray, silence_stereo: np.ndarray) -> None:
    config = MeterConfig(min_db=-60.0, peak_hold_ms=500, decay_rate_db_per_sec=40.0)
    calculator = LevelMetricsCalculator(meter_config=config)

    # Loud pulse at t=0.0
    calculator.compute_levels(sine_0dbfs_stereo, timestamp=0.0)

    # Silence at t=0.3 (within 500ms hold window)
    m_held = calculator.compute_levels(silence_stereo, timestamp=0.3)
    assert m_held.left.peak_held_db == pytest.approx(0.0, abs=0.1)

    # Silence at t=0.8 (0.3s after hold window expired)
    # Expected decay: 40 dB/s * (0.8 - 0.3) = 20 dB
    m_expired = calculator.compute_levels(silence_stereo, timestamp=0.8)
    assert m_expired.left.peak_held_db < -10.0


def test_reset_clears_state(sine_0dbfs_stereo: np.ndarray) -> None:
    calculator = LevelMetricsCalculator()
    calculator.compute_levels(sine_0dbfs_stereo, timestamp=1.0)
    calculator.reset()

    assert calculator._left_smoothed_rms_db == calculator.config.min_db
    assert calculator._right_smoothed_rms_db == calculator.config.min_db
    assert calculator._left_peak_held_db == calculator.config.min_db
    assert calculator._right_peak_held_db == calculator.config.min_db
