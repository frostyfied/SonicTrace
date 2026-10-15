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

    def reset(self) -> None:
        """Reset internal classifier state."""
        pass

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
            spatial_config: SpatialConfig with self-sound thresholds.

        Returns:
            Tuple of (SoundType, AcousticFeatures).
        """
        features = extract_acoustic_features(
            left_samples, right_samples, sample_rate=self.sample_rate
        )

        # 1. Player origin self-sound (weapon blast or point-blank shot)
        if direction.is_self_sound:
            return SoundType.SELF, features

        # 2. External directional sound event (gunshot, footstep, reload, vehicle, etc.)
        return SoundType.SOUND, features
