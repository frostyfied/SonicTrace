"""Unit tests for configuration persistence, auto-save serialization, and overlay window geometry."""

from __future__ import annotations

import json
from pathlib import Path

from src.config.presets import GamePreset
from src.config.settings import AppConfig


def test_app_config_presets_and_overlay_geometry_serialization(tmp_path: Path) -> None:
    """Verify user presets, active preset, and overlay geometry persist across save and load."""
    config_file = tmp_path / "config.json"

    custom_preset = GamePreset(
        name="Tactical Custom",
        description="User custom tuning for sniper rifles.",
        trigger_ratio=2.6,
        min_trigger_db=-49.0,
        cooldown_ms=55,
        spatial_mode="stereo_180",
    )

    original = AppConfig()
    original.active_preset = "Tactical Custom"
    original.user_presets = {"Tactical Custom": custom_preset.to_dict()}
    original.overlay_x = 450
    original.overlay_y = 300
    original.overlay_diameter = 380
    original.overlay_opacity = 0.90
    original.overlay_locked = True
    original.overlay_visible = True
    original.show_sound_numbers = False

    original.save_to_file(config_file)
    assert config_file.exists()

    loaded = AppConfig.load_from_file(config_file)
    assert loaded.active_preset == "Tactical Custom"
    assert "Tactical Custom" in loaded.user_presets
    assert loaded.user_presets["Tactical Custom"]["trigger_ratio"] == 2.6
    assert loaded.overlay_x == 450
    assert loaded.overlay_y == 300
    assert loaded.overlay_diameter == 380
    assert loaded.overlay_opacity == 0.90
    assert loaded.overlay_locked is True
    assert loaded.overlay_visible is True
    assert loaded.show_sound_numbers is False


def test_app_config_backward_compatibility_with_older_json(tmp_path: Path) -> None:
    """Ensure older config.json without presets or overlay fields loads with safe defaults."""
    old_file = tmp_path / "old_config.json"
    old_data = {
        "audio": {"sample_rate": 48000, "channels": 2},
        "detector": {"threshold_ratio": 3.5},
    }
    with open(old_file, "w", encoding="utf-8") as f:
        json.dump(old_data, f)

    loaded = AppConfig.load_from_file(old_file)
    assert loaded.user_presets == {}
    assert loaded.active_preset == "Default (Balanced)"
    assert loaded.overlay_x is None
    assert loaded.overlay_y is None
    assert loaded.overlay_diameter == 320
    assert loaded.overlay_opacity == 0.20
    assert loaded.show_sound_numbers is True
