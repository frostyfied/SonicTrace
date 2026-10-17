"""GCC-PHAT Cross-Correlation for robust Interaural Time Difference (ITD) estimation.

Uses Generalized Cross-Correlation with Phase Transform (GCC-PHAT) spectral
whitening for sharp, unambiguous delay peaks even in reverberant game environments,
with envelope-assisted disambiguation for high-frequency transients.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np


def compute_gcc_phat_itd(
    left_samples: np.ndarray,
    right_samples: np.ndarray,
    sample_rate: int = 48000,
    max_itd_ms: float = 0.70,
    phat_beta: float = 0.85,
) -> Tuple[float, float]:
    """Compute Interaural Time Difference (ITD) in milliseconds and correlation confidence.

    Uses GCC-PHAT (Generalized Cross-Correlation with Phase Transform) which
    whitens the cross-power spectrum by dividing by its magnitude. This produces
    sharper correlation peaks in reverberant game audio (indoor maps, corridors,
    wall reflections) compared to standard energy-normalized cross-correlation.

    Args:
        left_samples: 1D array of left channel samples.
        right_samples: 1D array of right channel samples.
        sample_rate: Audio sampling rate in Hz.
        max_itd_ms: Maximum physically plausible delay across human head (typically 0.65-0.70 ms).
        phat_beta: PHAT whitening strength in [0.0, 1.0]. 1.0 = full PHAT (sharpest peaks,
                   most noise sensitive). 0.0 = standard CC (no whitening). Default 0.85
                   balances sharp peaks with robustness to low-SNR transients.

    Returns:
        Tuple of (itd_ms, confidence):
            itd_ms: Positive if Right channel leads Left (sound from Right),
                    Negative if Left leads Right (sound from Left),
                    Near zero if sound is centered / directly ahead.
            confidence: Value in [0.0, 1.0] representing cross-correlation coefficient.
    """
    n_len = min(len(left_samples), len(right_samples))
    if n_len < 16:
        return 0.0, 0.0

    # Ensure zero-padding to next power of 2 >= 2*n_len to prevent circular convolution
    n_fft = 1 << int(math.ceil(math.log2(2 * n_len)))

    l_slice = left_samples[:n_len].astype(np.float32, copy=False)
    r_slice = right_samples[:n_len].astype(np.float32, copy=False)

    xl = np.fft.rfft(l_slice, n=n_fft)
    xr = np.fft.rfft(r_slice, n=n_fft)

    # Cross-spectral density: G = X_L * conj(X_R)
    # When Left channel is delayed relative to Right channel (sound arriving at Right first),
    # the correlation peak occurs at positive lag (positive ITD).
    cross_spectrum = xl * np.conj(xr)

    # GCC-PHAT whitening: divide cross-spectrum by its magnitude.
    magnitude = np.abs(cross_spectrum)
    phat_weight = np.power(magnitude + 1e-10, phat_beta)
    cross_spectrum_phat = cross_spectrum / phat_weight

    # Time-domain cross-correlation via IFFT of the whitened cross-spectrum
    cc_phat = np.fft.irfft(cross_spectrum_phat, n=n_fft)

    # Standard energy-normalized cross-correlation for bounded [0, 1] confidence scoring
    cc_standard = np.fft.irfft(cross_spectrum, n=n_fft)
    energy_norm = math.sqrt(float(np.sum(l_slice**2)) * float(np.sum(r_slice**2))) + 1e-9
    cc_standard = cc_standard / energy_norm

    # Physical search limit in samples
    max_lag_samples = int(math.ceil((max_itd_ms / 1000.0) * sample_rate))

    # Reconstruct continuous lag window centered at lag 0:
    # Lags [-max_lag, ..., -1] are stored at cc[-max_lag:]
    # Lags [0, ..., +max_lag] are stored at cc[:max_lag + 1]
    window_phat = np.concatenate([cc_phat[-max_lag_samples:], cc_phat[: max_lag_samples + 1]])
    if len(window_phat) == 0:
        return 0.0, 0.0

    # High-frequency carrier cycle-skipping guard:
    # When dominant spectral energy lies above 2400 Hz (half-wavelength < max_itd_ms),
    # weight the carrier cross-correlation with the non-negative amplitude envelope correlation
    # so impulsive transients never lock onto an aliased grating lobe.
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    spec_power = magnitude
    total_power = float(np.sum(spec_power)) + 1e-12
    high_power = float(np.sum(spec_power[freqs >= 2400.0]))
    if (high_power / total_power) > 0.75:
        env_l = np.abs(l_slice) - float(np.mean(np.abs(l_slice)))
        env_r = np.abs(r_slice) - float(np.mean(np.abs(r_slice)))
        env_norm = math.sqrt(float(np.sum(env_l**2)) * float(np.sum(env_r**2)))
        if env_norm > 1e-7:
            el_fft = np.fft.rfft(env_l, n=n_fft)
            er_fft = np.fft.rfft(env_r, n=n_fft)
            cc_env = np.fft.irfft(el_fft * np.conj(er_fft), n=n_fft) / env_norm
            win_env = np.concatenate([cc_env[-max_lag_samples:], cc_env[: max_lag_samples + 1]])
            env_peak = float(np.max(win_env))
            # If the signal has a clear transient envelope (not a steady continuous sine wave),
            # guide carrier peak selection using the positive envelope correlation profile.
            if env_peak > 0.35 and (env_peak - float(np.min(win_env))) > 0.25:
                env_guide = np.clip(win_env / (env_peak + 1e-9), 0.15, 1.0)
                search_window = window_phat * env_guide
            else:
                search_window = window_phat
        else:
            search_window = window_phat
    else:
        search_window = window_phat

    # Peak finding on GCC-PHAT (guided by envelope when high-frequency impulsive)
    peak_local_idx = int(np.argmax(search_window))
    peak_val = float(window_phat[peak_local_idx])

    # Convert window index to lag relative to zero
    best_lag = float(peak_local_idx - max_lag_samples)

    # Parabolic sub-sample interpolation for fractional-sample precision
    if 0 < peak_local_idx < len(window_phat) - 1:
        y_prev = float(window_phat[peak_local_idx - 1])
        y_curr = peak_val
        y_next = float(window_phat[peak_local_idx + 1])
        denom = y_prev - (2.0 * y_curr) + y_next
        if abs(denom) > 1e-10:
            delta = 0.5 * (y_prev - y_next) / denom
            best_lag += max(-0.5, min(0.5, delta))

    itd_sec = best_lag / float(sample_rate)
    itd_ms = itd_sec * 1000.0
    itd_ms = max(-max_itd_ms, min(max_itd_ms, itd_ms))

    # Confidence from standard Pearson cross-correlation across the 3-sample neighborhood
    # of the PHAT-selected lag (prevents fractional-sample phase offset from under-scoring).
    window_std = np.concatenate([cc_standard[-max_lag_samples:], cc_standard[: max_lag_samples + 1]])
    lo_idx = max(0, peak_local_idx - 1)
    hi_idx = min(len(window_std), peak_local_idx + 2)
    confidence = float(max(0.0, min(1.0, float(np.max(window_std[lo_idx:hi_idx])))))

    return itd_ms, confidence
