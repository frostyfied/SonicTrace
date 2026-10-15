"""Unit tests for configuration models and serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.settings import AppConfig, AudioConfig, DetectorConfig, MeterConfig, SpatialConfig


def test_audio_config_defaults() -> None:
    config = AudioConfig()
    assert config.sample_rate == 48000
    assert config.block_size == 2048
    assert config.channels == 2
    assert config.silence_threshold_db == -50.0
    assert config.reconnect_interval_s == 2.0
    assert config.device_name is None


def test_audio_config_validation() -> None:
    with pytest.raises(ValueError, match="Sample rate must be positive"):
        AudioConfig(sample_rate=0)

    with pytest.raises(ValueError, match="Block size must be positive"):
        AudioConfig(block_size=-100)

    with pytest.raises(ValueError, match="Channels must be 1 or 2"):
        AudioConfig(channels=6)

    with pytest.raises(ValueError, match="Reconnect interval must be positive"):
        AudioConfig(reconnect_interval_s=0)


def test_meter_config_validation() -> None:
    with pytest.raises(ValueError, match="min_db .* must be less than max_db"):
        MeterConfig(min_db=0.0, max_db=-10.0)

    with pytest.raises(ValueError, match="decay_rate_db_per_sec must be positive"):
        MeterConfig(decay_rate_db_per_sec=-5.0)

    with pytest.raises(ValueError, match="peak_hold_ms must be non-negative"):
        MeterConfig(peak_hold_ms=-100)


def test_app_config_serialization_roundtrip(tmp_path: Path) -> None:
    filepath = tmp_path / "test_config.json"
    original = AppConfig(
        audio=AudioConfig(sample_rate=44100, block_size=1024, device_name="Test Headphones"),
        meter=MeterConfig(min_db=-72.0, max_db=-3.0, decay_rate_db_per_sec=30.0),
        spatial=SpatialConfig(self_sound_threshold_db=-2.0, min_confidence=0.50),
    )

    original.save_to_file(filepath)
    assert filepath.exists()

    loaded = AppConfig.load_from_file(filepath)
    assert loaded.audio.sample_rate == 44100
    assert loaded.audio.block_size == 1024
    assert loaded.audio.device_name == "Test Headphones"
    assert loaded.meter.min_db == -72.0
    assert loaded.meter.max_db == -3.0
    assert loaded.meter.decay_rate_db_per_sec == 30.0
    assert loaded.spatial.self_sound_threshold_db == -2.0
    assert loaded.spatial.min_confidence == 0.50


def test_app_config_fallback_on_corrupt_file(tmp_path: Path) -> None:
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{ this is not valid json : [[", encoding="utf-8")

    loaded = AppConfig.load_from_file(corrupt_file)
    # Should safely return defaults rather than raising
    assert loaded.audio.sample_rate == 48000
    assert loaded.meter.min_db == -60.0


def test_app_config_fallback_on_non_dict_json(tmp_path: Path) -> None:
    array_file = tmp_path / "array.json"
    array_file.write_text("[1, 2, 3]", encoding="utf-8")

    loaded = AppConfig.load_from_file(array_file)
    assert loaded.audio.sample_rate == 48000


def test_app_config_load_non_existent_file(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.json"
    loaded = AppConfig.load_from_file(missing_file)
    assert loaded.audio.sample_rate == 48000
