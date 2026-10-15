"""Unit tests for LevelMeterWindow UI initialization, tab structure, and tooltips."""

import pytest
from PySide6.QtWidgets import QApplication

from src.audio_capture.service import AudioCaptureService
from src.config.settings import AppConfig
from src.ui.main_window import LevelMeterWindow


@pytest.fixture(scope="session")
def qapp():
    """Ensure a singleton QApplication instance exists for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_tabs_and_structure(qapp) -> None:
    config = AppConfig()
    service = AudioCaptureService(audio_config=config.audio, detector_config=config.detector, spatial_config=config.spatial)
    window = LevelMeterWindow(config=config, capture_service=service)

    # 1. Verify 4 tabs exist without emojis
    tab_titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert tab_titles == ["RADAR HUD", "AUDIO & ROUTING", "TUNING & CALIBRATION", "TELEMETRY LOG"]

    for title in tab_titles:
        # Assert no emojis present in tab titles
        assert all(ord(char) < 128 for char in title)

    # 2. Verify 180° compass dial widget is completely removed
    assert not hasattr(window, "compass_widget")

    # 3. Verify key settings have non-empty, informative tooltips
    assert len(window.hud_mode_combo.toolTip()) > 20
    assert len(window.mouse_compass_cb.toolTip()) > 20
    assert len(window.reset_yaw_btn.toolTip()) > 20
    assert len(window.persistence_spinbox.toolTip()) > 20
    assert len(window.app_combo.toolTip()) > 20
    assert len(window.calibrate_btn.toolTip()) > 20
    assert len(window.require_mouse_cb.toolTip()) > 20
    assert len(window.ratio_spinbox.toolTip()) > 20
    assert len(window.min_db_spinbox.toolTip()) > 20
    assert len(window.cooldown_spinbox.toolTip()) > 20
    assert len(window.enable_front_back_cb.toolTip()) > 20

    # 4. Verify no emojis in tooltips
    assert all(ord(c) < 128 or c in "°–—•" for c in window.hud_mode_combo.toolTip())

    # 5. Verify intrusive health_badge is removed from header bar
    assert not hasattr(window, "health_badge")

    # 6. Verify Game Presets controls exist without emojis
    assert hasattr(window, "preset_combo")
    assert window.preset_combo.count() >= 5
    assert "PUBG: Battlegrounds" in [window.preset_combo.itemText(i) for i in range(window.preset_combo.count())]
    assert hasattr(window, "save_preset_btn")
    assert hasattr(window, "delete_preset_btn")
    assert len(window.save_preset_btn.toolTip()) > 10
    assert len(window.delete_preset_btn.toolTip()) > 10

    # 7. Verify Radar Scale slider exists
    assert hasattr(window, "hud_size_slider")
    assert window.hud_size_slider.value() == 320

    # 8. Verify window starts with enlarged dimensions to avoid compression
    assert window.width() >= 960
    assert window.height() >= 880

    # 9. Verify Radar Style (Tactical Rays vs Sector Zones) combobox without emojis
    assert hasattr(window, "radar_type_combo")
    assert window.radar_type_combo.count() == 2
    assert all(ord(c) < 128 or c in "°–—•" for c in window.radar_type_combo.toolTip())
    for i in range(window.radar_type_combo.count()):
        text = window.radar_type_combo.itemText(i)
        assert all(ord(c) < 128 or c in "°–—•" for c in text)

    # Test toggling radar style updates the overlay
    window.radar_type_combo.setCurrentIndex(1)
    assert window.radar_overlay.radar_type == "zones"
    window.radar_type_combo.setCurrentIndex(0)
    assert window.radar_overlay.radar_type == "rays"

    # 10. Verify configuration tabs are wrapped in QScrollArea to prevent vertical squishing
    from PySide6.QtWidgets import QScrollArea
    assert isinstance(window.tabs.widget(0), QScrollArea)
    assert isinstance(window.tabs.widget(1), QScrollArea)
    assert isinstance(window.tabs.widget(2), QScrollArea)

    # 11. Verify Sound Mini-Circles checkbox exists without emojis and functions properly
    assert hasattr(window, "show_circles_cb")
    assert window.show_circles_cb.isChecked() is True
    assert all(ord(c) < 128 or c in "°–—•" for c in window.show_circles_cb.toolTip())
    assert all(ord(c) < 128 or c in "°–—•" for c in window.show_circles_cb.text())

    # Toggling checkbox updates overlay and config
    window.show_circles_cb.setChecked(False)
    assert window.radar_overlay.show_sound_circles is False
    assert window.config.show_sound_circles is False

    window.show_circles_cb.setChecked(True)
    assert window.radar_overlay.show_sound_circles is True
    assert window.config.show_sound_circles is True

    # 12. Verify Sound Numbers checkbox exists without emojis and functions properly
    assert hasattr(window, "show_numbers_cb")
    assert window.show_numbers_cb.isChecked() is True
    assert all(ord(c) < 128 or c in "°–—•" for c in window.show_numbers_cb.toolTip())
    assert all(ord(c) < 128 or c in "°–—•" for c in window.show_numbers_cb.text())

    # Toggling checkbox updates overlay and config
    window.show_numbers_cb.setChecked(False)
    assert window.radar_overlay.show_sound_numbers is False
    assert window.config.show_sound_numbers is False

    window.show_numbers_cb.setChecked(True)
    assert window.radar_overlay.show_sound_numbers is True
    assert window.config.show_sound_numbers is True

    window.close()

