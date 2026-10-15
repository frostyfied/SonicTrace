"""Unit tests for the transparent circular radar overlay HUD."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.direction_estimation.types import DirectionEstimate
from src.event_detection.types import SoundEvent
from src.ui.radar_overlay import RadarOverlayWindow


@pytest.fixture(scope="session")
def qapp():
    """Ensure a singleton QApplication instance exists for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_radar_overlay_initialization(qapp) -> None:
    hud = RadarOverlayWindow()
    assert hud.is_locked
    assert hud.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert hud.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    hud.close()


def test_radar_overlay_lock_toggle(qapp) -> None:
    hud = RadarOverlayWindow()
    hud.set_locked(False)
    assert not hud.is_locked
    assert not hud.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    hud.set_locked(True)
    assert hud.is_locked
    assert hud.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    hud.close()


def test_radar_overlay_add_sound_event(qapp) -> None:
    hud = RadarOverlayWindow()

    # Directional sound event at -45 degrees
    direction = DirectionEstimate(
        azimuth_deg=-45.0,
        itd_ms=-0.35,
        ild_db=-6.0,
        confidence=0.85,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="high",
    )
    event = SoundEvent(
        event_id="test_1",
        timestamp=100.0,
        peak_db=-12.0,
        energy_ratio=5.0,
        channel_bias=-0.6,
        duration_ms=10.7,
        direction=direction,
    )

    hud.add_sound_event(event)
    assert len(hud._pings) == 1
    assert hud._pings[0].azimuth_deg == -45.0
    assert not hud._pings[0].is_self_sound
    hud.close()


def test_radar_overlay_self_sound_toggle(qapp) -> None:
    hud = RadarOverlayWindow()
    hud.set_show_self_sounds(False)

    self_direction = DirectionEstimate(
        azimuth_deg=0.0,
        itd_ms=0.0,
        ild_db=0.0,
        confidence=1.0,
        is_self_sound=True,
        is_uncertain=False,
        dominant_band="low",
    )
    event = SoundEvent(
        event_id="test_self",
        timestamp=101.0,
        peak_db=-1.0,
        energy_ratio=10.0,
        channel_bias=0.0,
        duration_ms=10.7,
        direction=self_direction,
    )

    hud.add_sound_event(event)
    # When _show_self_sounds is False, self-sound should be ignored
    assert len(hud._pings) == 0

    hud.set_show_self_sounds(True)
    hud.add_sound_event(event)
    assert len(hud._pings) == 1
    assert hud._pings[0].is_self_sound
    hud.close()


def test_radar_overlay_sound_type_pings(qapp) -> None:
    from src.event_classification.types import SoundType
    hud = RadarOverlayWindow()

    sound_event = SoundEvent(
        event_id="snd_1",
        timestamp=200.0,
        peak_db=-14.0,
        energy_ratio=8.0,
        channel_bias=-0.5,
        duration_ms=10.7,
        direction=DirectionEstimate(
            azimuth_deg=-40.0,
            itd_ms=-0.3,
            ild_db=-5.0,
            confidence=0.9,
            is_self_sound=False,
            is_uncertain=False,
            dominant_band="high",
        ),
        sound_type=SoundType.SOUND,
    )
    hud.add_sound_event(sound_event)
    assert len(hud._pings) == 1
    assert hud._pings[0].sound_type == SoundType.SOUND
    assert hud._latest_sound_type == SoundType.SOUND

    self_event = SoundEvent(
        event_id="self_1",
        timestamp=201.0,
        peak_db=-2.0,
        energy_ratio=15.0,
        channel_bias=0.0,
        duration_ms=10.7,
        direction=DirectionEstimate(
            azimuth_deg=0.0,
            itd_ms=0.0,
            ild_db=0.1,
            confidence=1.0,
            is_self_sound=True,
            is_uncertain=False,
            dominant_band="low",
        ),
        sound_type=SoundType.SELF,
    )
    hud.add_sound_event(self_event)
    assert len(hud._pings) == 2
    assert hud._pings[1].sound_type == SoundType.SELF
    assert hud._pings[1].is_self_sound
    hud.close()


def test_radar_overlay_360_threat_tracking(qapp) -> None:
    """Validate that incoming enemy sounds populate threat clusters on the HUD."""
    hud = RadarOverlayWindow()
    hud.set_spatial_mode("hrtf_360")

    # Threat 1: Behind-Left (-135°)
    dir1 = DirectionEstimate(
        azimuth_deg=-45.0,
        itd_ms=-0.35,
        ild_db=-6.0,
        confidence=0.90,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="high",
        azimuth_360_deg=-135.0,
        is_rear=True,
    )
    evt1 = SoundEvent(
        event_id="t1",
        timestamp=10.0,
        peak_db=-18.0,
        energy_ratio=4.0,
        channel_bias=-0.5,
        duration_ms=10.0,
        direction=dir1,
    )
    hud.add_sound_event(evt1)

    clusters = hud.threat_tracker.get_active_clusters(now=10.0)
    assert len(clusters) == 1
    assert clusters[0].azimuth_deg == -135.0
    assert clusters[0].shot_count == 1
    assert clusters[0].is_rear is True

    # Threat 2: Front-Right (+45°)
    dir2 = DirectionEstimate(
        azimuth_deg=45.0,
        itd_ms=0.35,
        ild_db=6.0,
        confidence=0.85,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="mid",
        azimuth_360_deg=45.0,
        is_rear=False,
    )
    evt2 = SoundEvent(
        event_id="t2",
        timestamp=10.2,
        peak_db=-15.0,
        energy_ratio=5.0,
        channel_bias=0.5,
        duration_ms=10.0,
        direction=dir2,
    )
    hud.add_sound_event(evt2)

    clusters = hud.threat_tracker.get_active_clusters(now=10.3)
    assert len(clusters) == 2
    hud.close()


def test_radar_overlay_spatial_mode_switching(qapp) -> None:
    """Validate toggling between HRTF 360 and Stereo 180 modes on HUD."""
    hud = RadarOverlayWindow()
    assert hud.spatial_mode == "stereo_180"

    hud.set_spatial_mode("hrtf_360")
    assert hud.spatial_mode == "hrtf_360"

    hud.set_spatial_mode("stereo_180")
    assert hud.spatial_mode == "stereo_180"

    # In stereo mode, an event with is_rear=True displays lateral azimuth
    dir_rear = DirectionEstimate(
        azimuth_deg=-60.0,
        itd_ms=-0.4,
        ild_db=-7.0,
        confidence=0.8,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="mid",
        azimuth_360_deg=-120.0,
        is_rear=True,
    )
    evt = SoundEvent(
        event_id="s1",
        timestamp=20.0,
        peak_db=-20.0,
        energy_ratio=3.0,
        channel_bias=-0.6,
        duration_ms=10.0,
        direction=dir_rear,
    )
    hud.add_sound_event(evt)
    assert len(hud._pings) == 1
    # Uses lateral bearing in stereo mode
    assert hud._pings[0].azimuth_deg == -60.0
    hud.close()


def test_radar_overlay_newest_sound_prominence(qapp) -> None:
    """Validate that newest sound is tracked and painted cleanly without target lock."""
    hud = RadarOverlayWindow()
    hud.set_spatial_mode("hrtf_360")

    # Threat 1: Older shot at -60° (heard at t=10.0)
    d1 = DirectionEstimate(
        azimuth_deg=-60.0, itd_ms=-0.4, ild_db=-6.0, confidence=0.9,
        is_self_sound=False, is_uncertain=False, dominant_band="mid",
        azimuth_360_deg=-60.0, is_rear=False,
    )
    e1 = SoundEvent(
        event_id="e1", timestamp=10.0, peak_db=-22.0, energy_ratio=4.0,
        channel_bias=-0.5, duration_ms=10.0, direction=d1,
    )
    hud.add_sound_event(e1)

    # Threat 2: Newer shot at +90° (heard at t=11.5)
    d2 = DirectionEstimate(
        azimuth_deg=90.0, itd_ms=0.5, ild_db=8.0, confidence=0.95,
        is_self_sound=False, is_uncertain=False, dominant_band="high",
        azimuth_360_deg=90.0, is_rear=False,
    )
    e2 = SoundEvent(
        event_id="e2", timestamp=11.5, peak_db=-14.0, energy_ratio=8.0,
        channel_bias=0.8, duration_ms=10.0, direction=d2,
    )
    hud.add_sound_event(e2)

    clusters = hud.threat_tracker.get_active_clusters(now=11.6)
    assert len(clusters) == 2
    newest = max(clusters, key=lambda c: c.last_seen)
    assert newest.azimuth_deg == pytest.approx(90.0)

    # Trigger repaint to verify drawing logic executes with flame orange newest highlight
    hud.repaint()
    hud.close()


def test_radar_overlay_pubg_sound_lab_external_threats(qapp) -> None:
    """Validate that 0° and 180° gunshots in PUBG Sound Lab mode create active threat rays."""
    hud = RadarOverlayWindow()
    hud.set_spatial_mode("hrtf_360")

    # Loud 0° Ahead gunshot (PUBG Sound Lab front target)
    d_front = DirectionEstimate(
        azimuth_deg=0.0, itd_ms=0.0, ild_db=0.0, confidence=0.95,
        is_self_sound=False, is_uncertain=False, dominant_band="low",
        azimuth_360_deg=0.0, is_rear=False,
    )
    e_front = SoundEvent(
        event_id="pubg_front", timestamp=5.0, peak_db=-1.5, energy_ratio=10.0,
        channel_bias=0.0, duration_ms=12.0, direction=d_front,
    )
    hud.add_sound_event(e_front)

    # Loud 180° Behind gunshot (PUBG Sound Lab rear target)
    d_rear = DirectionEstimate(
        azimuth_deg=0.0, itd_ms=0.0, ild_db=0.0, confidence=0.95,
        is_self_sound=False, is_uncertain=False, dominant_band="low",
        azimuth_360_deg=180.0, is_rear=True,
    )
    e_rear = SoundEvent(
        event_id="pubg_rear", timestamp=5.5, peak_db=-2.0, energy_ratio=9.0,
        channel_bias=0.0, duration_ms=12.0, direction=d_rear,
    )
    hud.add_sound_event(e_rear)

    clusters = hud.threat_tracker.get_active_clusters(now=5.6)
    assert len(clusters) == 2
    hud.repaint()
    hud.close()


def test_radar_overlay_reset_gyro_heading(qapp) -> None:
    """Validate reset_gyro_heading clears accumulated mouse yaw to 0°."""
    hud = RadarOverlayWindow()
    hud.set_mouse_compass_enabled(True)
    hud.mouse_tracker.add_delta_x(200)
    assert hud.mouse_tracker.get_yaw_deg() != 0.0

    hud.reset_gyro_heading()
    assert hud.mouse_tracker.get_yaw_deg() == pytest.approx(0.0)
    hud.close()


def test_radar_overlay_direct_mode_by_default(qapp) -> None:
    """Validate that overlay defaults to Direct Screen-Locked Mode (mouse gyro disabled)."""
    hud = RadarOverlayWindow()
    assert not hud.mouse_tracker.enabled
    assert hud.mouse_tracker.get_yaw_deg() == 0.0
    assert hud.spatial_mode == "stereo_180"

    # Moving mouse in direct mode must NEVER accumulate yaw
    hud.mouse_tracker.add_delta_x(500)
    assert hud.mouse_tracker.get_yaw_deg() == 0.0
    hud.close()


def test_radar_overlay_zones_mode_and_rendering(qapp) -> None:
    """Validate switching between 'rays' and 'zones' radar styles and rendering without errors."""
    from PySide6.QtGui import QImage, QPainter

    hud = RadarOverlayWindow()
    assert hud.radar_type == "rays"

    # Switch to area zones mode
    hud.set_radar_type("zones")
    assert hud.radar_type == "zones"

    # Push active directional sound events
    d_threat = DirectionEstimate(
        azimuth_deg=45.0,
        itd_ms=0.30,
        ild_db=5.0,
        confidence=0.88,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="high",
    )
    e_threat = SoundEvent(
        event_id="threat_45",
        timestamp=10.0,
        peak_db=-8.0,
        energy_ratio=6.0,
        channel_bias=0.4,
        duration_ms=11.0,
        direction=d_threat,
    )
    hud.add_sound_event(e_threat)

    # Render offscreen in zones mode
    img = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    hud.render(img)

    # Switch back to rays mode and render offscreen
    hud.set_radar_type("rays")
    assert hud.radar_type == "rays"

    img_rays = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    img_rays.fill(0)
    hud.render(img_rays)

    hud.close()


def test_radar_overlay_toggle_mini_circles(qapp) -> None:
    """Validate toggling show_sound_circles to hide mini-circles and render without errors."""
    from PySide6.QtGui import QImage

    hud = RadarOverlayWindow()
    assert hud.show_sound_circles is True

    # Disable mini-circles
    hud.set_show_sound_circles(False)
    assert hud.show_sound_circles is False

    d_threat = DirectionEstimate(
        azimuth_deg=-60.0,
        itd_ms=-0.40,
        ild_db=-7.0,
        confidence=0.90,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="high",
    )
    e_threat = SoundEvent(
        event_id="threat_circle_test",
        timestamp=20.0,
        peak_db=-6.0,
        energy_ratio=8.0,
        channel_bias=-0.5,
        duration_ms=10.0,
        direction=d_threat,
    )
    hud.add_sound_event(e_threat)

    # Render with mini-circles hidden in zones mode
    hud.set_radar_type("zones")
    img_zones = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    hud.render(img_zones)

    # Render with mini-circles hidden in rays mode
    hud.set_radar_type("rays")
    img_rays = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    hud.render(img_rays)

    # Re-enable mini-circles
    hud.set_show_sound_circles(True)
    assert hud.show_sound_circles is True
    hud.render(img_rays)

    hud.close()


def test_radar_overlay_toggle_sound_numbers(qapp) -> None:
    """Validate toggling show_sound_numbers to hide burst counters and metrics."""
    from PySide6.QtGui import QImage

    hud = RadarOverlayWindow()
    assert hud.show_sound_numbers is True

    # Disable sound numbers
    hud.set_show_sound_numbers(False)
    assert hud.show_sound_numbers is False

    d_threat = DirectionEstimate(
        azimuth_deg=45.0,
        itd_ms=0.35,
        ild_db=6.0,
        confidence=0.92,
        is_self_sound=False,
        is_uncertain=False,
        dominant_band="high",
    )
    e1 = SoundEvent(
        event_id="threat_num_1",
        timestamp=25.0,
        peak_db=-8.0,
        energy_ratio=8.0,
        channel_bias=0.4,
        duration_ms=10.0,
        direction=d_threat,
    )
    e2 = SoundEvent(
        event_id="threat_num_2",
        timestamp=25.2,
        peak_db=-7.5,
        energy_ratio=8.5,
        channel_bias=0.4,
        duration_ms=10.0,
        direction=d_threat,
    )
    hud.add_sound_event(e1)
    hud.add_sound_event(e2)

    # Render with numbers hidden in zones mode
    hud.set_radar_type("zones")
    img_zones = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    hud.render(img_zones)

    # Render with numbers hidden in rays mode
    hud.set_radar_type("rays")
    img_rays = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    hud.render(img_rays)

    # Verify bearing label formatting without degrees
    lbl = hud._format_bearing_label(45.0)
    assert "°" not in lbl
    assert lbl == "FRONT-RIGHT"

    # Re-enable numbers
    hud.set_show_sound_numbers(True)
    assert hud.show_sound_numbers is True
    lbl_with_deg = hud._format_bearing_label(45.0)
    assert "45°" in lbl_with_deg
    hud.render(img_rays)

    hud.close()
