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

        # Rolling context buffer for wider direction estimation window (2048 samples).
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
        """High-pass filter channel using smooth cosine roll-on to eliminate rumble without ringing."""
        cutoff = self.config.high_pass_hz
        if cutoff <= 0.0 or len(channel) < 32:
            return channel
        n = len(channel)
        fft_c = np.fft.rfft(channel)
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sample_rate)
        taper_w = min(40.0, cutoff * 0.5)
        mask = np.ones_like(freqs, dtype=np.float32)
        mask[freqs <= (cutoff - taper_w)] = 0.0
        in_taper = (freqs > (cutoff - taper_w)) & (freqs < cutoff)
        if np.any(in_taper):
            mask[in_taper] = 0.5 * (
                1.0 + np.cos(np.pi * (cutoff - freqs[in_taper]) / taper_w)
            )
        return np.fft.irfft(fft_c * mask, n=n).astype(np.float32)

    def _extract_context_window(
        self,
        extended_left: np.ndarray,
        extended_right: np.ndarray,
        trigger_start_in_ext: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Extract an onset-aligned context window around the trigger subframe.

        Allocates 256 samples (~5.3ms) of pre-onset margin and up to 1792 samples
        (~37.3ms) of post-onset signal, avoiding excess pre-trigger background noise
        when transients fire in the final subframe of a chunk.
        """
        pre_samples = min(256, self._context_target_samples // 4)
        post_samples = self._context_target_samples - pre_samples
        ctx_start = max(0, trigger_start_in_ext - pre_samples)
        ctx_end = min(len(extended_left), trigger_start_in_ext + post_samples)
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

        # Build extended buffer: previous chunk + current chunk for wider context windows
        extended_left = np.concatenate([self._prev_left, left_filtered])
        extended_right = np.concatenate([self._prev_right, right_filtered])
        prev_len = len(self._prev_left)

        num_samples = len(left_ch)

        # Process the chunk in subframes for high temporal resolution
        for start_idx in range(0, num_samples, self.subframe_size):
            end_idx = min(num_samples, start_idx + self.subframe_size)
            sub_len = end_idx - start_idx
            if sub_len < 32:
                continue

            # Exact subframe duration for variable-sized process loopback buffers
            subframe_dur = sub_len / float(self.sample_rate)
            alpha_sta = 1.0 - math.exp(-subframe_dur / self._tau_sta)
            alpha_lta = 1.0 - math.exp(-subframe_dur / self._tau_lta)

            sub_time = now + (start_idx / float(self.sample_rate))
            sub_left = left_filtered[start_idx:end_idx]
            sub_right = right_filtered[start_idx:end_idx]

            left_energy = float(np.mean(sub_left**2))
            right_energy = float(np.mean(sub_right**2))
            frame_energy = (left_energy + right_energy) * 0.5

            peak_l_amp = float(np.max(np.abs(sub_left)))
            peak_r_amp = float(np.max(np.abs(sub_right)))
            peak_amp = max(peak_l_amp, peak_r_amp)
            peak_db = 20.0 * math.log10(peak_amp) if peak_amp > 1e-6 else -60.0
            left_peak_db = 20.0 * math.log10(peak_l_amp) if peak_l_amp > 1e-6 else -60.0
            right_peak_db = 20.0 * math.log10(peak_r_amp) if peak_r_amp > 1e-6 else -60.0

            # Establish initial baseline on first non-silent or initial frame
            if not self._initialized:
                self._sta_energy = max(1e-6, frame_energy)
                self._lta_energy = max(1e-6, frame_energy)
                self._initialized = True
                continue

            # Compute trigger ratio using RAW frame energy against LTA baseline
            noise_floor = 1e-6
            ratio = frame_energy / (self._lta_energy + noise_floor)

            # Save pre-update STA for the onset verification check
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

            # Ensure current subframe is actively in an onset attack, not a decaying tail
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

                # Extract onset-aligned context window for direction estimation
                trigger_start_in_ext = prev_len + start_idx
                ctx_left, ctx_right = self._extract_context_window(
                    extended_left, extended_right, trigger_start_in_ext
                )

                # Direction estimation (ITD, ILD, multi-band dominance, confidence, self-sound)
                direction_est = self.direction_estimator.estimate(
                    ctx_left, ctx_right, peak_db=peak_db, is_firing=is_firing
                )

                # Sound event classification (External Sound vs Self-Weapon / Self-Footstep)
                sound_type, features = self.classifier.classify(
                    left_samples=ctx_left,
                    right_samples=ctx_right,
                    direction=direction_est,
                    peak_db=peak_db,
                    timestamp=sub_time,
                    spatial_config=self.spatial_config,
                )

                is_self_weapon = direction_est.is_self_sound
                is_self_step = (not is_self_weapon) and (sound_type == SoundType.SELF)
                is_self = is_self_weapon or is_self_step

                if is_self_weapon:
                    self._last_self_sound_time = sub_time

                # Suppress self weapon if configured, or self footsteps when detected by cadence
                suppress_event = (
                    (self.spatial_config.suppress_self_sounds and is_self_weapon)
                    or (self.spatial_config.suppress_self_footsteps and is_self_step)
                )

                if not suppress_event:
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
                        left_peak_db=round(left_peak_db, 1),
                        right_peak_db=round(right_peak_db, 1),
                    )
                    events.append(event)

            # Update LTA rolling baseline (dampened during active burst freeze)
            if sub_time < self._lta_frozen_until:
                effective_alpha_lta = alpha_lta * 0.05
            else:
                effective_alpha_lta = alpha_lta

            self._lta_energy = (
                (1.0 - effective_alpha_lta) * self._lta_energy
                + effective_alpha_lta * frame_energy
            )

        # Retain up to 2048 recent filtered samples for the next chunk's pre-trigger context
        keep_n = min(len(extended_left), self._context_target_samples)
        self._prev_left = extended_left[-keep_n:].copy()
        self._prev_right = extended_right[-keep_n:].copy()

        return events
