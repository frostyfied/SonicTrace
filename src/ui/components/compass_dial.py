"""180-degree Directional Compass Dial Widget for visualizing acoustic azimuth."""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from src.direction_estimation.types import DirectionEstimate
from src.event_classification.types import SoundType


class DirectionCompassWidget(QWidget):
    """Semicircular 180° compass dial rendering azimuth angle, ITD, and confidence."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(130)
        self.setMinimumWidth(280)

        # Active display state
        self._target_azimuth_deg: float = 0.0
        self._confidence: float = 0.0
        self._is_self_sound: bool = False
        self._is_uncertain: bool = False
        self._sound_type: SoundType = SoundType.GENERIC
        self._is_rear: bool = False
        self._azimuth_360_deg: float = 0.0
        self._opacity: float = 0.0  # 0.0 (idle/dimmed) to 1.0 (bright active)

        # Decay timer
        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(25)  # 40 fps decay animation
        self._decay_timer.timeout.connect(self._on_decay_tick)

    def set_direction(
        self,
        estimate: DirectionEstimate,
        sound_type: SoundType = SoundType.GENERIC,
    ) -> None:
        """Trigger visual needle pointing to estimated azimuth with high opacity."""
        self._target_azimuth_deg = estimate.azimuth_deg
        self._confidence = estimate.confidence
        self._is_self_sound = estimate.is_self_sound
        self._is_uncertain = estimate.is_uncertain
        self._dominant_band = estimate.dominant_band
        self._sound_type = sound_type
        self._is_rear = getattr(estimate, "is_rear", False)
        self._azimuth_360_deg = getattr(estimate, "azimuth_360_deg", estimate.azimuth_deg)
        self._opacity = 1.0


        if not self._decay_timer.isActive():
            self._decay_timer.start()
        self.update()

    def _on_decay_tick(self) -> None:
        """Gradually fade needle opacity back to subtle idle baseline."""
        self._opacity = max(0.15, self._opacity - 0.025)
        if self._opacity <= 0.15:
            self._decay_timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        """Draw the 180° semicircular compass dial, angle markings, and directional ray."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        # Origin is centered near the bottom
        cx = w / 2.0
        cy = h - 18.0
        radius = min(cx - 24.0, cy - 14.0)
        if radius < 30.0:
            return

        # 1. Background Semicircular Arc Track with Modern Gradient
        arc_rect = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)
        grad = QRadialGradient(cx, cy, radius)
        grad.setColorAt(0.0, QColor("#090f1d"))
        grad.setColorAt(0.7, QColor("#0f172a"))
        grad.setColorAt(1.0, QColor("#1e293b"))
        painter.setPen(QPen(QColor("#334155"), 1.8))
        painter.setBrush(QBrush(grad))
        painter.drawPie(arc_rect, 0 * 16, 180 * 16)

        # Concentric inner distance rings (50% and 75%)
        inner_pen = QPen(QColor("#1e293b"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(inner_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for frac in (0.50, 0.75):
            r = radius * frac
            painter.drawArc(QRectF(cx - r, cy - r, r * 2.0, r * 2.0), 0 * 16, 180 * 16)

        # 2. Precision Minor & Major Angle Ticks
        for deg in range(-90, 91, 15):
            phi_rad = math.radians(90.0 - deg)
            is_major = (deg in (-90, -45, 0, 45, 90))
            tick_len = 10.0 if is_major else 5.0
            tick_col = QColor("#64748b") if is_major else QColor("#334155")
            tick_width = 1.5 if is_major else 1.0

            x_out = cx + radius * math.cos(phi_rad)
            y_out = cy - radius * math.sin(phi_rad)
            x_in = cx + (radius - tick_len) * math.cos(phi_rad)
            y_in = cy - (radius - tick_len) * math.sin(phi_rad)

            painter.setPen(QPen(tick_col, tick_width))
            painter.drawLine(QPointF(x_in, y_in), QPointF(x_out, y_out))

        # Major Labels
        tick_angles = [
            (-90.0, "LEFT -90°"),
            (-45.0, "-45°"),
            (0.0, "AHEAD 0°"),
            (45.0, "+45°"),
            (90.0, "+90° RIGHT"),
        ]

        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#94a3b8")))

        for az, label in tick_angles:
            phi_rad = math.radians(90.0 - az)
            tx = cx + (radius + 14.0) * math.cos(phi_rad)
            ty = cy - (radius + 14.0) * math.sin(phi_rad)
            painter.drawText(
                QRectF(tx - 36.0, ty - 8.0, 72.0, 16.0),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        # 3. Direction Needle & Precision Blip
        phi_target = math.radians(90.0 - self._target_azimuth_deg)
        blip_x = cx + radius * math.cos(phi_target)
        blip_y = cy - radius * math.sin(phi_target)

        # Color determination based on SoundType
        if self._is_self_sound or self._sound_type == SoundType.SELF:
            needle_col = QColor(168, 85, 247, int(255 * self._opacity))  # Purple
            type_title = "SELF"
        elif self._is_uncertain:
            needle_col = QColor(245, 158, 11, int(255 * self._opacity))  # Amber
            type_title = "AMBIGUOUS"
        else:
            needle_col = QColor(34, 211, 238, int(255 * self._opacity))  # Cyan
            type_title = "SOUND"

        # Directional ray line
        painter.setPen(QPen(needle_col, 2.5))
        painter.drawLine(QPointF(cx, cy), QPointF(blip_x, blip_y))

        # Glowing blip on perimeter
        blip_grad = QRadialGradient(blip_x, blip_y, 10.0)
        blip_grad.setColorAt(0.0, needle_col)
        blip_grad.setColorAt(1.0, QColor(needle_col.red(), needle_col.green(), needle_col.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(blip_grad))
        painter.drawEllipse(QPointF(blip_x, blip_y), 9.0, 9.0)

        # 4. Center Player Origin Reticle
        painter.setPen(QPen(QColor("#38bdf8"), 2.0))
        painter.setBrush(QBrush(QColor("#0369a1")))
        painter.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

        # 5. Bottom Digital Readout (Clean Monospace Telemetry)
        readout_font = QFont("Consolas", 10, QFont.Weight.Bold)
        painter.setFont(readout_font)
        painter.setPen(QPen(needle_col))

        if self._is_self_sound or self._sound_type == SoundType.SELF:
            readout_text = f"PLAYER SELF SOUND (0°) [Conf: {int(self._confidence * 100)}%]"
        elif self._is_rear:
            if abs(self._target_azimuth_deg) <= 2.0:
                readout_text = f"BEHIND (180.0°) [REAR] [Conf: {int(self._confidence * 100)}%]"
            elif self._target_azimuth_deg < -2.0:
                readout_text = f"BEHIND-LEFT ({self._azimuth_360_deg:.1f}°) [REAR] [Conf: {int(self._confidence * 100)}%]"
            else:
                readout_text = f"BEHIND-RIGHT (+{self._azimuth_360_deg:.1f}°) [REAR] [Conf: {int(self._confidence * 100)}%]"
        elif abs(self._target_azimuth_deg) <= 2.0:
            readout_text = f"AHEAD (0.0°) [Conf: {int(self._confidence * 100)}%]"
        elif self._target_azimuth_deg < -2.0:
            readout_text = f"FRONT-LEFT ({self._target_azimuth_deg:.1f}°) [Conf: {int(self._confidence * 100)}%]"
        else:
            readout_text = f"FRONT-RIGHT (+{self._target_azimuth_deg:.1f}°) [Conf: {int(self._confidence * 100)}%]"

        painter.drawText(
            QRectF(cx - 170.0, cy - 26.0, 340.0, 18.0),
            Qt.AlignmentFlag.AlignCenter,
            readout_text,
        )

