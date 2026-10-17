"""Data structures and types for transient sound events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.direction_estimation.types import DirectionEstimate
from src.event_classification.types import AcousticFeatures, SoundType


@dataclass(slots=True)
class SoundEvent:
    """Represents a detected candidate transient sound event (e.g., gunshot, footstep)."""

    event_id: str
    timestamp: float
    peak_db: float
    energy_ratio: float
    channel_bias: float  # -1.0 (Hard Left) to 0.0 (Ahead / Front) to +1.0 (Hard Right)
    duration_ms: float
    direction: Optional[DirectionEstimate] = None
    sound_type: SoundType = SoundType.GENERIC
    features: Optional[AcousticFeatures] = None
    left_peak_db: Optional[float] = None
    right_peak_db: Optional[float] = None
