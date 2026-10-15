"""Application runtime and lifecycle manager for PySide6."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from src.audio_capture.service import AudioCaptureService
from src.config.settings import AppConfig
from src.ui.main_window import LevelMeterWindow

if sys.platform == "win32" and not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED for clean Qt OleInitialize

logger = logging.getLogger(__name__)

DARK_STYLESHEET = """
QMainWindow {
    background-color: #090d16;
}

QWidget#centralWidget {
    background-color: #090d16;
}

QLabel {
    color: #e2e8f0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
}

/* Card Containers */
QFrame[card="true"] {
    background-color: #111827;
    border: 1px solid #1f293d;
    border-radius: 8px;
}

/* Push Buttons */
QPushButton {
    background-color: #1e293b;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 14px;
    font-family: 'Segoe UI', sans-serif;
    font-size: 11px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #293548;
    border-color: #475569;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #0f172a;
    border-color: #64748b;
}

QPushButton:disabled {
    background-color: #0f172a;
    color: #475569;
    border-color: #1e293b;
}

/* Combo Boxes */
QComboBox {
    background-color: #0f172a;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 10px;
    font-family: 'Segoe UI', sans-serif;
    font-size: 11px;
    font-weight: 500;
}

QComboBox:hover {
    border-color: #38bdf8;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #1e293b;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}

QComboBox QAbstractItemView {
    background-color: #0f172a;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 6px;
    selection-background-color: #1e293b;
    selection-color: #38bdf8;
    padding: 4px;
    outline: none;
}

/* Spin Boxes */
QDoubleSpinBox, QSpinBox {
    background-color: #0f172a;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 5px;
    padding: 4px 6px;
    font-family: 'Consolas', 'Segoe UI', monospace;
    font-size: 11px;
    font-weight: 600;
}

QDoubleSpinBox:hover, QSpinBox:hover {
    border-color: #38bdf8;
}

QDoubleSpinBox:focus, QSpinBox:focus {
    border-color: #0284c7;
}

/* Checkboxes */
QCheckBox {
    color: #cbd5e1;
    font-family: 'Segoe UI', sans-serif;
    font-size: 11px;
    spacing: 7px;
}

QCheckBox:hover {
    color: #ffffff;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #475569;
    border-radius: 3px;
    background-color: #0f172a;
}

QCheckBox::indicator:hover {
    border-color: #38bdf8;
}

QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
}

/* Sliders */
QSlider::groove:horizontal {
    height: 6px;
    background-color: #1e293b;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background-color: #0284c7;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #38bdf8;
    border: 2px solid #0f172a;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background-color: #7dd3fc;
}

/* Minimalist Scrollbars */
QScrollBar:vertical {
    border: none;
    background-color: transparent;
    width: 6px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    min-height: 24px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background-color: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    height: 0px;
}
"""


def run_gui_application(config: Optional[AppConfig] = None) -> int:
    """Initialize and run the PySide6 level visualizer application."""
    if config is None:
        config = AppConfig.load_from_file("config.json")

    # Configure High-DPI attributes
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setStyleSheet(DARK_STYLESHEET)

    # Initialize Audio Capture Service
    capture_service = AudioCaptureService(
        audio_config=config.audio,
        meter_config=config.meter,
        detector_config=config.detector,
        spatial_config=config.spatial,
    )

    # Create and display UI
    window = LevelMeterWindow(config=config, capture_service=capture_service)
    window.show()

    # Start audio capture
    capture_service.start()

    logger.info("Application event loop entering exec().")
    exit_code = app.exec()
    logger.info("Application exited with code %s.", exit_code)
    return exit_code
