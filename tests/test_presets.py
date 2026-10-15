"""Unit tests for competitive game presets and custom user profile management."""

from __future__ import annotations

from src.config.presets import (
    BUILTIN_PRESETS,
    GamePreset,
    get_all_presets,
    get_preset_by_name,
)


def test_builtin_presets_structure_and_completeness() -> None:
    """Verify standard built-in profiles are configured with valid competitive settings."""
    assert "Default (Balanced)" in BUILTIN_PRESETS
    assert "PUBG: Battlegrounds" in BUILTIN_PRESETS
    assert "Valorant" in BUILTIN_PRESETS
    assert "Counter-Strike 2" in BUILTIN_PRESETS
    assert "Apex Legends" in BUILTIN_PRESETS

    for name, preset in BUILTIN_PRESETS.items():
        assert preset.name == name
        assert len(preset.description) > 10
        assert preset.trigger_ratio > 1.0
        assert preset.min_trigger_db < -10.0
        assert preset.cooldown_ms >= 20
        assert 0.0 < preset.min_confidence <= 1.0
        assert preset.spatial_mode in ("stereo_180", "hrtf_360")
        assert preset.cluster_lifetime_s >= 2.0


def test_pubg_preset_specifics() -> None:
    """PUBG preset should use 180 forward dome and LMB physical gating."""
    pubg = BUILTIN_PRESETS["PUBG: Battlegrounds"]
    assert pubg.spatial_mode == "stereo_180"
    assert pubg.require_mouse_for_self is True
    assert pubg.trigger_ratio == 3.2
    assert pubg.bilateral_self_threshold_db == -4.0


def test_valorant_preset_specifics() -> None:
    """Valorant preset should use 360 HRTF surround with pinna spectral cues."""
    val = BUILTIN_PRESETS["Valorant"]
    assert val.spatial_mode == "hrtf_360"
    assert val.enable_front_back is True
    assert val.trigger_ratio == 2.8


def test_custom_user_preset_creation_and_retrieval() -> None:
    """Creating and adding user custom presets should integrate seamlessly."""
    custom = GamePreset(
        name="Custom DMR Setup",
        description="Low threshold sniper tuning.",
        trigger_ratio=2.5,
        min_trigger_db=-52.0,
        cooldown_ms=50,
        spatial_mode="stereo_180",
    )
    user_dict = {custom.name: custom.to_dict()}

    all_presets = get_all_presets(user_dict)
    assert "Custom DMR Setup" in all_presets
    assert all_presets["Custom DMR Setup"].trigger_ratio == 2.5

    retrieved = get_preset_by_name("Custom DMR Setup", user_dict)
    assert retrieved.name == "Custom DMR Setup"
    assert retrieved.min_trigger_db == -52.0


def test_get_preset_fallback_on_unknown_name() -> None:
    """Unknown preset names should safely fall back to 'Default (Balanced)'."""
    preset = get_preset_by_name("NonExistentGameProfile123")
    assert preset.name == "Default (Balanced)"
