"""Data models and enumeration types for sound event classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SoundType(str, Enum):
    """Semantic category of detected sound event."""

    SOUND = "sound"
    SELF = "self"

    # Backward compatibility aliases
    GENERIC = "sound"
    GUNSHOT = "sound"
    FOOTSTEP = "sound"
    SELF_WEAPON = "self"
    SELF_STEP = "self"


@dataclass(slots=True)
class AcousticFeatures:
    """Acoustic feature set extracted from a transient subframe."""

    attack_time_ms: float
    crest_factor_db: float
    spectral_centroid_hz: float
    high_low_ratio: float
    dominant_band: str
    rms_db: float
    peak_db: float
