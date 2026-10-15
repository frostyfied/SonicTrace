"""Audio level and ballistics metrics calculator.

Performs robust RMS, peak, and dBFS calculations with broadcast-standard
meter ballistics (instant attack, configurable exponential decay, and peak hold).
"""

from __future__ import annotations

import math
import time
from typing import Optional

import numpy as np

from src.audio_processing.types import ChannelLevel, LevelMetrics
from src.config.settings import MeterConfig


class LevelMetricsCalculator:
    """Calculates smoothed stereo audio levels, peak holds, and silence status."""

    def __init__(
        self,
        meter_config: Optional[MeterConfig] = None,
        silence_threshold_db: float = -50.0,
        mono_duration_threshold_s: float = 2.0,
    ) -> None:
        self.config = meter_config or MeterConfig()
        self.silence_threshold_db = silence_threshold_db
        self.mono_duration_threshold_s = mono_duration_threshold_s

        # Smoothed state in dBFS
        self._left_smoothed_rms_db: float = self.config.min_db
        self._right_smoothed_rms_db: float = self.config.min_db

        self._left_peak_held_db: float = self.config.min_db
        self._right_peak_held_db: float = self.config.min_db

        self._left_peak_timestamp: float = 0.0
        self._right_peak_timestamp: float = 0.0

        self._last_process_time: Optional[float] = None

        # Audio health tracking
        self._mono_duration_s: float = 0.0
        self._is_mono_detected: bool = False
        self._last_correlation: float = 1.0
        self._clipping_hold_s: float = 0.0

    def reset(self) -> None:
        """Reset internal smoothed state, peak holds, and health monitors."""
        self._left_smoothed_rms_db = self.config.min_db
        self._right_smoothed_rms_db = self.config.min_db
        self._left_peak_held_db = self.config.min_db
        self._right_peak_held_db = self.config.min_db
        self._left_peak_timestamp = 0.0
        self._right_peak_timestamp = 0.0
        self._last_process_time = None
        self._mono_duration_s = 0.0
        self._is_mono_detected = False
        self._last_correlation = 1.0
        self._clipping_hold_s = 0.0

    def _linear_to_db(self, linear_value: float) -> float:
        """Convert a linear amplitude (0.0 to 1.0+) to dBFS, clamped to [min_db, max_db]."""
        if linear_value <= 1e-6:
            return self.config.min_db
        db = 20.0 * math.log10(linear_value)
        return max(self.config.min_db, min(self.config.max_db, db))

    def compute_levels(
        self,
        samples: np.ndarray,
        timestamp: Optional[float] = None,
    ) -> LevelMetrics:
        """Calculate stereo level metrics and health diagnostics from an audio buffer.

        Args:
            samples: 2D numpy array of shape (N, channels) or 1D array of shape (N,).
                     Expected to be floating point samples nominally in range [-1.0, 1.0].
            timestamp: Optional epoch or monotonic timestamp. Defaults to time.monotonic().

        Returns:
            LevelMetrics containing left/right levels, silence, mono detection, and clipping flags.
        """
        now = time.monotonic() if timestamp is None else timestamp
        dt = 0.0 if self._last_process_time is None else max(0.0, now - self._last_process_time)
        self._last_process_time = now

        # Normalize buffer dimensions
        is_hardware_mono = (samples.ndim == 2 and samples.shape[1] == 1) or (samples.ndim == 1)
        if samples.ndim == 1:
            left_ch = samples
            right_ch = samples
        elif samples.ndim == 2:
            if samples.shape[1] >= 2:
                left_ch = samples[:, 0]
                right_ch = samples[:, 1]
            elif samples.shape[1] == 1:
                left_ch = samples[:, 0]
                right_ch = samples[:, 0]
            else:
                left_ch = np.zeros(0, dtype=np.float32)
                right_ch = np.zeros(0, dtype=np.float32)
        else:
            left_ch = np.zeros(0, dtype=np.float32)
            right_ch = np.zeros(0, dtype=np.float32)

        left_metrics = self._process_channel(
            channel_samples=left_ch,
            now=now,
            dt=dt,
            is_left=True,
        )
        right_metrics = self._process_channel(
            channel_samples=right_ch,
            now=now,
            dt=dt,
            is_left=False,
        )

        is_silent = (
            left_metrics.peak_db <= self.silence_threshold_db
            and right_metrics.peak_db <= self.silence_threshold_db
        )

        # Audio Health & Mono Detection
        if is_hardware_mono:
            self._mono_duration_s += dt
            if self._mono_duration_s >= 0.5:
                self._is_mono_detected = True
            self._last_correlation = 1.0
        else:
            self._is_mono_detected = False
            self._mono_duration_s = 0.0
            if not is_silent and left_ch.size > 0 and right_ch.size > 0:
                energy_l = float(np.sum(left_ch ** 2))
                energy_r = float(np.sum(right_ch ** 2))
                if energy_l > 1e-7 and energy_r > 1e-7:
                    dot_prod = float(np.sum(left_ch * right_ch))
                    corr = dot_prod / (math.sqrt(energy_l * energy_r) + 1e-12)
                    self._last_correlation = float(max(-1.0, min(1.0, corr)))

        # Peak clipping detection (hard digital limit at 0 dBFS / sample >= 0.999)
        max_peak = max(left_metrics.peak_linear, right_metrics.peak_linear)
        if max_peak >= 0.999:
            self._clipping_hold_s = 1.0
        elif dt > 0:
            self._clipping_hold_s = max(0.0, self._clipping_hold_s - dt)
        is_clipping = self._clipping_hold_s > 0.0

        return LevelMetrics(
            timestamp=now,
            left=left_metrics,
            right=right_metrics,
            is_silent=is_silent,
            is_mono=self._is_mono_detected,
            is_clipping=is_clipping,
            channel_correlation=self._last_correlation,
        )


    def _process_channel(
        self,
        channel_samples: np.ndarray,
        now: float,
        dt: float,
        is_left: bool,
    ) -> ChannelLevel:
        """Calculate and apply ballistics to a single audio channel."""
        if len(channel_samples) == 0:
            rms_linear = 0.0
            peak_linear = 0.0
        else:
            # Linear RMS and Peak
            rms_linear = float(np.sqrt(np.mean(channel_samples**2)))
            peak_linear = float(np.max(np.abs(channel_samples)))

        raw_rms_db = self._linear_to_db(rms_linear)
        raw_peak_db = self._linear_to_db(peak_linear)

        prev_smoothed_rms = (
            self._left_smoothed_rms_db if is_left else self._right_smoothed_rms_db
        )
        prev_held_peak = (
            self._left_peak_held_db if is_left else self._right_peak_held_db
        )
        peak_timestamp = (
            self._left_peak_timestamp if is_left else self._right_peak_timestamp
        )

        # RMS Ballistics: Instant attack, exponential decay in dB
        if raw_rms_db >= prev_smoothed_rms:
            smoothed_rms_db = raw_rms_db
        else:
            decay_amount = self.config.decay_rate_db_per_sec * dt
            smoothed_rms_db = max(self.config.min_db, prev_smoothed_rms - decay_amount)

        # Peak Hold Ballistics:
        # If new peak is higher, jump up and reset timer.
        # If hold period has elapsed, decay at decay_rate_db_per_sec.
        hold_sec = self.config.peak_hold_ms / 1000.0
        if raw_peak_db >= prev_held_peak:
            held_peak_db = raw_peak_db
            peak_timestamp = now
        else:
            time_since_peak = now - peak_timestamp
            if time_since_peak < hold_sec:
                held_peak_db = prev_held_peak
            else:
                decay_dt = max(0.0, dt)
                decay_amount = self.config.decay_rate_db_per_sec * decay_dt
                held_peak_db = max(
                    raw_peak_db,
                    max(self.config.min_db, prev_held_peak - decay_amount),
                )

        if is_left:
            self._left_smoothed_rms_db = smoothed_rms_db
            self._left_peak_held_db = held_peak_db
            self._left_peak_timestamp = peak_timestamp
        else:
            self._right_smoothed_rms_db = smoothed_rms_db
            self._right_peak_held_db = held_peak_db
            self._right_peak_timestamp = peak_timestamp

        return ChannelLevel(
            rms_linear=rms_linear,
            peak_linear=peak_linear,
            rms_db=smoothed_rms_db,
            peak_db=raw_peak_db,
            peak_held_db=held_peak_db,
        )
