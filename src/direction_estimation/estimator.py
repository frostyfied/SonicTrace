"""Direction estimation combining multi-band filtering, ITD (GCC-PHAT), and ILD cues."""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

from src.config.settings import SpatialConfig
from src.direction_estimation.cross_correlation import compute_gcc_phat_itd
from src.direction_estimation.mouse_tracker import is_left_mouse_down
from src.direction_estimation.types import DirectionEstimate


class DirectionEstimator:
    """Estimates acoustic azimuth direction and confidence from stereo transient buffers."""

    def __init__(
        self,
        config: Optional[SpatialConfig] = None,
        sample_rate: int = 48000,
    ) -> None:
        self.config = config or SpatialConfig()
        self.sample_rate = sample_rate

    def estimate(
        self,
        left_samples: np.ndarray,
        right_samples: np.ndarray,
        peak_db: float = -60.0,
        is_firing: Optional[bool] = None,
    ) -> DirectionEstimate:
        """Calculate spatial azimuth, ITD, ILD, confidence, and self-sound status.

        Args:
            left_samples: 1D array of left channel transient samples.
            right_samples: 1D array of right channel transient samples.
            peak_db: Overall peak dBFS level of the transient.

        Returns:
            DirectionEstimate with azimuth_deg in [-90.0°, +90.0°] (0.0° is Ahead/Front).
        """
        n_len = min(len(left_samples), len(right_samples))
        if n_len < 16:
            return DirectionEstimate(
                azimuth_deg=0.0,
                itd_ms=0.0,
                ild_db=0.0,
                confidence=0.0,
                is_self_sound=False,
                is_uncertain=True,
                dominant_band="mid",
                azimuth_360_deg=0.0,
                is_rear=False,
                front_back_ratio=1.0,
            )

        # 1. Onset-anchored Precedence (Haas) windowing & split-duplex band extraction
        (
            dominant_band,
            flt_left,
            flt_right,
            front_back_ratio,
            ild_db,
            upper_band_share,
        ) = self._extract_duplex_cues(left_samples[:n_len], right_samples[:n_len])

        # 2. Interaural Time Difference (ITD) via GCC-PHAT
        itd_ms, conf_itd = compute_gcc_phat_itd(
            flt_left,
            flt_right,
            sample_rate=self.sample_rate,
            max_itd_ms=self.config.max_itd_ms,
        )

        # 3. Angle estimation using Rayleigh's Duplex Theory
        itd_norm = max(-1.0, min(1.0, itd_ms / self.config.max_itd_ms))
        theta_itd_deg = math.asin(itd_norm) * (180.0 / math.pi)

        # ILD angle: non-linear arcsin mapping (psychoacoustically accurate)
        head_shadow_max_db = 15.0
        ild_norm = max(-1.0, min(1.0, ild_db / head_shadow_max_db))
        theta_ild_deg = math.asin(ild_norm) * (180.0 / math.pi)

        # 4. Continuous cue activation & Sign-Coherence Guard
        # Eliminates the artificial ±5.7° dead zone while still respecting pure stereo amplitude panning
        itd_active = abs(theta_itd_deg) >= 2.5 and conf_itd >= 0.25
        ild_active = abs(ild_db) >= 0.45

        # Sign-Coherence Guard: if indoor wall reflections cause ITD phase lag to oppose
        # a strong ILD energy imbalance (|ILD| >= 2.0 dB), trust the energy hemisphere.
        cues_conflict = (theta_itd_deg * theta_ild_deg) < -9.0

        if cues_conflict and abs(ild_db) >= 2.0:
            fused_azimuth = theta_ild_deg
            confidence = float(min(1.0, 0.45 + abs(ild_db) / 25.0))
        elif ild_active and not itd_active:
            # Standard stereo amplitude panning without binaural delay
            fused_azimuth = theta_ild_deg
            confidence = float(min(1.0, 0.5 + abs(ild_db) / 20.0))
        elif itd_active and not ild_active:
            # Pure phase/delay cue
            fused_azimuth = theta_itd_deg
            confidence = float(conf_itd)
        elif itd_active and ild_active:
            # Both cues active (HRTF binaural): fuse with frequency band weighting
            if dominant_band == "low":
                w_itd, w_ild = 0.60, 0.40
            elif dominant_band == "high":
                w_itd, w_ild = 0.30, 0.70
            else:
                w_itd, w_ild = self.config.itd_weight, self.config.ild_weight
            total_w = w_itd + w_ild
            fused_azimuth = (w_itd * theta_itd_deg + w_ild * theta_ild_deg) / total_w

            angle_diff = abs(theta_itd_deg - theta_ild_deg)
            agreement = max(0.0, 1.0 - (angle_diff / 120.0))
            confidence = float(max(0.0, min(1.0, 0.6 * conf_itd + 0.4 * agreement)))
        else:
            # Both near zero -> Directly Ahead (0.0°)
            fused_azimuth = 0.0
            confidence = float(conf_itd)

        fused_azimuth = float(max(-90.0, min(90.0, fused_azimuth)))
        is_uncertain = confidence < self.config.min_confidence

        # 5. Self-sound check (player's own weapon)
        if not getattr(self.config, "enable_self_sound_gating", True):
            is_self_sound = False
        else:
            sample_peak_amp = (
                float(
                    max(
                        np.max(np.abs(left_samples[:n_len])),
                        np.max(np.abs(right_samples[:n_len])),
                    )
                )
                if n_len > 0
                else 0.0
            )
            peak_l_amp = float(np.max(np.abs(left_samples[:n_len]))) if n_len > 0 else 0.0
            peak_r_amp = float(np.max(np.abs(right_samples[:n_len]))) if n_len > 0 else 0.0

            if sample_peak_amp > 1e-6:
                eff_peak_l_db = peak_db + 20.0 * math.log10((peak_l_amp + 1e-12) / sample_peak_amp)
                eff_peak_r_db = peak_db + 20.0 * math.log10((peak_r_amp + 1e-12) / sample_peak_amp)
            else:
                eff_peak_l_db = peak_db
                eff_peak_r_db = peak_db

            require_mouse = getattr(self.config, "require_mouse_for_self", True)
            if require_mouse:
                mouse_firing = is_firing if is_firing is not None else is_left_mouse_down()
            else:
                mouse_firing = True if is_firing is None else is_firing

            is_bilateral_self = (
                eff_peak_l_db >= self.config.bilateral_self_threshold_db
                and eff_peak_r_db >= self.config.bilateral_self_threshold_db
                and abs(ild_db) <= 3.5
            )

            is_self_sound = bool(mouse_firing and is_bilateral_self)

        # Pin self-sounds to 0.0° (Center/Origin) to prevent weapon stereo offsets from swinging L/R
        if is_self_sound:
            fused_azimuth = 0.0

        # 6. Front vs. Behind (HRTF Pinna Spectral Cues & 360° Polar Bearing)
        is_rear = False
        enable_fb = getattr(self.config, "enable_front_back", False)
        spatial_mode = getattr(self.config, "spatial_mode", "stereo_180")

        if not is_self_sound and enable_fb and spatial_mode == "hrtf_360":
            # Guard 1: Sounds near center (|azimuth| <= 6.0°) must NEVER flip to rear.
            # Guard 2: Distant or wall-occluded sounds (peak_db < -20 dB with complete high-frequency
            # air-absorption rolloff) lack >4.5 kHz HRTF spectral cues and must stay in front.
            is_distance_lpf = (peak_db < -20.0) and (upper_band_share < 1e-4)
            if abs(fused_azimuth) > 6.0 and not is_distance_lpf:
                rear_thresh = getattr(self.config, "rear_ratio_threshold", 0.08)
                is_rear = bool(front_back_ratio < rear_thresh)

        # 360° Polar Mapping:
        # Ahead: 0.0°, Right: +90.0°, Left: -90.0°, Behind: ±180.0°
        if is_self_sound:
            azimuth_360 = 0.0
            is_rear = False
        elif not is_rear:
            azimuth_360 = fused_azimuth
        else:
            if fused_azimuth > 0.0:
                azimuth_360 = 180.0 - fused_azimuth
            elif fused_azimuth < 0.0:
                azimuth_360 = -180.0 - fused_azimuth
            else:
                azimuth_360 = 180.0

        return DirectionEstimate(
            azimuth_deg=round(fused_azimuth, 1),
            itd_ms=round(itd_ms, 3),
            ild_db=round(ild_db, 1),
            confidence=round(confidence, 2),
            is_self_sound=is_self_sound,
            is_uncertain=is_uncertain,
            dominant_band=dominant_band,
            azimuth_360_deg=round(azimuth_360, 1),
            is_rear=is_rear,
            front_back_ratio=round(front_back_ratio, 3),
        )

    def _build_adaptive_onset_window(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        """Build an onset-anchored Precedence (Haas) window for impulsive transients, or Hann for stationary signals.

        Solves two critical accuracy failure modes:
        1. Late-subframe triggers where the transient sits near the end of the buffer (preventing
           a centered Hann window from attenuating the signal by 18+ dB).
        2. Indoor corridor echoes arriving 5-12 ms after the direct wave (prioritizing direct arrival).
        """
        n = len(left)
        if n < 64:
            return np.hanning(n).astype(np.float32)

        inst_power = 0.5 * (left.astype(np.float32) ** 2 + right.astype(np.float32) ** 2)
        # Smooth energy over ~1.5 ms (72 samples at 48 kHz) to locate burst envelope
        k_len = min(n // 4, max(8, int(0.0015 * self.sample_rate)))
        kernel = np.ones(k_len, dtype=np.float32) / float(k_len)
        env = np.convolve(inst_power, kernel, mode="same")

        max_env = float(np.max(env))
        min_env = float(np.min(env))
        if max_env <= 1e-10:
            return np.hanning(n).astype(np.float32)

        # If the signal is a steady continuous test wave (low dynamic range across buffer),
        # use a standard flat-centered Tukey/Hann window so leading delay samples are preserved.
        if min_env > 0.25 * max_env:
            return np.hanning(n).astype(np.float32)

        # Locate the first arrival onset where short-time power exceeds 20% of peak power
        above = np.flatnonzero(env >= 0.20 * max_env)
        onset_idx = int(above[0]) if len(above) > 0 else 0

        # If onset is right at sample 0 (e.g., pre-sliced synthetic impulse), preserve leading edge
        # so initial ITD delay samples at t=0..35 are never zeroed out!
        if onset_idx < int(0.001 * self.sample_rate):
            tau_samples = 0.008 * self.sample_rate
            window = np.exp(-np.arange(n, dtype=np.float32) / tau_samples)
            end_taper = min(64, n // 4)
            window[-end_taper:] *= 0.5 * (
                1.0 + np.cos(np.pi * np.arange(end_taper, dtype=np.float32) / end_taper)
            )
            return window

        # Build asymmetric Haas window anchored at onset_idx:
        # - 2.0 ms smooth cosine pre-roll before onset_idx (captures leading ear arrival)
        # - 3.5 ms flat unity plateau across the direct wave
        # - Exponential Haas decay (tau = 4.5 ms) after plateau to suppress corridor reflections
        pre_roll = min(onset_idx, max(32, int(0.002 * self.sample_rate)))
        plateau = max(64, int(0.0035 * self.sample_rate))
        tau_samples = 0.0045 * self.sample_rate

        window = np.zeros(n, dtype=np.float32)
        start_ramp = onset_idx - pre_roll
        if pre_roll > 0:
            t_r = np.arange(pre_roll, dtype=np.float32) / float(pre_roll)
            window[start_ramp:onset_idx] = 0.5 * (1.0 - np.cos(np.pi * t_r))

        plateau_end = min(n, onset_idx + plateau)
        window[onset_idx:plateau_end] = 1.0

        tail_len = n - plateau_end
        if tail_len > 0:
            decay = np.exp(-np.arange(tail_len, dtype=np.float32) / tau_samples)
            end_taper = min(48, tail_len)
            decay[-end_taper:] *= 0.5 * (
                1.0 + np.cos(np.pi * np.arange(end_taper, dtype=np.float32) / end_taper)
            )
            window[plateau_end:] = decay

        return window

    @staticmethod
    def _cosine_taper_mask(
        freqs: np.ndarray, low_hz: float, high_hz: float, roll_off_hz: float = 200.0
    ) -> np.ndarray:
        """Create a smooth cosine-tapered bandpass mask to avoid Gibbs ringing."""
        mask = np.zeros(len(freqs), dtype=np.float64)

        for i, f in enumerate(freqs):
            if f < low_hz - roll_off_hz or f > high_hz + roll_off_hz:
                mask[i] = 0.0
            elif f < low_hz:
                mask[i] = 0.5 * (1.0 + math.cos(math.pi * (low_hz - f) / roll_off_hz))
            elif f > high_hz:
                mask[i] = 0.5 * (1.0 + math.cos(math.pi * (f - high_hz) / roll_off_hz))
            else:
                mask[i] = 1.0

        return mask

    def _extract_dominant_band(
        self, left: np.ndarray, right: np.ndarray
    ) -> Tuple[str, np.ndarray, np.ndarray, float]:
        """Backward-compatible wrapper returning (dominant_band, flt_l, flt_r, front_back_ratio)."""
        chosen_band, flt_l, flt_r, front_back_ratio, _, _ = self._extract_duplex_cues(left, right)
        return chosen_band, flt_l, flt_r, front_back_ratio

    def _extract_duplex_cues(
        self, left: np.ndarray, right: np.ndarray
    ) -> Tuple[str, np.ndarray, np.ndarray, float, float, float]:
        """Decompose stereo samples using onset-anchored windowing and split-duplex band cues.

        Separates ITD phase extraction from high-frequency head-shadow ILD calculation so that
        bass-heavy footsteps never erase high-band ILD cues, and high-frequency bullet cracks
        never lose their onset timing edge.
        """
        n = len(left)
        window = self._build_adaptive_onset_window(left, right)
        fft_l = np.fft.rfft(left * window)
        fft_r = np.fft.rfft(right * window)

        freqs = np.fft.rfftfreq(n, d=1.0 / self.sample_rate)
        mag_sq_l = np.abs(fft_l) ** 2
        mag_sq_r = np.abs(fft_r) ** 2
        total_spec_energy = float(np.sum(mag_sq_l + mag_sq_r)) + 1e-12

        # Band energy computation
        mask_low = (freqs >= 80.0) & (freqs < 1200.0)
        mask_mid = (freqs >= 1200.0) & (freqs < 4000.0)
        mask_high = freqs >= 4000.0

        energy_low = float(np.sum(mag_sq_l[mask_low] + mag_sq_r[mask_low]))
        energy_mid = float(np.sum(mag_sq_l[mask_mid] + mag_sq_r[mask_mid]))
        energy_high = float(np.sum(mag_sq_l[mask_high] + mag_sq_r[mask_high]))

        # HRTF Pinna spectral ratio: High shelf (>= 7500 Hz) vs Mid presence (1500 - 4500 Hz)
        mask_mid_presence = (freqs >= 1500.0) & (freqs < 4500.0)
        mask_high_shelf = freqs >= 7500.0
        p_mid = float(np.sum(mag_sq_l[mask_mid_presence] + mag_sq_r[mask_mid_presence]))
        p_high = float(np.sum(mag_sq_l[mask_high_shelf] + mag_sq_r[mask_high_shelf]))
        front_back_ratio = float(p_high / (p_mid + 1e-9))

        mask_upper = freqs >= 4500.0
        upper_band_share = float(np.sum(mag_sq_l[mask_upper] + mag_sq_r[mask_upper]) / total_spec_energy)

        # Select dominant band
        if energy_high >= energy_mid and energy_high >= energy_low:
            chosen_band = "high"
        elif energy_mid >= energy_low:
            chosen_band = "mid"
        else:
            chosen_band = "low"

        # Build smooth cosine-tapered bandpass mask for the chosen band
        band_ranges = {
            "low": (80.0, 1200.0),
            "mid": (1200.0, 4000.0),
            "high": (4000.0, self.sample_rate / 2.0),
        }
        low_hz, high_hz = band_ranges[chosen_band]
        smooth_mask = self._cosine_taper_mask(freqs, low_hz, high_hz, roll_off_hz=200.0)

        flt_l = np.fft.irfft(fft_l * smooth_mask, n=n).astype(np.float32)
        flt_r = np.fft.irfft(fft_r * smooth_mask, n=n).astype(np.float32)

        # Split-Duplex ILD Calculation:
        # In HRTF / 3D audio, low frequencies (<1200 Hz) diffract around the head with minimal ILD,
        # while directional head-shadowing ILD is concentrated in the mid/high bands (>=1200 Hz).
        # If dominant_band is "low" but significant mid/high energy exists (>= 3% of total energy),
        # evaluate ILD on the mid/high head-shadow spectrum if it carries a stronger directional cue.
        dom_energy_l = float(np.mean(flt_l**2))
        dom_energy_r = float(np.mean(flt_r**2))
        ild_dom_db = 10.0 * math.log10((dom_energy_r + 1e-9) / (dom_energy_l + 1e-9))

        mask_shadow = freqs >= 1200.0
        shadow_l = float(np.sum(mag_sq_l[mask_shadow]))
        shadow_r = float(np.sum(mag_sq_r[mask_shadow]))
        if chosen_band == "low" and (shadow_l + shadow_r) >= 0.03 * total_spec_energy:
            ild_shadow_db = 10.0 * math.log10((shadow_r + 1e-9) / (shadow_l + 1e-9))
            if abs(ild_shadow_db) > abs(ild_dom_db):
                ild_db = ild_shadow_db
            else:
                ild_db = ild_dom_db
        else:
            ild_db = ild_dom_db

        ild_db = max(-25.0, min(25.0, ild_db))
        return chosen_band, flt_l, flt_r, front_back_ratio, ild_db, upper_band_share
