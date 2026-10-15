"""Unit tests for MouseYawTracker raw input and compass orientation."""

from __future__ import annotations

import pytest

from src.direction_estimation.mouse_tracker import MouseYawTracker


def test_mouse_tracker_initial_state() -> None:
    tracker = MouseYawTracker(sensitivity_deg_per_count=0.05, enabled=True)
    assert tracker.get_yaw_deg() == pytest.approx(0.0)
    assert tracker.sensitivity_deg_per_count == pytest.approx(0.05)
    assert tracker.enabled is True


def test_mouse_tracker_add_delta_x() -> None:
    tracker = MouseYawTracker(sensitivity_deg_per_count=0.05)

    # Move right 100 counts -> +5.0 degrees
    tracker.add_delta_x(100)
    assert tracker.get_yaw_deg() == pytest.approx(5.0)

    # Move right another 300 counts -> +15.0 degrees (total +20.0 degrees)
    tracker.add_delta_x(300)
    assert tracker.get_yaw_deg() == pytest.approx(20.0)

    # Move left 600 counts -> -30.0 degrees (total -10.0 degrees)
    tracker.add_delta_x(-600)
    assert tracker.get_yaw_deg() == pytest.approx(-10.0)


def test_mouse_tracker_yaw_wrapping() -> None:
    tracker = MouseYawTracker(sensitivity_deg_per_count=1.0)

    # Turn 190 degrees right -> wraps to -170 degrees
    tracker.add_delta_x(190)
    assert tracker.get_yaw_deg() == pytest.approx(-170.0)

    # Reset yaw
    tracker.reset_yaw(0.0)
    assert tracker.get_yaw_deg() == pytest.approx(0.0)


def test_mouse_tracker_toggle_enabled() -> None:
    tracker = MouseYawTracker(sensitivity_deg_per_count=0.05)
    tracker.add_delta_x(200)
    assert tracker.get_yaw_deg() == pytest.approx(10.0)

    tracker.set_enabled(False)
    assert tracker.get_yaw_deg() == pytest.approx(0.0)

    # Ignored when disabled
    tracker.add_delta_x(200)
    assert tracker.get_yaw_deg() == pytest.approx(0.0)

    tracker.set_enabled(True)
    tracker.add_delta_x(100)
    assert tracker.get_yaw_deg() == pytest.approx(5.0)


def test_mouse_tracker_interactive_calibration() -> None:
    tracker = MouseYawTracker(sensitivity_deg_per_count=0.05)
    tracker.start_calibration()
    assert tracker.is_calibrating is True

    # Simulate player doing a full 360° turn requiring 7200 mouse counts
    tracker.add_delta_x(7200)

    # Calibrate to 360°
    new_sens = tracker.finish_calibration(target_turn_deg=360.0)
    assert tracker.is_calibrating is False
    assert new_sens == pytest.approx(360.0 / 7200.0)  # 0.05
    assert tracker.sensitivity_deg_per_count == pytest.approx(0.05)
