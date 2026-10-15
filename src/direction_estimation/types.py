"""Data types for spatial direction estimation."""

from __future__ import annotations

from dataclasses import dataclass


from enum import Enum


class SpatialMode(str, Enum):
    """Acoustic spatialization model mode."""

    HRTF_360 = "hrtf_360"      # 360° Polar Radar with Pinna Spectral Front/Back Detection
    STEREO_180 = "stereo_180"  # 180° Lateral/Forward Radar (for games without HRTF)


@dataclass(slots=True)
class DirectionEstimate:
    """Estimated spatial acoustic direction, interaural cues, and confidence."""

    azimuth_deg: float      # -90.0° (Hard Left) to 0.0° (Ahead / Front) to +90.0° (Hard Right)
    itd_ms: float           # Interaural Time Difference in milliseconds
    ild_db: float           # Interaural Level Difference in decibels
    confidence: float       # 0.0 to 1.0 confidence score
    is_self_sound: bool     # True if flagged as player's own point-blank sound
    is_uncertain: bool      # True if confidence is below threshold
    dominant_band: str      # "low" (80-1.2k), "mid" (1.2k-4k), or "high" (4k-16k)
    azimuth_360_deg: float = 0.0  # -180.0° to +180.0° full polar bearing (0° Ahead, ±180° Behind)
    is_rear: bool = False         # True if spectral pinna cues indicate rear hemisphere
    front_back_ratio: float = 1.0 # High-to-mid frequency ratio for HRTF analysis

    def __post_init__(self) -> None:
        if self.azimuth_360_deg == 0.0 and self.azimuth_deg != 0.0:
            if not self.is_rear:
                object.__setattr__(self, "azimuth_360_deg", self.azimuth_deg)
            else:
                if self.azimuth_deg > 0:
                    object.__setattr__(self, "azimuth_360_deg", 180.0 - self.azimuth_deg)
                elif self.azimuth_deg < 0:
                    object.__setattr__(self, "azimuth_360_deg", -180.0 - self.azimuth_deg)
                else:
                    object.__setattr__(self, "azimuth_360_deg", 180.0)


