"""Application configuration models and serialization.

Provides strongly-typed dataclasses for audio capture and level metering settings,
with JSON persistence and graceful fallback on malformed or missing configs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioConfig:
    """Settings controlling WASAPI loopback audio capture."""

    sample_rate: int = 48000
    block_size: int = 2048
    channels: int = 2
    silence_threshold_db: float = -50.0
    reconnect_interval_s: float = 2.0
    device_name: Optional[str] = None
    target_process_name: Optional[str] = None
    target_pid: Optional[int] = None

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"Sample rate must be positive, got {self.sample_rate}")
        if self.block_size <= 0:
            raise ValueError(f"Block size must be positive, got {self.block_size}")
        if self.channels not in (1, 2):
            raise ValueError(f"Channels must be 1 or 2, got {self.channels}")
        if self.reconnect_interval_s <= 0:
            raise ValueError(
                f"Reconnect interval must be positive, got {self.reconnect_interval_s}"
            )


@dataclass(slots=True)
class MeterConfig:
    """Settings controlling live audio level metering ballistics and display range."""

    min_db: float = -60.0
    max_db: float = 0.0
    decay_rate_db_per_sec: float = 40.0
    peak_hold_ms: int = 600

    def __post_init__(self) -> None:
        if self.min_db >= self.max_db:
            raise ValueError(
                f"min_db ({self.min_db}) must be less than max_db ({self.max_db})"
            )
        if self.decay_rate_db_per_sec <= 0:
            raise ValueError(
                f"decay_rate_db_per_sec must be positive, got {self.decay_rate_db_per_sec}"
            )
        if self.peak_hold_ms < 0:
            raise ValueError(
                f"peak_hold_ms must be non-negative, got {self.peak_hold_ms}"
            )


@dataclass(slots=True)
class DetectorConfig:
    """Settings controlling transient sound event detection (STA/LTA)."""

    sta_window_ms: float = 20.0
    lta_window_ms: float = 1200.0
    threshold_ratio: float = 2.4
    min_trigger_db: float = -52.0
    cooldown_ms: float = 45.0
    lta_freeze_ms: float = 600.0
    high_pass_hz: float = 0.0

    def __post_init__(self) -> None:
        if self.sta_window_ms <= 0:
            raise ValueError(f"sta_window_ms must be positive, got {self.sta_window_ms}")
        if self.lta_window_ms <= self.sta_window_ms:
            raise ValueError(
                f"lta_window_ms ({self.lta_window_ms}) must be greater than sta_window_ms ({self.sta_window_ms})"
            )
        if self.threshold_ratio <= 1.0:
            raise ValueError(f"threshold_ratio must be > 1.0, got {self.threshold_ratio}")
        if self.cooldown_ms < 0:
            raise ValueError(f"cooldown_ms must be non-negative, got {self.cooldown_ms}")
        if self.lta_freeze_ms < 0:
            raise ValueError(f"lta_freeze_ms must be non-negative, got {self.lta_freeze_ms}")
        if self.high_pass_hz < 0:
            raise ValueError(f"high_pass_hz must be non-negative, got {self.high_pass_hz}")


@dataclass(slots=True)
class SpatialConfig:
    """Settings controlling spatial direction estimation (ITD, ILD, self-sound gating)."""

    self_sound_threshold_db: float = -3.5
    bilateral_self_threshold_db: float = -4.0
    self_echo_lockout_ms: float = 180.0
    max_itd_ms: float = 0.70
    min_confidence: float = 0.35
    itd_weight: float = 0.60
    ild_weight: float = 0.40
    suppress_self_sounds: bool = False
    suppress_self_footsteps: bool = True
    self_footstep_max_ild_db: float = 1.0
    self_footstep_max_angle_deg: float = 6.0
    self_footstep_min_db: float = -46.0
    self_footstep_max_db: float = -20.0
    spatial_mode: str = "stereo_180"  # "stereo_180" (recommended for stereo gaming) or "hrtf_360" (polar surround)
    enable_front_back: bool = False   # Disabled by default: prevents false rear flipping on gunfire
    rear_ratio_threshold: float = 0.08
    cluster_angular_tolerance_deg: float = 20.0
    cluster_lifetime_s: float = 8.0  # Persistent ray window in seconds
    enable_mouse_compass: bool = False  # Direct Screen-Locked mode by default (zero mouse drift)
    mouse_yaw_sensitivity: float = 0.05  # Degrees per mouse hardware count
    on_target_tolerance_deg: float = 6.0  # Angular lock-on threshold around 0° Ahead
    require_mouse_for_self: bool = True  # Requires physical mouse click (LMB) to classify as player weapon self-sound
    enable_self_sound_gating: bool = True  # If False, disables self-sound detection completely (all sounds external)

    def __post_init__(self) -> None:
        if self.max_itd_ms <= 0:
            raise ValueError(f"max_itd_ms must be positive, got {self.max_itd_ms}")
        if not (0.0 <= self.min_confidence <= 1.0):
            raise ValueError(f"min_confidence must be in [0.0, 1.0], got {self.min_confidence}")
        if self.itd_weight < 0 or self.ild_weight < 0:
            raise ValueError("Weights must be non-negative")
        if self.self_echo_lockout_ms < 0:
            raise ValueError(f"self_echo_lockout_ms must be non-negative, got {self.self_echo_lockout_ms}")
        if self.self_footstep_max_ild_db < 0:
            raise ValueError("self_footstep_max_ild_db must be non-negative")
        if self.self_footstep_max_angle_deg < 0:
            raise ValueError("self_footstep_max_angle_deg must be non-negative")
        if self.rear_ratio_threshold <= 0:
            raise ValueError("rear_ratio_threshold must be positive")
        if self.cluster_angular_tolerance_deg <= 0:
            raise ValueError("cluster_angular_tolerance_deg must be positive")
        if self.cluster_lifetime_s <= 0:
            raise ValueError("cluster_lifetime_s must be positive")
        if self.mouse_yaw_sensitivity <= 0:
            raise ValueError("mouse_yaw_sensitivity must be positive")
        if self.on_target_tolerance_deg <= 0:
            raise ValueError("on_target_tolerance_deg must be positive")



@dataclass(slots=True)
class AppConfig:
    """Top-level application configuration."""

    audio: AudioConfig = field(default_factory=AudioConfig)
    meter: MeterConfig = field(default_factory=MeterConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    spatial: SpatialConfig = field(default_factory=SpatialConfig)

    # User presets & game profiles
    user_presets: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_preset: str = "Default (Balanced)"

    # Overlay UI window geometry & state persistence
    overlay_x: Optional[int] = None
    overlay_y: Optional[int] = None
    overlay_diameter: int = 320
    overlay_opacity: float = 0.85
    overlay_locked: bool = True
    overlay_visible: bool = True
    overlay_type: str = "rays"  # "rays" (lines) or "zones" (curved threat arcs)
    show_sound_circles: bool = True  # If False, hides mini-circle sound pips on radar
    show_sound_numbers: bool = True  # If False, hides numeric counters/metrics on radar

    # Main window dimensions
    window_width: int = 960
    window_height: int = 880

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Create AppConfig from dictionary with safe defaults for missing keys."""
        audio_data = data.get("audio", {})
        meter_data = data.get("meter", {})
        detector_data = data.get("detector", {})
        spatial_data = data.get("spatial", {})

        audio = AudioConfig(**{k: v for k, v in audio_data.items() if hasattr(AudioConfig, k)})
        meter = MeterConfig(**{k: v for k, v in meter_data.items() if hasattr(MeterConfig, k)})
        detector = DetectorConfig(**{k: v for k, v in detector_data.items() if hasattr(DetectorConfig, k)})
        spatial = SpatialConfig(**{k: v for k, v in spatial_data.items() if hasattr(SpatialConfig, k)})

        return cls(
            audio=audio,
            meter=meter,
            detector=detector,
            spatial=spatial,
            user_presets=data.get("user_presets", {}),
            active_preset=data.get("active_preset", "Default (Balanced)"),
            overlay_x=data.get("overlay_x"),
            overlay_y=data.get("overlay_y"),
            overlay_diameter=data.get("overlay_diameter", 320),
            overlay_opacity=data.get("overlay_opacity", 0.85),
            overlay_locked=data.get("overlay_locked", True),
            overlay_visible=data.get("overlay_visible", True),
            overlay_type=data.get("overlay_type", "rays"),
            show_sound_circles=data.get("show_sound_circles", True),
            show_sound_numbers=data.get("show_sound_numbers", True),
            window_width=data.get("window_width", 960),
            window_height=data.get("window_height", 880),
        )



    def save_to_file(self, file_path: Path | str) -> None:
        """Serialize configuration to a JSON file."""
        target_path = Path(file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Saved configuration to %s", target_path)

    @classmethod
    def load_from_file(cls, file_path: Path | str) -> AppConfig:
        """Load configuration from JSON file.

        Falls back to default configuration if file is missing, unreadable, or invalid.
        """
        target_path = Path(file_path)
        if not target_path.exists():
            logger.debug("Config file %s not found. Using defaults.", target_path)
            return cls()

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(
                    "Config file %s did not contain a JSON object. Using defaults.",
                    target_path,
                )
                return cls()
            return cls.from_dict(data)
        except Exception as exc:
            logger.warning(
                "Failed to parse config file %s (%s). Falling back to defaults.",
                target_path,
                exc,
            )
            return cls()
