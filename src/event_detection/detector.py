"""Transient sound event detection using STA/LTA energy ratios and refractory cooldowns."""

from __future__ import annotations

import math
import time
from typing import Optional

import numpy as np

from src.config.settings import DetectorConfig, SpatialConfig
from src.direction_estimation.estimator import DirectionEstimator
from src.event_classification.classifier import SoundClassifier
from src.event_classification.types import SoundType
from src.event_detection.types import SoundEvent


class TransientEventDetector:
    """Detects candidate sound events (e.g. gunshots, footsteps) using STA/LTA energy ratios."""

    def __init__(
        self,
        config: Optional[DetectorConfig] = None,
        spatial_config: Optional[SpatialConfig] = None,
        sample_rate: int = 48000,
        subframe_size: int = 512,
    ) -> None:
        self.config = config or DetectorConfig()
        self.spatial_config = spatial_config or SpatialConfig()
        self.sample_rate = sample_rate
        self.subframe_size = subframe_size

        self.direction_estimator = DirectionEstimator(
            config=self.spatial_config,
            sample_rate=self.sample_rate,
        )
        self.classifier = SoundClassifier(sample_rate=self.sample_rate)

        # Time constants for exponential moving averages
        self._tau_sta = max(0.001, self.config.sta_window_ms / 1000.0)
        self._tau_lta = max(0.010, self.config.lta_window_ms / 1000.0)
        self._cooldown_sec = self.config.cooldown_ms / 1000.0
        self._lta_freeze_sec = self.config.lta_freeze_ms / 1000.0

        # Rolling energy states
        self._initialized: bool = False
        self._sta_energy: float = 1e-6
        self._lta_energy: float = 1e-6

        self._last_event_time: float = -1.0
        self._last_self_sound_time: float = -1.0
        self._lta_frozen_until: float = -1.0
        self._event_counter: int = 0

        # Rolling context buffer for wider direction estimation window.
        # Direction estimation on a single 512-sample subframe (~10.7ms) provides very
        # coarse FFT resolution and cross-correlation precision. By storing recent filtered
        # samples and extracting a wider 2048-sample context centered on the trigger point,
        # we get 4x better frequency resolution and much more reliable ITD/ILD estimates.
        self._context_target_samples: int = 2048
        self._prev_left: np.ndarray = np.zeros(0, dtype=np.float32)
        self._prev_right: np.ndarray = np.zeros(0, dtype=np.float32)

    def update_spatial_config(self, config: SpatialConfig) -> None:
        """Update spatial parameters and re-initialize direction estimator."""
        self.spatial_config = config
        self.direction_estimator = DirectionEstimator(
            config=config,
            sample_rate=self.sample_rate,
        )

    def reset(self) -> None:
        """Reset internal rolling energy baselines and event counter."""
        self._initialized = False
        self._sta_energy = 1e-6
        self._lta_energy = 1e-6
        self._last_event_time = -1.0
        self._last_self_sound_time = -1.0
        self._lta_frozen_until = -1.0
        self._event_counter = 0
        self._prev_left = np.zeros(0, dtype=np.float32)
        self._prev_right = np.zeros(0, dtype=np.float32)
        self.classifier.reset()

    def _apply_high_pass(self, channel: np.ndarray) -> np.ndarray:
        """High-pass filter channel to eliminate low-frequency rumble below cutoff."""
        cutoff = self.config.high_pass_hz
        if cutoff <= 0.0 or len(channel) < 32:
            return channel
        n = len(channel)
        fft_c = np.fft.rfft(channel)
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sample_rate)
        fft_c[freqs < cutoff] = 0.0
        return np.fft.irfft(fft_c, n=n).astype(np.float32)

    def _extract_context_window(
        self,
        extended_left: np.ndarray,
        extended_right: np.ndarray,
        trigger_center_in_ext: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Extract a wider context window centered on the trigger point for direction estimation.

        Uses the extended buffer (previous chunk + current chunk) to extract up to
        _context_target_samples samples centered on the trigger, providing much better
        FFT frequency resolution and cross-correlation precision than a raw 512-sample subframe.
        """
        half_ctx = self._context_target_samples // 2
        ctx_start = max(0, trigger_center_in_ext - half_ctx)
        ctx_end = min(len(extended_left), trigger_center_in_ext + half_ctx)
        return extended_left[ctx_start:ctx_end], extended_right[ctx_start:ctx_end]

    def process_chunk(
        self,
        samples: np.ndarray,
        timestamp: Optional[float] = None,
        is_firing: Optional[bool] = None,
    ) -> list[SoundEvent]:
        """Analyze an audio buffer and return any detected sound events.

        Args:
            samples: Audio array of shape (N, channels) or (N,), float32 in [-1.0, 1.0].
            timestamp: Monotonic timestamp for the start of this chunk.

        Returns:
            List of detected SoundEvent records (usually 0 or 1 per chunk).
        """
        now = time.monotonic() if timestamp is None else timestamp
        events: list[SoundEvent] = []

        if len(samples) == 0:
            return events

        # Normalize channel dimensions
        if samples.ndim == 1:
            left_ch = samples
            right_ch = samples
        elif samples.ndim == 2:
            left_ch = samples[:, 0]
            right_ch = samples[:, 1] if samples.shape[1] > 1 else samples[:, 0]
        else:
            return events

        # Strip ambient open-world rumble (wind/engine < 120 Hz)
        if self.config.high_pass_hz > 0.0:
            left_filtered = self._apply_high_pass(left_ch)
            right_filtered = self._apply_high_pass(right_ch)
        else:
            left_filtered = left_ch
            right_filtered = right_ch

        # Build extended buffer: previous chunk + current chunk for wider context windows.
        # When a trigger fires at the start of a chunk, the previous chunk's samples
        # provide backward context for the direction estimation window.
        extended_left = np.concatenate([self._prev_left, left_filtered])
        extended_right = np.concatenate([self._prev_right, right_filtered])
        prev_len = len(self._prev_left)

        num_samples = len(left_ch)
        subframe_dur = self.subframe_size / float(self.sample_rate)

        # Alpha smoothing factors for EMA
        alpha_sta = 1.0 - math.exp(-subframe_dur / self._tau_sta)
        alpha_lta = 1.0 - math.exp(-subframe_dur / self._tau_lta)

        # Process the chunk in subframes for high temporal resolution
        for start_idx in range(0, num_samples, self.subframe_size):
            end_idx = min(num_samples, start_idx + self.subframe_size)
            sub_len = end_idx - start_idx
            if sub_len == 0:
                continue

            sub_time = now + (start_idx / float(self.sample_rate))
            sub_left = left_filtered[start_idx:end_idx]
            sub_right = right_filtered[start_idx:end_idx]

            left_energy = float(np.mean(sub_left**2))
            right_energy = float(np.mean(sub_right**2))
            frame_energy = (left_energy + right_energy) * 0.5

            peak_amp = float(max(np.max(np.abs(sub_left)), np.max(np.abs(sub_right))))
            peak_db = 20.0 * math.log10(peak_amp) if peak_amp > 1e-6 else -60.0

            # Establish initial baseline on first non-silent or initial frame
            if not self._initialized:
                self._sta_energy = max(1e-6, frame_energy)
                self._lta_energy = max(1e-6, frame_energy)
                self._initialized = True
                continue

            # Compute trigger ratio using RAW frame energy against LTA baseline.
            # Using frame_energy directly (instead of the EMA-smoothed STA) captures
            # the full onset spike without dilution from the previous STA value.
            # This is critical for detecting sharp transients that the EMA would smooth down.
            noise_floor = 1e-6
            ratio = frame_energy / (self._lta_energy + noise_floor)

            # Save pre-update STA for the onset verification check below.
            # This prevents the circular dependency where is_onset compared frame_energy
            # against an STA that already included frame_energy.
            pre_update_sta = self._sta_energy

            # Update STA (Short-Term Average) — done AFTER ratio computation
            self._sta_energy = (1.0 - alpha_sta) * self._sta_energy + alpha_sta * frame_energy

            time_since_last_event = sub_time - self._last_event_time
            time_since_last_self = sub_time - self._last_self_sound_time
            self_lockout_sec = self.spatial_config.self_echo_lockout_ms / 1000.0

            in_cooldown = (
                time_since_last_event < self._cooldown_sec
                or time_since_last_self < self_lockout_sec
            )

            # Ensure the current subframe is actively in an onset attack, not in a decaying tail.
            # Uses pre-update STA so that a decaying tail (where frame_energy < old STA)
            # is properly rejected, rather than always passing because STA was just
            # blended with the current frame_energy.
            is_onset = frame_energy >= (pre_update_sta * 0.4)

            # Trigger condition
            if (
                ratio >= self.config.threshold_ratio
                and peak_db >= self.config.min_trigger_db
                and not in_cooldown
                and is_onset
            ):
                self._last_event_time = sub_time
                self._lta_frozen_until = sub_time + self._lta_freeze_sec

                # Channel bias calculation: -1.0 (Hard Left) to +1.0 (Hard Right)
                total_energy = left_energy + right_energy + 1e-10
                channel_bias = float(
                    max(-1.0, min(1.0, (right_energy - left_energy) / total_energy))
                )

                # Extract wider context window for direction estimation.
                # Instead of the raw 512-sample subframe, extract up to 2048 samples
                # centered on the trigger point from the extended buffer (prev + current chunk).
                # This provides 4x better FFT frequency resolution and cross-correlation precision.
                trigger_center_in_ext = prev_len + start_idx + sub_len // 2
                ctx_left, ctx_right = self._extract_context_window(
                    extended_left, extended_right, trigger_center_in_ext
                )

                # Direction estimation (ITD, ILD, multi-band dominance, confidence, self-sound)
                direction_est = self.direction_estimator.estimate(
                    ctx_left, ctx_right, peak_db=peak_db, is_firing=is_firing
                )

                # Sound event classification (Footstep, Gunshot, Self-Weapon, Self-Step, Generic)
                sound_type, features = self.classifier.classify(
                    left_samples=ctx_left,
                    right_samples=ctx_right,
                    direction=direction_est,
                    peak_db=peak_db,
                    timestamp=sub_time,
                    spatial_config=self.spatial_config,
                )

                is_self = direction_est.is_self_sound or sound_type == SoundType.SELF
                if is_self:
                    self._last_self_sound_time = sub_time

                # Check suppression rules (default: suppress_self_sounds is False, so self sounds trigger halo)
                suppress_self = self.spatial_config.suppress_self_sounds and is_self

                if not suppress_self:
                    self._event_counter += 1
                    event = SoundEvent(
                        event_id=f"evt_{self._event_counter}",
                        timestamp=sub_time,
                        peak_db=peak_db,
                        energy_ratio=ratio,
                        channel_bias=channel_bias,
                        duration_ms=round(subframe_dur * 1000.0, 1),
                        direction=direction_est,
                        sound_type=sound_type,
                        features=features,
                    )
                    events.append(event)

            # Update LTA rolling baseline
            # Anti-poisoning: dampen LTA update during active event freeze to protect ambient baseline
            if sub_time < self._lta_frozen_until:
                effective_alpha_lta = alpha_lta * 0.05
            else:
                effective_alpha_lta = alpha_lta

            self._lta_energy = (
                (1.0 - effective_alpha_lta) * self._lta_energy
                + effective_alpha_lta * frame_energy
            )

        # Store current chunk's filtered samples for the next chunk's context buffer
        self._prev_left = left_filtered.copy()
        self._prev_right = right_filtered.copy()

        return events

