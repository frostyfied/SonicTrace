"""Custom audio level meter widget with dBFS markings, ballistics, and peak hold."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from src.config.settings import MeterConfig


class MeterBar(QWidget):
    """Custom painted horizontal stereo level bar with gradient and peak hold line."""

    def __init__(
        self,
        channel_label: str = "L",
        config: MeterConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.channel_label = channel_label
        self.config = config or MeterConfig()

        self._rms_db = self.config.min_db
        self._peak_held_db = self.config.min_db

        self.setMinimumHeight(44)
        self.setMinimumWidth(260)

    def set_levels(self, rms_db: float, peak_held_db: float) -> None:
        """Update current displayed RMS dB and held peak dB."""
        self._rms_db = max(self.config.min_db, min(self.config.max_db, rms_db))
        self._peak_held_db = max(self.config.min_db, min(self.config.max_db, peak_held_db))
        self.update()

    def _db_to_ratio(self, db_val: float) -> float:
        """Convert a dB value to a normalized 0.0 -> 1.0 ratio along the meter scale."""
        total_range = self.config.max_db - self.config.min_db
        if total_range <= 0.0:
            return 0.0
        return max(0.0, min(1.0, (db_val - self.config.min_db) / total_range))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render the meter bar, scale ticks, gradient bar, and peak marker."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = float(self.width())
        height = float(self.height())

        # Layout metrics
        label_width = 30.0
        readout_width = 72.0
        bar_left = label_width + 8.0
        bar_right = width - readout_width - 8.0
        bar_width = max(10.0, bar_right - bar_left)
        bar_top = 8.0
        bar_height = height - 20.0

        # Draw Channel Label ("L" or "R")
        painter.setPen(QPen(QColor("#94a3b8")))
        font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(
            QRectF(0.0, bar_top, label_width, bar_height),
            Qt.AlignmentFlag.AlignCenter,
            self.channel_label,
        )

        # Draw Background Track
        track_rect = QRectF(bar_left, bar_top, bar_width, bar_height)
        painter.setPen(QPen(QColor("#334155"), 1.0))
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.drawRoundedRect(track_rect, 4.0, 4.0)

        # Draw RMS Fill Gradient
        fill_ratio = self._db_to_ratio(self._rms_db)
        if fill_ratio > 0.001:
            fill_width = bar_width * fill_ratio
            fill_rect = QRectF(bar_left, bar_top, fill_width, bar_height)

            gradient = QLinearGradient(bar_left, bar_top, bar_left + bar_width, bar_top)
            # Safe zone: green
            gradient.setColorAt(0.0, QColor("#10b981"))
            # -12 dB: yellow-green
            gradient.setColorAt(0.7, QColor("#eab308"))
            # -6 dB: orange
            gradient.setColorAt(0.88, QColor("#f97316"))
            # 0 dB: red
            gradient.setColorAt(1.0, QColor("#ef4444"))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(fill_rect, 4.0, 4.0)

        # Draw Peak Hold Marker Line
        peak_ratio = self._db_to_ratio(self._peak_held_db)
        if peak_ratio > 0.01:
            peak_x = bar_left + (bar_width * peak_ratio)
            painter.setPen(QPen(QColor("#ffffff"), 2.0))
            painter.drawLine(
                QPointF(peak_x, bar_top - 1.0),
                QPointF(peak_x, bar_top + bar_height + 1.0),
            )

        # Draw Numeric Readout
        painter.setPen(QPen(QColor("#e2e8f0")))
        mono_font = QFont("Consolas", 10)
        painter.setFont(mono_font)
        if self._rms_db <= self.config.min_db + 0.5:
            db_text = "-inf dB"
        else:
            db_text = f"{self._rms_db:5.1f} dB"

        readout_rect = QRectF(bar_right + 8.0, bar_top, readout_width, bar_height)
        painter.drawText(
            readout_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            db_text,
        )

        # Draw Scale Tick Labels beneath the bar
        ticks = [-48, -36, -24, -12, -6, 0]
        tick_font = QFont("Segoe UI", 7)
        painter.setFont(tick_font)
        painter.setPen(QPen(QColor("#64748b")))

        for tick_val in ticks:
            tick_ratio = self._db_to_ratio(float(tick_val))
            tick_x = bar_left + (bar_width * tick_ratio)
            # Small tick line
            painter.drawLine(
                QPointF(tick_x, bar_top + bar_height),
                QPointF(tick_x, bar_top + bar_height + 3.0),
            )
            # Text label
            painter.drawText(
                QRectF(tick_x - 14.0, bar_top + bar_height + 3.0, 28.0, 10.0),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                str(tick_val),
            )
