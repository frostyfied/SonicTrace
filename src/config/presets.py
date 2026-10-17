"""Competitive game presets and tuning profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(slots=True)
class GamePreset:
    """A collection of DSP tuning parameters optimized for a specific game."""

    name: str
    description: str
    trigger_ratio: float = 3.5
    min_trigger_db: float = -45.0
    cooldown_ms: int = 70
    min_confidence: float = 0.35
    spatial_mode: str = "stereo_180"
    bilateral_self_threshold_db: float = -4.0
    self_echo_lockout_ms: float = 180.0
    require_mouse_for_self: bool = True
    enable_front_back: bool = False
    cluster_lifetime_s: float = 8.0

    def to_dict(self) -> dict[str, Any]:
        """Convert preset to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GamePreset:
        """Create a GamePreset from dictionary with defaults for missing keys."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


BUILTIN_PRESETS: dict[str, GamePreset] = {
    "Default (Balanced)": GamePreset(
        name="Default (Balanced)",
        description="Standard balanced tuning for general shooters and tactical games.",
        trigger_ratio=3.5,
        min_trigger_db=-45.0,
        cooldown_ms=70,
        min_confidence=0.35,
        spatial_mode="hrtf_360",
        bilateral_self_threshold_db=-4.0,
        self_echo_lockout_ms=180.0,
        require_mouse_for_self=True,
        enable_front_back=False,
        cluster_lifetime_s=2.0,
    ),
    "PUBG: Battlegrounds": GamePreset(
        name="PUBG: Battlegrounds",
        description="Optimized for PUBG gunshots with 180° Forward Dome and snap detection.",
        trigger_ratio=3.2,
        min_trigger_db=-45.0,
        cooldown_ms=70,
        min_confidence=0.35,
        spatial_mode="stereo_180",
        bilateral_self_threshold_db=-4.0,
        self_echo_lockout_ms=180.0,
        require_mouse_for_self=True,
        enable_front_back=False,
        cluster_lifetime_s=8.0,
    ),
    "Valorant": GamePreset(
        name="Valorant",
        description="Tuned for Valorant 3D HRTF engine with discrete bullet crack sensitivity.",
        trigger_ratio=2.8,
        min_trigger_db=-48.0,
        cooldown_ms=60,
        min_confidence=0.30,
        spatial_mode="hrtf_360",
        bilateral_self_threshold_db=-6.0,
        self_echo_lockout_ms=150.0,
        require_mouse_for_self=True,
        enable_front_back=True,
        cluster_lifetime_s=6.0,
    ),
    "Counter-Strike 2": GamePreset(
        name="Counter-Strike 2",
        description="High-threshold punchy audio tuning for CS2 weapon discharges and footsteps.",
        trigger_ratio=3.4,
        min_trigger_db=-42.0,
        cooldown_ms=75,
        min_confidence=0.40,
        spatial_mode="stereo_180",
        bilateral_self_threshold_db=-3.0,
        self_echo_lockout_ms=160.0,
        require_mouse_for_self=True,
        enable_front_back=False,
        cluster_lifetime_s=7.0,
    ),
    "Apex Legends": GamePreset(
        name="Apex Legends",
        description="Rapid retrigger debounce for high fire-rate weapons with 180° forward dome.",
        trigger_ratio=3.0,
        min_trigger_db=-46.0,
        cooldown_ms=80,
        min_confidence=0.35,
        spatial_mode="stereo_180",
        bilateral_self_threshold_db=-5.0,
        self_echo_lockout_ms=180.0,
        require_mouse_for_self=True,
        enable_front_back=False,
        cluster_lifetime_s=8.0,
    ),
}


def get_all_presets(user_presets: dict[str, dict[str, Any]] | None = None) -> dict[str, GamePreset]:
    """Retrieve combined dictionary of built-in presets and user-created custom presets."""
    presets = dict(BUILTIN_PRESETS)
    if user_presets:
        for name, data in user_presets.items():
            if isinstance(data, dict):
                presets[name] = GamePreset.from_dict(data)
    return presets


def get_preset_by_name(name: str, user_presets: dict[str, dict[str, Any]] | None = None) -> GamePreset:
    """Find preset by name, falling back to 'Default (Balanced)' if not found."""
    all_presets = get_all_presets(user_presets)
    return all_presets.get(name, BUILTIN_PRESETS["Default (Balanced)"])
