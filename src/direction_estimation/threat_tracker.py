"""Spatial threat clustering and tracking engine with world-space gyro compass persistence."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional

from src.direction_estimation.types import DirectionEstimate
from src.event_classification.types import SoundType
from src.event_detection.types import SoundEvent


@dataclass
class ThreatCluster:
    """An acoustic threat cluster tracking an active enemy firing position."""

    cluster_id: int
    azimuth_deg: float          # Current relative screen bearing [-180.0°, +180.0°] (0° Ahead, ±180° Behind)
    peak_db: float              # Peak dBFS level of the loudest shot in this cluster
    shot_count: int             # Number of burst shots from this threat bearing
    first_seen: float           # Monotonic timestamp of the first detected shot
    last_seen: float            # Monotonic timestamp of the latest detected shot
    confidence: float           # Confidence score [0.0, 1.0]
    is_rear: bool               # True if located in the rear hemisphere
    is_primary: bool = False     # True if this is the most critical active threat
    dominant_band: str = "mid"
    world_azimuth_deg: float = 0.0  # Absolute world-space heading anchored to gyro compass
    is_on_target: bool = False      # True if aligned within lock-on tolerance of 0° Ahead


def circular_angle_diff(angle_1: float, angle_2: float) -> float:
    """Compute signed circular angle difference (angle_1 - angle_2) in [-180.0, 180.0]."""
    diff = (angle_1 - angle_2 + 180.0) % 360.0 - 180.0
    return diff


def circular_angle_distance(angle_1: float, angle_2: float) -> float:
    """Compute absolute shortest angular distance on a 360° circle."""
    return abs(circular_angle_diff(angle_1, angle_2))


def normalize_bearing_360(angle: float) -> float:
    """Normalize bearing to [-180.0, 180.0]."""
    norm = (angle + 180.0) % 360.0 - 180.0
    if norm == -180.0:
        return 180.0
    return norm


class SpatialThreatTracker:
    """Groups incoming transient sound events into persistent spatial threat clusters with gyro mouse orientation."""

    def __init__(
        self,
        angular_tolerance_deg: float = 20.0,
        cluster_lifetime_s: float = 8.0,
        max_clusters: int = 6,
        on_target_tolerance_deg: float = 6.0,
    ) -> None:
        self.angular_tolerance_deg = angular_tolerance_deg
        self.cluster_lifetime_s = cluster_lifetime_s
        self.max_clusters = max_clusters
        self.on_target_tolerance_deg = on_target_tolerance_deg

        self._clusters: List[ThreatCluster] = []
        self._next_id: int = 1

    def update(
        self,
        event: SoundEvent,
        current_yaw: float = 0.0,
        now: Optional[float] = None,
    ) -> Optional[ThreatCluster]:
        """Incorporate an incoming sound event into active threat clusters.

        Args:
            event: The detected SoundEvent.
            current_yaw: Current player gyro yaw heading in degrees.
            now: Optional monotonic timestamp.

        Returns:
            The matched or newly spawned ThreatCluster, or None if the event is a player self-sound
            or an isolated low-confidence/uncertain noise transient.
        """
        direction = event.direction
        if direction is None:
            return None

        # Exclude player's own point-blank weapon discharges or self-footsteps
        if direction.is_self_sound or event.sound_type == SoundType.SELF:
            return None

        current_time = time.monotonic() if now is None else now

        # Use 360 bearing
        event_rel_azimuth = getattr(direction, "azimuth_360_deg", direction.azimuth_deg)
        event_is_rear = getattr(direction, "is_rear", False)

        # Convert relative bearing to world-space heading at time of hearing
        world_azimuth = normalize_bearing_360(event_rel_azimuth + current_yaw)

        # 1. Prune expired clusters first
        self._prune_expired(current_time)

        # 2. Find closest existing cluster in world space
        best_cluster: Optional[ThreatCluster] = None
        min_dist = float("inf")

        for cluster in self._clusters:
            dist = circular_angle_distance(world_azimuth, cluster.world_azimuth_deg)
            if dist < min_dist and dist <= self.angular_tolerance_deg:
                min_dist = dist
                best_cluster = cluster

        if best_cluster is not None:
            # Merge into existing cluster with confidence-weighted circular EMA
            best_cluster.shot_count += 1
            best_cluster.last_seen = current_time
            best_cluster.peak_db = max(best_cluster.peak_db, event.peak_db)
            best_cluster.dominant_band = direction.dominant_band

            # Confidence-weighted bearing smoothing: prevents low-confidence reverb tails
            # from pulling a locked high-confidence threat ray off-target
            conf_ratio = direction.confidence / (best_cluster.confidence + direction.confidence + 1e-6)
            alpha_az = max(0.08, min(0.45, 0.50 * conf_ratio))
            diff = circular_angle_diff(world_azimuth, best_cluster.world_azimuth_deg)
            smoothed_world = best_cluster.world_azimuth_deg + alpha_az * diff
            best_cluster.world_azimuth_deg = round(normalize_bearing_360(smoothed_world), 1)

            # Only allow events with comparable confidence to flip front/rear hemisphere state
            if direction.confidence >= best_cluster.confidence * 0.80:
                best_cluster.is_rear = event_is_rear
            best_cluster.confidence = max(best_cluster.confidence, direction.confidence)

            # Update current screen bearing
            screen_bearing = normalize_bearing_360(best_cluster.world_azimuth_deg - current_yaw)
            best_cluster.azimuth_deg = round(screen_bearing, 1)
            best_cluster.is_on_target = (abs(best_cluster.azimuth_deg) <= self.on_target_tolerance_deg)

            self._rank_threats(current_time)
            return best_cluster

        # Do not spawn brand-new persistent threat rays from uncertain/low-confidence echoes
        if getattr(direction, "is_uncertain", False):
            return None

        # 3. Create new persistent threat cluster
        initial_screen_bearing = normalize_bearing_360(world_azimuth - current_yaw)
        new_cluster = ThreatCluster(
            cluster_id=self._next_id,
            azimuth_deg=round(initial_screen_bearing, 1),
            peak_db=round(event.peak_db, 1),
            shot_count=1,
            first_seen=current_time,
            last_seen=current_time,
            confidence=round(direction.confidence, 2),
            is_rear=event_is_rear,
            dominant_band=direction.dominant_band,
            is_primary=False,
            world_azimuth_deg=round(world_azimuth, 1),
            is_on_target=(abs(initial_screen_bearing) <= self.on_target_tolerance_deg),
        )
        self._next_id += 1
        self._clusters.append(new_cluster)

        # Cap cluster count
        if len(self._clusters) > self.max_clusters:
            self._clusters.sort(key=lambda c: c.last_seen)
            self._clusters.pop(0)

        self._rank_threats(current_time)
        return new_cluster

    def get_active_clusters(
        self,
        current_yaw: float = 0.0,
        now: Optional[float] = None,
    ) -> List[ThreatCluster]:
        """Retrieve all currently active threat clusters, updating their screen bearings to the current yaw."""
        current_time = time.monotonic() if now is None else now
        self._prune_expired(current_time)

        # Update screen bearings based on current player heading
        for cluster in self._clusters:
            screen_az = normalize_bearing_360(cluster.world_azimuth_deg - current_yaw)
            cluster.azimuth_deg = round(screen_az, 1)
            cluster.is_on_target = (abs(cluster.azimuth_deg) <= self.on_target_tolerance_deg)

        self._rank_threats(current_time)
        return list(self._clusters)

    def _prune_expired(self, current_time: float) -> None:
        """Remove clusters that have not received shots within lifetime window."""
        self._clusters = [
            c for c in self._clusters
            if (current_time - c.last_seen) <= self.cluster_lifetime_s
        ]

    def _rank_threats(self, current_time: float) -> None:
        """Rank threats and flag is_primary on the highest priority threat."""
        if not self._clusters:
            return

        def score(c: ThreatCluster) -> float:
            recency = max(0.0, self.cluster_lifetime_s - (current_time - c.last_seen))
            return (c.shot_count * 15.0) + (c.peak_db + 60.0) * 0.5 + (recency * 10.0)

        self._clusters.sort(key=score, reverse=True)
        for idx, c in enumerate(self._clusters):
            c.is_primary = (idx == 0)

    def reset(self) -> None:
        """Clear all active threat clusters."""
        self._clusters.clear()
        self._next_id = 1
