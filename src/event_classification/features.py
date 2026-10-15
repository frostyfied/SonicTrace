"""Acoustic feature extraction from transient audio buffers."""

from __future__ import annotations

import math
import numpy as np

from src.event_classification.types import AcousticFeatures


def extract_acoustic_features(
    left: np.ndarray,
    right: np.ndarray,
    sample_rate: int = 48000,
) -> AcousticFeatures:
    """Extract temporal envelope and spectral distribution features from a stereo buffer.

    Args:
        left: 1D array of left channel transient samples.
        right: 1D array of right channel transient samples.
        sample_rate: Audio sampling frequency in Hz.

    Returns:
        AcousticFeatures instance with attack time, crest factor, spectral centroid, etc.
    """
    n = min(len(left), len(right))
    if n == 0:
        return AcousticFeatures(
            attack_time_ms=0.0,
            crest_factor_db=0.0,
            spectral_centroid_hz=0.0,
            high_low_ratio=1.0,
            dominant_band="mid",
            rms_db=-60.0,
            peak_db=-60.0,
        )

    l = left[:n]
    r = right[:n]
    mono = (l + r) * 0.5

    # 1. Temporal envelope: Attack time & Peak index
    abs_mono = np.abs(mono)
    peak_idx = int(np.argmax(abs_mono))
    peak_val = float(abs_mono[peak_idx])
    attack_time_ms = (peak_idx / float(sample_rate)) * 1000.0

    # 2. RMS and Crest Factor
    rms_val = float(np.sqrt(np.mean(mono**2)))
    crest_ratio = (peak_val / (rms_val + 1e-9))
    crest_factor_db = 20.0 * math.log10(max(1.0, crest_ratio))

    peak_db = 20.0 * math.log10(peak_val) if peak_val > 1e-6 else -60.0
    rms_db = 20.0 * math.log10(rms_val) if rms_val > 1e-6 else -60.0

    # 3. Spectral Centroid and Band Energies via FFT
    fft_mono = np.fft.rfft(mono)
    magnitudes = np.abs(fft_mono)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    mag_sum = float(np.sum(magnitudes))
    if mag_sum > 1e-9:
        spectral_centroid_hz = float(np.sum(freqs * magnitudes) / mag_sum)
    else:
        spectral_centroid_hz = 0.0

    # Energy in Low (< 1200 Hz), Mid (1200 - 3500 Hz), High (> 3500 Hz)
    low_mask = (freqs >= 80.0) & (freqs < 1200.0)
    high_mask = freqs >= 2200.0

    low_energy = float(np.sum(magnitudes[low_mask] ** 2))
    high_energy = float(np.sum(magnitudes[high_mask] ** 2))
    high_low_ratio = (high_energy + 1e-9) / (low_energy + 1e-9)

    mid_mask = (freqs >= 1200.0) & (freqs < 3500.0)
    mid_energy = float(np.sum(magnitudes[mid_mask] ** 2))

    if high_energy >= mid_energy and high_energy >= low_energy:
        dominant_band = "high"
    elif mid_energy >= low_energy:
        dominant_band = "mid"
    else:
        dominant_band = "low"

    return AcousticFeatures(
        attack_time_ms=round(attack_time_ms, 2),
        crest_factor_db=round(crest_factor_db, 2),
        spectral_centroid_hz=round(spectral_centroid_hz, 1),
        high_low_ratio=round(high_low_ratio, 3),
        dominant_band=dominant_band,
        rms_db=round(rms_db, 1),
        peak_db=round(peak_db, 1),
    )
