"""Unit tests for acoustic feature extraction, sound classification, and self-footstep suppression."""

from __future__ import annotations

import math
import numpy as np
import pytest

from src.config.settings import DetectorConfig, SpatialConfig
from src.direction_estimation.types import DirectionEstimate
from src.event_classification.classifier import SoundClassifier
from src.event_classification.features import extract_acoustic_features
from src.event_classification.types import SoundType
from src.event_detection.detector import TransientEventDetector


def _generate_gunshot_synthetic(sample_rate: int = 48000, peak_amp: float = 0.5) -> np.ndarray:
    """Synthesize a sharp gunshot transient: explosive 1ms rise + exponential decay + high frequencies."""
    n_samples = 1024
    t = np.arange(n_samples) / float(sample_rate)
    # Fast 3ms decay
    envelope = np.exp(-t / 0.005)
    noise = np.random.RandomState(42).randn(n_samples) * 0.15
    carrier = np.sin(2.0 * math.pi * 3200.0 * t) + noise
    wave = (envelope * carrier).astype(np.float32)
    wave = wave / np.max(np.abs(wave)) * peak_amp
    return wave


def _generate_footstep_synthetic(sample_rate: int = 48000, peak_amp: float = 0.04) -> np.ndarray:
    """Synthesize a footstep transient: softer 10ms mechanical impact rise + low-mid frequency thud."""
    n_samples = 1024
    t = np.arange(n_samples) / float(sample_rate)
    # Soft onset peaking around 10ms (480 samples)
    attack_len = int(0.010 * sample_rate)
    envelope = np.zeros(n_samples, dtype=np.float32)
    envelope[:attack_len] = np.sin(np.linspace(0, math.pi / 2, attack_len))
    envelope[attack_len:] = np.exp(-np.linspace(0, 3.5, n_samples - attack_len))
    # Low-mid impact (450 Hz) + subtle friction
    carrier = np.sin(2.0 * math.pi * 450.0 * t) + 0.15 * np.sin(2.0 * math.pi * 1500.0 * t)
    wave = (envelope * carrier).astype(np.float32)
    wave = wave / (np.max(np.abs(wave)) + 1e-9) * peak_amp
    return wave


def test_acoustic_feature_extraction_gunshot() -> None:
    fs = 48000
    gunshot = _generate_gunshot_synthetic(sample_rate=fs, peak_amp=0.7)
    features = extract_acoustic_features(gunshot, gunshot, sample_rate=fs)

    # Gunshot has fast attack (< 4ms), high crest factor (> 10 dB)
    assert features.attack_time_ms < 4.0
    assert features.crest_factor_db > 10.0
    assert features.peak_db > -10.0


def test_acoustic_feature_extraction_footstep() -> None:
    fs = 48000
    step = _generate_footstep_synthetic(sample_rate=fs, peak_amp=0.03)
    features = extract_acoustic_features(step, step, sample_rate=fs)

    # Footstep has slower rise time (>= 8ms) and lower centroid (< 2000 Hz)
    assert features.attack_time_ms >= 8.0
    assert features.spectral_centroid_hz < 2000.0
    assert -40.0 <= features.peak_db <= -25.0


def test_sound_classifier_classifies_external_sound() -> None:
    fs = 48000
    classifier = SoundClassifier(sample_rate=fs)
    spatial_cfg = SpatialConfig()

    gunshot = _generate_gunshot_synthetic(sample_rate=fs, peak_amp=0.6)
    dir_est = DirectionEstimate(
        azimuth_deg=-30.0,
        itd_ms=-0.25,
        ild_db=-6.0,
        confidence=0.8,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="high",
    )

    sound_type, feats = classifier.classify(
        left_samples=gunshot,
        right_samples=gunshot * 0.5,
        direction=dir_est,
        peak_db=-4.4,
        timestamp=1.0,
        spatial_config=spatial_cfg,
    )
    # External sound event classified as SoundType.SOUND
    assert sound_type == SoundType.SOUND
    # Backwards compatibility alias checks
    assert sound_type == SoundType.GUNSHOT
    assert sound_type == SoundType.FOOTSTEP


def test_sound_classifier_classifies_self_sound() -> None:
    fs = 48000
    classifier = SoundClassifier(sample_rate=fs)
    spatial_cfg = SpatialConfig()

    blast = _generate_gunshot_synthetic(sample_rate=fs, peak_amp=0.9)
    dir_est = DirectionEstimate(
        azimuth_deg=0.0,
        itd_ms=0.0,
        ild_db=0.1,
        confidence=1.0,
        is_self_sound=True,
        is_uncertain=False,
        dominant_band="low",
    )

    sound_type, feats = classifier.classify(
        left_samples=blast,
        right_samples=blast,
        direction=dir_est,
        peak_db=-1.2,
        timestamp=1.5,
        spatial_config=spatial_cfg,
    )
    # Player origin sound classified as SoundType.SELF
    assert sound_type == SoundType.SELF
    assert sound_type == SoundType.SELF_WEAPON


def test_self_sound_suppression_and_emission_in_detector() -> None:
    """Verify that player's own sounds trigger SoundType.SELF when unsuppressed, and are ignored when suppressed."""
    fs = 48000
    config = DetectorConfig(min_trigger_db=-52.0)

    # 1. Default: suppress_self_sounds is False -> emit event with SoundType.SELF (for purple halo HUD)
    spatial_cfg_emit = SpatialConfig(
        suppress_self_sounds=False,
        bilateral_self_threshold_db=-6.0,
        require_mouse_for_self=False,
    )
    detector_emit = TransientEventDetector(config=config, spatial_config=spatial_cfg_emit, sample_rate=fs)

    blast = _generate_gunshot_synthetic(sample_rate=fs, peak_amp=0.9)
    stereo_blast = np.column_stack([blast, blast])

    # Pre-baseline silence
    pre = np.zeros((2048, 2), dtype=np.float32)
    detector_emit.process_chunk(pre, timestamp=0.0)

    events = detector_emit.process_chunk(stereo_blast, timestamp=0.1)
    assert len(events) >= 1
    assert events[0].sound_type == SoundType.SELF
    assert events[0].direction is not None
    assert events[0].direction.is_self_sound

    # 2. When suppress_self_sounds is True -> event is suppressed
    spatial_cfg_suppress = SpatialConfig(
        suppress_self_sounds=True,
        bilateral_self_threshold_db=-6.0,
        require_mouse_for_self=False,
    )
    detector_suppress = TransientEventDetector(config=config, spatial_config=spatial_cfg_suppress, sample_rate=fs)
    detector_suppress.process_chunk(pre, timestamp=0.0)

    suppressed_events = detector_suppress.process_chunk(stereo_blast, timestamp=0.1)
    assert len(suppressed_events) == 0


def test_continuous_distant_gunfire_burst_tracking() -> None:
    """Verify that multi-shot full-auto spray of distant gunfire (-48 dBFS) is not swallowed by LTA."""
    fs = 48000
    config = DetectorConfig(
        sta_window_ms=20.0,
        lta_window_ms=1200.0,
        min_trigger_db=-52.0,
        cooldown_ms=45.0,
        lta_freeze_ms=600.0,
        threshold_ratio=2.2,
    )
    detector = TransientEventDetector(config=config, sample_rate=fs)

    # Pre-quiet ambient background
    quiet = np.random.RandomState(1).randn(int(0.4 * fs), 2).astype(np.float32) * 0.001
    for i in range(0, len(quiet), 1024):
        detector.process_chunk(quiet[i:i+1024], timestamp=i/fs)

    # Gunshot
    shot = _generate_gunshot_synthetic(sample_rate=fs, peak_amp=0.015)
    stereo_shot = np.column_stack([shot, shot])

    detected_shots = 0
    t = 0.5
    gap = np.zeros((int(0.080 * fs), 2), dtype=np.float32)

    for i in range(3):
        evs = detector.process_chunk(stereo_shot, timestamp=t)
        detected_shots += len(evs)
        t += len(stereo_shot) / fs
        detector.process_chunk(gap, timestamp=t)
        t += len(gap) / fs

    # All 3 shots in the rapid burst must register (anti-poisoning prevents LTA swallowing)
    assert detected_shots == 3
