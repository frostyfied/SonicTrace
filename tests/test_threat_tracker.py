"""Unit tests for SpatialThreatTracker multi-threat clustering engine."""

from __future__ import annotations

import pytest

from src.direction_estimation.threat_tracker import (
    SpatialThreatTracker,
    circular_angle_diff,
    circular_angle_distance,
    normalize_bearing_360,
)
from src.direction_estimation.types import DirectionEstimate
from src.event_classification.types import SoundType
from src.event_detection.types import SoundEvent


def _make_event(
    event_id: str,
    azimuth_360: float,
    peak_db: float = -30.0,
    timestamp: float = 100.0,
    is_self: bool = False,
    sound_type: SoundType = SoundType.SOUND,
    is_rear: bool = False,
) -> SoundEvent:
    dir_est = DirectionEstimate(
        azimuth_deg=min(90.0, max(-90.0, azimuth_360)),
        itd_ms=0.0,
        ild_db=0.0,
        confidence=0.85,
        is_self_sound=is_self,
        is_uncertain=False,
        dominant_band="high",
        azimuth_360_deg=azimuth_360,
        is_rear=is_rear,
        front_back_ratio=0.2 if is_rear else 1.2,
    )
    return SoundEvent(
        event_id=event_id,
        timestamp=timestamp,
        peak_db=peak_db,
        energy_ratio=3.5,
        channel_bias=0.0,
        duration_ms=10.0,
        direction=dir_est,
        sound_type=SoundType.SELF if is_self else sound_type,
    )


def test_circular_angle_helpers() -> None:
    """Validate wrap-around circular angle math across the +/-180 boundary."""
    assert circular_angle_diff(10.0, 0.0) == pytest.approx(10.0)
    assert circular_angle_diff(170.0, -170.0) == pytest.approx(-20.0)
    assert circular_angle_diff(-170.0, 170.0) == pytest.approx(20.0)
    assert circular_angle_distance(170.0, -170.0) == pytest.approx(20.0)
    assert circular_angle_distance(0.0, 180.0) == pytest.approx(180.0)
    assert normalize_bearing_360(190.0) == pytest.approx(-170.0)
    assert normalize_bearing_360(-190.0) == pytest.approx(170.0)


def test_threat_tracker_single_event() -> None:
    """A single external sound event creates a threat cluster."""
    tracker = SpatialThreatTracker(angular_tolerance_deg=20.0, cluster_lifetime_s=3.0)
    evt = _make_event("evt_1", azimuth_360=45.0, peak_db=-25.0, timestamp=10.0)

    cluster = tracker.update(evt, now=10.0)
    assert cluster is not None
    assert cluster.cluster_id == 1
    assert cluster.azimuth_deg == pytest.approx(45.0)
    assert cluster.shot_count == 1
    assert cluster.is_primary is True

    active = tracker.get_active_clusters(now=10.0)
    assert len(active) == 1
    assert active[0].cluster_id == 1


def test_threat_tracker_burst_clustering() -> None:
    """Multiple shots from similar angles cluster together and accumulate shot counts."""
    tracker = SpatialThreatTracker(angular_tolerance_deg=20.0, cluster_lifetime_s=3.0)

    evt1 = _make_event("evt_1", azimuth_360=40.0, peak_db=-30.0, timestamp=10.0)
    evt2 = _make_event("evt_2", azimuth_360=48.0, peak_db=-24.0, timestamp=10.2)
    evt3 = _make_event("evt_3", azimuth_360=42.0, peak_db=-22.0, timestamp=10.4)

    tracker.update(evt1, now=10.0)
    tracker.update(evt2, now=10.2)
    cluster = tracker.update(evt3, now=10.4)

    assert cluster is not None
    assert cluster.shot_count == 3
    assert cluster.peak_db == pytest.approx(-22.0)
    # Azimuth smoothed between 40, 48, 42
    assert 40.0 <= cluster.azimuth_deg <= 48.0

    active = tracker.get_active_clusters(now=10.5)
    assert len(active) == 1
    assert active[0].shot_count == 3


def test_threat_tracker_multi_threat_separation() -> None:
    """Distinct enemy positions create independent simultaneous threat clusters."""
    tracker = SpatialThreatTracker(angular_tolerance_deg=20.0, cluster_lifetime_s=3.0)

    # Threat A: Ahead-Left (-45°)
    evt_a1 = _make_event("evt_a1", azimuth_360=-45.0, peak_db=-28.0, timestamp=10.0)
    evt_a2 = _make_event("evt_a2", azimuth_360=-43.0, peak_db=-26.0, timestamp=10.1)

    # Threat B: Behind-Right (+135°)
    evt_b1 = _make_event("evt_b1", azimuth_360=135.0, peak_db=-20.0, timestamp=10.2, is_rear=True)

    tracker.update(evt_a1, now=10.0)
    tracker.update(evt_a2, now=10.1)
    tracker.update(evt_b1, now=10.2)

    active = tracker.get_active_clusters(now=10.3)
    assert len(active) == 2

    azimuths = {round(c.azimuth_deg) for c in active}
    assert any(abs(az - (-45)) <= 5 for az in azimuths)
    assert any(abs(az - 135) <= 5 for az in azimuths)


def test_threat_tracker_self_sound_ignored() -> None:
    """Player self-sound weapon discharges must not create threat clusters."""
    tracker = SpatialThreatTracker()
    self_evt = _make_event("evt_self", azimuth_360=0.0, peak_db=-2.0, timestamp=10.0, is_self=True)

    res = tracker.update(self_evt, now=10.0)
    assert res is None
    assert len(tracker.get_active_clusters(now=10.0)) == 0


def test_threat_tracker_cluster_expiration() -> None:
    """Clusters expire and are pruned after cluster_lifetime_s."""
    tracker = SpatialThreatTracker(cluster_lifetime_s=2.0)

    evt = _make_event("evt_1", azimuth_360=-60.0, timestamp=10.0)
    tracker.update(evt, now=10.0)
    assert len(tracker.get_active_clusters(now=11.5)) == 1

    # At 12.5 (2.5s later), cluster must be pruned
    assert len(tracker.get_active_clusters(now=12.5)) == 0


def test_threat_tracker_primary_threat_prioritization() -> None:
    """Cluster with active burst and high intensity is ranked as primary."""
    tracker = SpatialThreatTracker(cluster_lifetime_s=3.0)

    # Single shot at 90°
    tracker.update(_make_event("evt_1", azimuth_360=90.0, peak_db=-35.0, timestamp=10.0), now=10.0)

    # 4-shot burst at -30°
    for t in [10.1, 10.2, 10.3, 10.4]:
        tracker.update(_make_event("evt_burst", azimuth_360=-30.0, peak_db=-20.0, timestamp=t), now=t)

    active = tracker.get_active_clusters(now=10.5)
    assert len(active) == 2
    assert active[0].is_primary is True
    assert active[0].azimuth_deg == pytest.approx(-30.0, abs=2.0)
    assert active[1].is_primary is False


def test_threat_tracker_mouse_yaw_rotation_and_target_alignment() -> None:
    """Validate that turning mouse yaw rotates persistent threat ray towards 0° (Ahead) and triggers lock-on."""
    tracker = SpatialThreatTracker(cluster_lifetime_s=8.0, on_target_tolerance_deg=6.0)

    # Enemy shoots from the right (+90°) while player is facing initial heading (yaw = 0.0)
    evt = _make_event("gunshot_right", azimuth_360=90.0, peak_db=-20.0, timestamp=10.0)
    cluster = tracker.update(evt, current_yaw=0.0, now=10.0)
    assert cluster is not None
    assert cluster.azimuth_deg == pytest.approx(90.0)
    assert cluster.is_on_target is False

    # Player turns mouse 45° to the right (current_yaw = 45.0)
    active = tracker.get_active_clusters(current_yaw=45.0, now=10.5)
    assert len(active) == 1
    # Ray rotates from 90° towards 0° -> now at +45°
    assert active[0].azimuth_deg == pytest.approx(45.0)
    assert active[0].is_on_target is False

    # Player completes 90° turn to face the enemy directly (current_yaw = 90.0)
    active = tracker.get_active_clusters(current_yaw=90.0, now=11.0)
    assert len(active) == 1
    # Ray reaches exactly 0.0° Ahead / North!
    assert active[0].azimuth_deg == pytest.approx(0.0)
    # Locked on target!
    assert active[0].is_on_target is True

    # Player overshoots right by 20° (current_yaw = 110.0)
    active = tracker.get_active_clusters(current_yaw=110.0, now=11.5)
    assert len(active) == 1
    assert active[0].azimuth_deg == pytest.approx(-20.0)
    assert active[0].is_on_target is False



def test_threat_tracker_ignores_uncertain_new_clusters_and_weights_confidence() -> None:
    """Uncertain noise events must not spawn new threat clusters or yank high-confidence clusters."""
    tracker = SpatialThreatTracker(angular_tolerance_deg=20.0, cluster_lifetime_s=5.0)

    # 1. Uncertain event alone does not spawn a new cluster
    uncertain_evt = _make_event("evt_unc", azimuth_360=60.0, peak_db=-35.0, timestamp=1.0)
    uncertain_evt.direction.is_uncertain = True
    uncertain_evt.direction.confidence = 0.15
    assert tracker.update(uncertain_evt, now=1.0) is None
    assert len(tracker.get_active_clusters(now=1.0)) == 0

    # 2. High-confidence event spawns cluster at +45.0°
    strong_evt = _make_event("evt_strong", azimuth_360=45.0, peak_db=-15.0, timestamp=2.0)
    strong_evt.direction.confidence = 0.95
    cluster = tracker.update(strong_evt, now=2.0)
    assert cluster is not None
    assert cluster.azimuth_deg == pytest.approx(45.0)

    # 3. Low-confidence reflection at +60.0° nudges cluster minimally (< 2.5°) instead of 25% (+3.8°)
    weak_echo = _make_event("evt_echo", azimuth_360=60.0, peak_db=-28.0, timestamp=2.1)
    weak_echo.direction.confidence = 0.10
    updated = tracker.update(weak_echo, now=2.1)
    assert updated is not None
    assert updated.azimuth_deg < 47.0
