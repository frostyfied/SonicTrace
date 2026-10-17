"""Classification engine distinguishing external sounds vs player self-actions."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from src.config.settings import SpatialConfig
from src.direction_estimation.types import DirectionEstimate
from src.event_classification.features import extract_acoustic_features
from src.event_classification.types import AcousticFeatures, SoundType

logger = logging.getLogger(__name__)


class SoundClassifier:
    """Classifies detected transient sound events into external sounds vs self origin sounds."""

    def __init__(self, sample_rate: int = 48000) -> None:
        self.sample_rate = sample_rate
        self._last_step_candidate_time: float = -1.0

    def reset(self) -> None:
        """Reset internal classifier state."""
        self._last_step_candidate_time = -1.0

    def classify(
        self,
        left_samples: np.ndarray,
        right_samples: np.ndarray,
        direction: DirectionEstimate,
        peak_db: float,
        timestamp: float,
        spatial_config: SpatialConfig,
    ) -> tuple[SoundType, AcousticFeatures]:
        """Classify transient sound into SoundType (SELF or SOUND) with acoustic feature extraction.

        Args:
            left_samples: Left channel transient buffer.
            right_samples: Right channel transient buffer.
            direction: DirectionEstimate from DirectionEstimator.
            peak_db: Overall peak dBFS level.
            timestamp: Event timestamp in seconds.
            spatial_config: SpatialConfig with self-sound and self-footstep thresholds.

        Returns:
            Tuple of (SoundType, AcousticFeatures).
        """
        features = extract_acoustic_features(
            left_samples, right_samples, sample_rate=self.sample_rate
        )

        # 1. Player origin self-sound (weapon blast or point-blank shot)
        if direction.is_self_sound:
            return SoundType.SELF, features

        # 2. Bilateral self-footstep suppression (centered foley matching locomotion cadence)
        if getattr(spatial_config, "suppress_self_footsteps", False):
            in_db_window = (
                spatial_config.self_footstep_min_db
                <= peak_db
                <= spatial_config.self_footstep_max_db
            )
            is_centered = (
                abs(direction.ild_db) <= spatial_config.self_footstep_max_ild_db
                and abs(direction.azimuth_deg) <= spatial_config.self_footstep_max_angle_deg
                and abs(direction.itd_ms) <= 0.08
            )
            is_step_profile = (
                features.spectral_centroid_hz < 2200.0
                and features.attack_time_ms >= 5.0
            )
            if in_db_window and is_centered and is_step_profile:
                dt = timestamp - self._last_step_candidate_time
                self._last_step_candidate_time = timestamp
                if 0.20 <= dt <= 0.68:
                    return SoundType.SELF, features

        # 3. External directional sound event (gunshot, footstep, reload, vehicle, etc.)
        return SoundType.SOUND, features
