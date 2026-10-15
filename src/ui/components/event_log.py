"""Live scrolling table widget displaying detected candidate sound events with spatial directions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.event_classification.types import SoundType
from src.event_detection.types import SoundEvent


class EventLogWidget(QWidget):
    """Compact dark-mode table displaying recent sound event records with spatial azimuth and cues."""

    def __init__(self, max_records: int = 30, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.max_records = max_records

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(["ID", "Type", "Time", "Peak", "Azimuth Direction", "ITD", "Conf"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setStyleSheet(
            """
            QTableWidget {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                gridline-color: #1e293b;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 10px;
                border: none;
                border-bottom: 1px solid #334155;
                padding: 4px 6px;
            }
            """
        )
        layout.addWidget(self.table)

    def add_event(self, event: SoundEvent) -> None:
        """Insert a newly detected sound event at the top of the table."""
        self.table.insertRow(0)

        time_str = datetime.now().strftime("%H:%M:%S.%f")[:12]

        # Classification Type badge
        if event.sound_type == SoundType.SELF or (event.direction and event.direction.is_self_sound):
            type_str = "Self"
            type_color = QColor("#c084fc")
        elif event.direction and event.direction.is_uncertain:
            type_str = "Ambiguous"
            type_color = QColor("#f59e0b")
        else:
            type_str = "Sound"
            type_color = QColor("#38bdf8")

        direction = event.direction
        if direction is not None:
            az = direction.azimuth_deg
            az_360 = getattr(direction, "azimuth_360_deg", az)
            is_rear = getattr(direction, "is_rear", False)
            itd_str = f"{direction.itd_ms:+.2f}ms"
            conf_str = f"{int(direction.confidence * 100)}%"

            if direction.is_self_sound or event.sound_type == SoundType.SELF:
                dir_str = "Origin (Self)"
                dir_color = QColor("#c084fc")
            elif direction.is_uncertain:
                dir_str = f"Ambiguous ({az_360:+.1f}°)"
                dir_color = QColor("#f59e0b")  # Amber
            elif is_rear:
                if abs(az) <= 5.0:
                    dir_str = "Behind (180.0°)"
                    dir_color = QColor("#f43f5e")  # Rose
                elif az_360 < 0.0:
                    dir_str = f"Rear-Left ({az_360:.1f}°)"
                    dir_color = QColor("#f59e0b")  # Amber
                else:
                    dir_str = f"Rear-Right (+{az_360:.1f}°)"
                    dir_color = QColor("#f97316")  # Orange
            elif abs(az) <= 5.0:
                dir_str = f"Ahead ({az:+.1f}°)"
                dir_color = QColor("#22d3ee")  # Cyan
            elif az < -5.0:
                dir_str = f"Left ({az:.1f}°)"
                dir_color = QColor("#38bdf8")  # Sky Blue
            else:
                dir_str = f"Right (+{az:.1f}°)"
                dir_color = QColor("#34d399")  # Emerald

        else:
            itd_str = "N/A"
            conf_str = "N/A"
            if event.channel_bias <= -0.2:
                dir_str = f"Left ({int(abs(event.channel_bias)*100)}%)"
                dir_color = QColor("#38bdf8")
            elif event.channel_bias >= 0.2:
                dir_str = f"Right ({int(abs(event.channel_bias)*100)}%)"
                dir_color = QColor("#34d399")
            else:
                dir_str = "Ahead (0°)"
                dir_color = QColor("#22d3ee")

        id_item = QTableWidgetItem(event.event_id)
        type_item = QTableWidgetItem(type_str)
        time_item = QTableWidgetItem(time_str)
        peak_item = QTableWidgetItem(f"{event.peak_db:4.1f} dB")
        dir_item = QTableWidgetItem(dir_str)
        itd_item = QTableWidgetItem(itd_str)
        conf_item = QTableWidgetItem(conf_str)

        id_item.setForeground(QColor("#94a3b8"))
        type_item.setForeground(type_color)
        time_item.setForeground(QColor("#cbd5e1"))
        peak_item.setForeground(QColor("#fbbf24"))
        dir_item.setForeground(dir_color)
        itd_item.setForeground(QColor("#94a3b8"))
        conf_item.setForeground(QColor("#38bdf8"))

        for col, item in enumerate([id_item, type_item, time_item, peak_item, dir_item, itd_item, conf_item]):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(0, col, item)

        # Truncate oldest rows
        while self.table.rowCount() > self.max_records:
            self.table.removeRow(self.table.rowCount() - 1)
