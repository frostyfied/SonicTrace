"""GCC-PHAT Cross-Correlation for robust Interaural Time Difference (ITD) estimation.

Uses Generalized Cross-Correlation with Phase Transform (GCC-PHAT) spectral
whitening for sharp, unambiguous delay peaks even in reverberant game environments.
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

    l_slice = left_samples[:n_len]
    r_slice = right_samples[:n_len]

    xl = np.fft.rfft(l_slice, n=n_fft)
    xr = np.fft.rfft(r_slice, n=n_fft)

    # Cross-spectral density: G = X_L * conj(X_R)
    # When Left channel is delayed relative to Right channel (sound arriving at Right first),
    # the correlation peak occurs at positive lag (positive ITD).
    cross_spectrum = xl * np.conj(xr)

    # GCC-PHAT whitening: divide cross-spectrum by its magnitude.
    # This flattens the spectral envelope and preserves only phase information,
    # producing much sharper correlation peaks in reverberant environments.
    # phat_beta controls the blend: |G|^beta weighting (beta=1.0 = full PHAT, 0.0 = standard CC).
    magnitude = np.abs(cross_spectrum)
    phat_weight = np.power(magnitude + 1e-10, phat_beta)
    cross_spectrum_phat = cross_spectrum / phat_weight

    # Time-domain cross-correlation via IFFT of the whitened cross-spectrum
    cc_phat = np.fft.irfft(cross_spectrum_phat, n=n_fft)

    # Also compute standard energy-normalized cross-correlation for confidence scoring.
    # GCC-PHAT produces sharper peaks (better for ITD), but the Pearson correlation
    # from unwhitened CC is naturally bounded in [-1, 1] and directly measures
    # inter-channel coherence — making it reliable for confidence assessment.
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

    # Use GCC-PHAT for peak finding (sharper, more robust to reverb)
    peak_local_idx = int(np.argmax(window_phat))
    peak_val = float(window_phat[peak_local_idx])

    # Convert window index to lag relative to zero:
    # index 0 -> -max_lag_samples
    # index max_lag_samples -> 0
    # index 2*max_lag_samples -> +max_lag_samples
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
    # Clamp to max_itd_ms
    itd_ms = max(-max_itd_ms, min(max_itd_ms, itd_ms))

    # Confidence from standard Pearson cross-correlation at the PHAT-selected lag.
    # This evaluates the coherence of the original (unwhitened) signals at the delay
    # found by PHAT, giving us the best of both worlds: PHAT's sharp peak for accurate
    # delay, Pearson's bounded [0, 1] metric for reliable confidence assessment.
    window_std = np.concatenate([cc_standard[-max_lag_samples:], cc_standard[: max_lag_samples + 1]])
    confidence = float(max(0.0, min(1.0, window_std[peak_local_idx])))

    return itd_ms, confidence
