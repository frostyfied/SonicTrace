"""Data types and data structures for audio level metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChannelLevel:
    """Audio level measurements for a single channel."""

    rms_linear: float
    peak_linear: float
    rms_db: float
    peak_db: float
    peak_held_db: float


@dataclass(slots=True)
class LevelMetrics:
    """Stereo level metrics, silence status, and audio health indications."""

    timestamp: float
    left: ChannelLevel
    right: ChannelLevel
    is_silent: bool
    is_mono: bool = False
    is_clipping: bool = False
    channel_correlation: float = 1.0

