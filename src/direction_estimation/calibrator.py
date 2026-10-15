"""Interactive weapon audio calibrator for measuring player weapon profile and setting thresholds."""

from __future__ import annotations

import enum
import math
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


class CalibrationState(str, enum.Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class CalibrationResult:
    """Outcome of a weapon audio calibration session."""

    success: bool
    shot_count: int
    avg_left_peak_db: float
    avg_right_peak_db: float
    recommended_threshold_db: float
    message: str


class WeaponCalibrator:
    """Manages an interactive calibration session to detect the player's weapon blast profile."""

    def __init__(
        self,
        duration_s: float = 5.0,
        target_shots: int = 3,
        safety_margin_db: float = 2.5,
    ) -> None:
        self.duration_s = duration_s
        self.target_shots = target_shots
        self.safety_margin_db = safety_margin_db

        self.state: CalibrationState = CalibrationState.IDLE
        self._start_time: float = 0.0
        self._recorded_shots: list[Tuple[float, float]] = []  # (left_peak_db, right_peak_db)

    def start(self) -> None:
        """Start a new calibration recording session."""
        self.state = CalibrationState.RECORDING
        self._start_time = time.monotonic()
        self._recorded_shots.clear()

    def cancel(self) -> None:
        """Cancel the ongoing calibration session."""
        self.state = CalibrationState.IDLE
        self._recorded_shots.clear()

    @property
    def remaining_seconds(self) -> float:
        """Remaining duration in seconds before calibration times out."""
        if self.state != CalibrationState.RECORDING:
            return 0.0
        elapsed = time.monotonic() - self._start_time
        return max(0.0, self.duration_s - elapsed)

    @property
    def shots_recorded(self) -> int:
        """Number of distinct weapon shots recorded so far."""
        return len(self._recorded_shots)

    def register_shot(self, left_peak_db: float, right_peak_db: float) -> Optional[CalibrationResult]:
        """Record a candidate weapon blast event and check for completion.

        Args:
            left_peak_db: Peak dBFS of the left channel during the transient.
            right_peak_db: Peak dBFS of the right channel during the transient.

        Returns:
            CalibrationResult if calibration completed; None if still recording.
        """
        if self.state != CalibrationState.RECORDING:
            return None

        # Only register loud transients (louder than -25 dBFS) as potential weapon shots
        if left_peak_db < -25.0 or right_peak_db < -25.0:
            return None

        self._recorded_shots.append((left_peak_db, right_peak_db))

        # If target shots reached, finalize immediately
        if len(self._recorded_shots) >= self.target_shots:
            return self.finalize()

        return None

    def poll(self) -> Optional[CalibrationResult]:
        """Check timer expiry and finalize if time is up."""
        if self.state != CalibrationState.RECORDING:
            return None

        if time.monotonic() - self._start_time >= self.duration_s:
            return self.finalize()

        return None

    def finalize(self) -> CalibrationResult:
        """Compute the recommended bilateral threshold from recorded shots."""
        if not self._recorded_shots:
            self.state = CalibrationState.FAILED
            return CalibrationResult(
                success=False,
                shot_count=0,
                avg_left_peak_db=-60.0,
                avg_right_peak_db=-60.0,
                recommended_threshold_db=-4.0,
                message="No weapon shots detected during calibration. Keep firing while calibrating.",
            )

        avg_l = float(np.mean([s[0] for s in self._recorded_shots]))
        avg_r = float(np.mean([s[1] for s in self._recorded_shots]))

        # Take the quieter of the two channels and subtract safety margin
        quieter_channel = min(avg_l, avg_r)
        recommended = round(quieter_channel - self.safety_margin_db, 1)
        recommended = max(-30.0, min(-1.0, recommended))

        self.state = CalibrationState.COMPLETED
        return CalibrationResult(
            success=True,
            shot_count=len(self._recorded_shots),
            avg_left_peak_db=round(avg_l, 1),
            avg_right_peak_db=round(avg_r, 1),
            recommended_threshold_db=recommended,
            message=(
                f"Calibrated successfully from {len(self._recorded_shots)} shots! "
                f"L: {avg_l:.1f} dB, R: {avg_r:.1f} dB. New threshold: {recommended:.1f} dBFS."
            ),
        )
