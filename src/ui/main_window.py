"""Main desktop window for audio level visualization and spatial acoustic monitoring."""

from __future__ import annotations

import logging
import queue
from typing import Optional, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.audio_capture.process_scanner import (
    find_process_by_pid,
    list_active_audio_processes,
)
from src.audio_capture.service import AudioCaptureService
from src.audio_capture.types import CaptureState, DeviceInfo, StatusEvent
from src.audio_processing.types import LevelMetrics
from src.config.presets import BUILTIN_PRESETS, GamePreset, get_all_presets, get_preset_by_name
from src.config.settings import AppConfig
from src.direction_estimation.calibrator import (
    CalibrationResult,
    CalibrationState,
    WeaponCalibrator,
)
from src.event_classification.types import SoundType
from src.event_detection.types import SoundEvent
from src.ui.components.event_log import EventLogWidget
from src.ui.components.meter_bar import MeterBar
from src.ui.radar_overlay import RadarOverlayWindow


logger = logging.getLogger(__name__)

STATUS_STYLES = {
    CaptureState.ACTIVE: "background-color: #064e3b; color: #34d399; border: 1px solid #059669;",
    CaptureState.SILENCE: "background-color: #451a03; color: #fbbf24; border: 1px solid #b45309;",
    CaptureState.RECONNECTING: "background-color: #431407; color: #fb923c; border: 1px solid #ea580c;",
    CaptureState.ERROR: "background-color: #4c0519; color: #f87171; border: 1px solid #e11d48;",
    CaptureState.STOPPED: "background-color: #1e293b; color: #94a3b8; border: 1px solid #475569;",
    CaptureState.STARTING: "background-color: #1e1b4b; color: #818cf8; border: 1px solid #4f46e5;",
}

EVENT_FLASH_IDLE = "background-color: #0f172a; color: #64748b; border: 1px solid #1e293b; border-radius: 6px; padding: 4px 14px; font-weight: 700;"
EVENT_FLASH_ACTIVE = "background-color: #083344; color: #38bdf8; border: 1px solid #0284c7; border-radius: 6px; padding: 4px 14px; font-weight: 700;"
EVENT_FLASH_SELF = "background-color: #3b0764; color: #d8b4fe; border: 1px solid #a855f7; border-radius: 6px; padding: 4px 14px; font-weight: 700;"

MAIN_WINDOW_STYLESHEET = """
QMainWindow {
    background-color: #090d16;
}
QWidget#centralWidget {
    background-color: #090d16;
}
QTabWidget::pane {
    background-color: #0b1120;
    border: 1px solid #1e293b;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background-color: #111827;
    color: #94a3b8;
    border: 1px solid #1e293b;
    border-bottom: none;
    padding: 9px 24px;
    font-family: 'Segoe UI', sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: #0b1120;
    color: #38bdf8;
    border: 1px solid #0284c7;
    border-bottom: 2px solid #0284c7;
}
QTabBar::tab:hover:!selected {
    background-color: #1e293b;
    color: #f1f5f9;
}
QFrame.card {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
}
QFrame.subcard {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 6px;
}
QComboBox {
    background-color: #0f172a;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
}
QComboBox:hover {
    border: 1px solid #0284c7;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #0f172a;
    color: #f1f5f9;
    selection-background-color: #1e293b;
    selection-color: #38bdf8;
    padding: 4px;
    border: 1px solid #334155;
}
QSpinBox, QDoubleSpinBox {
    background-color: #0f172a;
    color: #f1f5f9;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}
QSpinBox:hover, QDoubleSpinBox:hover {
    border: 1px solid #0284c7;
}
QCheckBox {
    color: #e2e8f0;
    font-size: 11px;
    font-weight: 600;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #475569;
    border-radius: 4px;
    background-color: #0f172a;
}
QCheckBox::indicator:hover {
    border: 1px solid #0284c7;
}
QCheckBox::indicator:checked {
    background-color: #0284c7;
    border: 1px solid #38bdf8;
}
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
    border: 1px solid #0284c7;
    width: 14px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #7dd3fc;
}
QToolTip {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #0284c7;
    padding: 8px 12px;
    font-size: 11px;
    border-radius: 6px;
}
QScrollBar:vertical {
    background-color: #0b1120;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #334155;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background-color: #0284c7;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


class LevelMeterWindow(QMainWindow):
    """Main desktop control panel for spatial audio tracking and radar overlay configuration."""

    def __init__(
        self,
        config: AppConfig,
        capture_service: AudioCaptureService,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.capture_service = capture_service

        self.calibrator = WeaponCalibrator(duration_s=6.0, target_shots=3)
        self.radar_overlay = RadarOverlayWindow()
        self.radar_overlay.set_spatial_mode(self.config.spatial.spatial_mode)
        self.radar_overlay.set_mouse_compass_enabled(self.config.spatial.enable_mouse_compass)
        self.radar_overlay.set_mouse_sensitivity(self.config.spatial.mouse_yaw_sensitivity)
        self.radar_overlay.set_cluster_lifetime(self.config.spatial.cluster_lifetime_s)
        self.radar_overlay.set_hud_diameter(self.config.overlay_diameter)
        self.radar_overlay.set_hud_opacity(self.config.overlay_opacity)
        self.radar_overlay.set_locked(self.config.overlay_locked)
        self.radar_overlay.set_radar_type(getattr(self.config, "overlay_type", "rays"))
        self.radar_overlay.set_show_sound_circles(getattr(self.config, "show_sound_circles", True))
        self.radar_overlay.set_show_sound_numbers(getattr(self.config, "show_sound_numbers", True))

        if self.config.overlay_x is not None and self.config.overlay_y is not None:
            self.radar_overlay.move(self.config.overlay_x, self.config.overlay_y)

        self.radar_overlay.position_changed.connect(self._on_overlay_position_changed)

        if self.config.overlay_visible:
            self.radar_overlay.show()
        else:
            self.radar_overlay.hide()

        self._suppress_preset_change_signals: bool = False

        self.setWindowTitle("Spatial Audio Radar")
        init_w = max(960, getattr(self.config, "window_width", 960))
        init_h = max(880, getattr(self.config, "window_height", 880))
        self.setMinimumSize(840, 760)
        self.resize(init_w, init_h)
        self.setStyleSheet(MAIN_WINDOW_STYLESHEET)

        self._init_ui()
        self._init_timer()
        self._refresh_device_list()
        self._refresh_app_list()
        self._refresh_preset_combo()


    def _create_card(self, title: str, subtitle: str) -> Tuple[QFrame, QVBoxLayout]:
        """Construct a standardized UI card with a prominent section title and subtitle."""
        card = QFrame()
        card.setProperty("class", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        header_container = QVBoxLayout()
        header_container.setSpacing(2)

        hdr_lbl = QLabel(title.upper())
        hdr_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        hdr_lbl.setStyleSheet("color: #f8fafc; letter-spacing: 0.6px;")
        header_container.addWidget(hdr_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setFont(QFont("Segoe UI", 8))
        sub_lbl.setStyleSheet("color: #64748b;")
        header_container.addWidget(sub_lbl)

        card_layout.addLayout(header_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #1e293b; max-height: 1px;")
        card_layout.addWidget(sep)

        return card, card_layout

    def _init_ui(self) -> None:
        """Construct the reorganized tabbed window interface."""
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(18, 16, 18, 16)
        root_layout.setSpacing(12)

        # 1. Persistent Top Header Bar
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title_container = QVBoxLayout()
        title_container.setSpacing(1)

        title_label = QLabel("SPATIAL AUDIO RADAR")
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #f8fafc; letter-spacing: 0.8px;")
        title_container.addWidget(title_label)

        sub_title = QLabel("LOW-LATENCY ESPORTS ACOUSTIC DSP")
        sub_title.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        sub_title.setStyleSheet("color: #64748b; letter-spacing: 0.5px;")
        title_container.addWidget(sub_title)

        header_layout.addLayout(title_container)
        header_layout.addStretch()

        # Telemetry flash indicator badge
        self.event_flash_badge = QLabel("IDLE")
        self.event_flash_badge.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.event_flash_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.event_flash_badge.setFixedHeight(30)
        self.event_flash_badge.setMinimumWidth(180)
        self.event_flash_badge.setStyleSheet(EVENT_FLASH_IDLE)
        self.event_flash_badge.setToolTip(
            "Live Telemetry Alert\n"
            "Displays the latest acoustic transient bearing and dBFS peak.\n"
            "Flashes in real time when directional gunshots or footsteps are detected."
        )
        header_layout.addWidget(self.event_flash_badge)

        # Service lifecycle status badge
        self.status_badge = QLabel(CaptureState.STARTING.value)
        self.status_badge.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setFixedHeight(30)
        self.status_badge.setMinimumWidth(100)
        self.status_badge.setStyleSheet(
            f"border-radius: 6px; padding: 2px 12px; {STATUS_STYLES[CaptureState.STARTING]}"
        )
        self.status_badge.setToolTip(
            "Capture Engine Status\n"
            "Indicates the operational state of the Windows WASAPI audio loopback thread."
        )
        header_layout.addWidget(self.status_badge)

        root_layout.addLayout(header_layout)

        # 2. Master Quick Action Bar
        action_bar = QFrame()
        action_bar.setStyleSheet("background-color: #111827; border: 1px solid #1e293b; border-radius: 8px;")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(14, 8, 14, 8)
        action_layout.setSpacing(10)

        self.hud_toggle_btn = QPushButton("Hide Overlay")
        self.hud_toggle_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #0284c7;
                color: white;
                font-weight: 700;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #0369a1; }
            """
        )
        self.hud_toggle_btn.setToolTip(
            "Toggle Radar HUD Visibility\n"
            "Show or hide the transparent in-game radar overlay on your screen."
        )
        self.hud_toggle_btn.clicked.connect(self._on_toggle_hud_visibility)
        action_layout.addWidget(self.hud_toggle_btn)

        self.hud_lock_btn = QPushButton("Locked (Click-Through)")
        self.hud_lock_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #065f46;
                color: #34d399;
                font-weight: 700;
                border: 1px solid #059669;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #047857; }
            """
        )
        self.hud_lock_btn.setToolTip(
            "Click-Through Lock State\n"
            "- Locked: Game clicks pass directly through the radar overlay without interruption.\n"
            "- Unlocked: Allows dragging and repositioning the radar on your monitor."
        )
        self.hud_lock_btn.clicked.connect(self._on_toggle_hud_lock)
        action_layout.addWidget(self.hud_lock_btn)

        self.toggle_btn = QPushButton("Pause Capture")
        self.toggle_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e293b;
                color: #e2e8f0;
                font-weight: 700;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #334155; color: white; }
            """
        )
        self.toggle_btn.setToolTip(
            "Audio Capture Service Controller\n"
            "Temporarily suspend or resume audio capture without closing the application."
        )
        self.toggle_btn.clicked.connect(self._on_toggle_capture)
        action_layout.addWidget(self.toggle_btn)

        action_layout.addStretch()

        self.app_quick_status = QLabel("Target: All System Audio (Master Mix)")
        self.app_quick_status.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.app_quick_status.setStyleSheet("color: #38bdf8;")
        action_layout.addWidget(self.app_quick_status)

        root_layout.addWidget(action_bar)

        # 3. Main Navigation Tab Widget
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, stretch=1)

        # Tab 1: Radar HUD
        self._init_tab_radar_hud()

        # Tab 2: Audio & Routing
        self._init_tab_audio_routing()

        # Tab 3: Tuning & Calibration
        self._init_tab_tuning_calibration()

        # Tab 4: Telemetry Log
        self._init_tab_telemetry_log()

        # 4. Status Footer
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        self.log_label = QLabel("Ready. Low-latency acoustic engine initialized.")
        self.log_label.setStyleSheet("color: #64748b; font-size: 11px;")
        footer_layout.addWidget(self.log_label, stretch=1)

        rate_badge = QLabel(
            f"{self.config.audio.sample_rate // 1000} kHz / {self.config.audio.block_size} smp"
        )
        rate_badge.setStyleSheet(
            "color: #94a3b8; font-size: 11px; background-color: #111827; padding: 3px 8px; border-radius: 4px; border: 1px solid #1e293b;"
        )
        footer_layout.addWidget(rate_badge)

        root_layout.addLayout(footer_layout)

    # -------------------------------------------------------------------------
    # Tab 1: Radar HUD
    # -------------------------------------------------------------------------
    def _init_tab_radar_hud(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        tab = QWidget()
        tab.setStyleSheet("background-color: transparent;")
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(14, 14, 14, 14)
        tab_layout.setSpacing(12)

        # Card 1: Overlay Display Configuration
        card_disp, disp_layout = self._create_card(
            title="Overlay Display Settings",
            subtitle="Configure radar display geometry, transparency, and firing visuals",
        )

        grid_disp = QGridLayout()
        grid_disp.setHorizontalSpacing(14)
        grid_disp.setVerticalSpacing(10)

        # Row 0: Mode selection
        lbl_mode = QLabel("Display Geometry:")
        lbl_mode.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_mode, 0, 0)

        self.hud_mode_combo = QComboBox()
        self.hud_mode_combo.addItem("180° Stereo Forward Arc (Recommended)", "stereo_180")
        self.hud_mode_combo.addItem("360° Polar Surround", "hrtf_360")
        if self.config.spatial.spatial_mode == "stereo_180":
            self.hud_mode_combo.setCurrentIndex(0)
        else:
            self.hud_mode_combo.setCurrentIndex(1)
        self.hud_mode_combo.setToolTip(
            "Radar Coordinate Geometry\n"
            "- 180° Stereo Forward Arc (Recommended): Maps sounds cleanly across your forward vision (0° Ahead = Crosshair).\n"
            "  Zero front-to-back ambiguity or false rear flipping. Ideal for competitive FPS gaming.\n"
            "- 360° Polar Surround: Full 360° polar radar circle with front and rear hemispheres for 3D audio."
        )
        self.hud_mode_combo.currentIndexChanged.connect(self._on_hud_mode_changed)
        grid_disp.addWidget(self.hud_mode_combo, 0, 1)

        # Row 1: Radar Style
        lbl_style = QLabel("Radar Style:")
        lbl_style.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_style, 1, 0)

        self.radar_type_combo = QComboBox()
        self.radar_type_combo.addItem("Tactical Rays (Straight Lines)", "rays")
        self.radar_type_combo.addItem("Sector Threat Zones (Curved Arcs)", "zones")
        if getattr(self.config, "overlay_type", "rays") == "zones":
            self.radar_type_combo.setCurrentIndex(1)
        else:
            self.radar_type_combo.setCurrentIndex(0)
        self.radar_type_combo.setToolTip(
            "Radar Visualization Style\n"
            "- Tactical Rays: Classic straight directional line rays drawn towards sound origins.\n"
            "- Sector Threat Zones: Renders curved threat area zones showing estimated origin sectors."
        )
        self.radar_type_combo.currentIndexChanged.connect(self._on_radar_type_changed)
        grid_disp.addWidget(self.radar_type_combo, 1, 1)

        # Row 2: Radar Scale / Diameter slider
        lbl_size = QLabel("Radar Scale:")
        lbl_size.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_size, 2, 0)

        size_container = QHBoxLayout()
        size_container.setSpacing(10)

        self.hud_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.hud_size_slider.setRange(200, 600)
        self.hud_size_slider.setValue(self.config.overlay_diameter)
        self.hud_size_slider.setToolTip(
            "Radar HUD Scale\n"
            "Adjusts physical diameter of the circular radar overlay (200px to 600px)."
        )
        self.hud_size_slider.valueChanged.connect(self._on_hud_size_changed)
        size_container.addWidget(self.hud_size_slider)

        self.hud_size_px = QLabel(f"{self.hud_size_slider.value()} px")
        self.hud_size_px.setStyleSheet("color: #38bdf8; font-weight: bold; min-width: 48px;")
        size_container.addWidget(self.hud_size_px)

        grid_disp.addLayout(size_container, 2, 1)

        # Row 3: Opacity slider
        lbl_op = QLabel("Overlay Opacity:")
        lbl_op.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_op, 3, 0)

        opacity_container = QHBoxLayout()
        opacity_container.setSpacing(10)

        self.hud_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.hud_opacity_slider.setRange(20, 100)
        self.hud_opacity_slider.setValue(int(self.config.overlay_opacity * 100))
        self.hud_opacity_slider.setToolTip(
            "Overlay Transparency\n"
            "Adjusts background glass opacity of the floating radar HUD (20% subtle to 100% solid)."
        )
        self.hud_opacity_slider.valueChanged.connect(self._on_hud_opacity_changed)
        opacity_container.addWidget(self.hud_opacity_slider)

        self.hud_opacity_pct = QLabel(f"{self.hud_opacity_slider.value()}%")
        self.hud_opacity_pct.setStyleSheet("color: #38bdf8; font-weight: bold; min-width: 32px;")
        opacity_container.addWidget(self.hud_opacity_pct)

        grid_disp.addLayout(opacity_container, 3, 1)

        # Row 4: Self-Sound Pulse
        lbl_self = QLabel("Player Weapon Ripple:")
        lbl_self.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_self, 4, 0)

        self.hud_self_cb = QCheckBox("Pulse Purple Shockwave from Reticle on Firing")
        self.hud_self_cb.setChecked(True)
        self.hud_self_cb.setToolTip(
            "Player Weapon Visual Pulse\n"
            "Displays an expanding purple halo centered on the player reticle when you fire your weapon,\n"
            "confirming that self-sound suppression is actively functioning."
        )
        self.hud_self_cb.toggled.connect(self._on_hud_self_toggled)
        grid_disp.addWidget(self.hud_self_cb, 4, 1)

        # Row 5: Individual Sound Mini-Circles
        lbl_circles = QLabel("Sound Mini-Circles:")
        lbl_circles.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_circles, 5, 0)

        self.show_circles_cb = QCheckBox("Show Mini-Circles for Individual Sounds")
        self.show_circles_cb.setChecked(getattr(self.config, "show_sound_circles", True))
        self.show_circles_cb.setToolTip(
            "Individual Sound Markers\n"
            "When checked, renders mini-circle pips and transient shockwaves for each sound.\n"
            "Uncheck to hide all mini-circles and display clean threat zones or rays only."
        )
        self.show_circles_cb.toggled.connect(self._on_toggle_sound_circles)
        grid_disp.addWidget(self.show_circles_cb, 5, 1)

        # Row 6: Numeric Threat Indicators (Numbers)
        lbl_numbers = QLabel("Sound Numbers:")
        lbl_numbers.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_disp.addWidget(lbl_numbers, 6, 0)

        self.show_numbers_cb = QCheckBox("Show Numbers (Burst Multipliers & Metrics)")
        self.show_numbers_cb.setChecked(getattr(self.config, "show_sound_numbers", True))
        self.show_numbers_cb.setToolTip(
            "Numeric Overlay Indicators\n"
            "When checked, displays burst multiplier numbers (x2, x3), dB levels, and angle numbers.\n"
            "Uncheck to hide all numbers on the radar overlay for a minimal tactical view."
        )
        self.show_numbers_cb.toggled.connect(self._on_toggle_sound_numbers)
        grid_disp.addWidget(self.show_numbers_cb, 6, 1)

        disp_layout.addLayout(grid_disp)
        tab_layout.addWidget(card_disp)

        # Card 2: Aim Tracking & Compass Orientation
        card_track, track_layout = self._create_card(
            title="Aim Tracking & Orientation",
            subtitle="Crosshair-anchored screen lock vs. hardware mouse gyro compass",
        )

        grid_track = QGridLayout()
        grid_track.setHorizontalSpacing(14)
        grid_track.setVerticalSpacing(10)

        # Row 0: Compass Toggle & Reset
        lbl_engine = QLabel("Tracking Mode:")
        lbl_engine.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_track.addWidget(lbl_engine, 0, 0)

        mode_btn_box = QHBoxLayout()
        mode_btn_box.setSpacing(10)

        self.mouse_compass_cb = QCheckBox("Enable Mouse Gyro Compass (Compensate In-Game Turns)")
        self.mouse_compass_cb.setChecked(self.config.spatial.enable_mouse_compass)
        self.mouse_compass_cb.setToolTip(
            "Aim Orientation Engine\n"
            "- Unchecked (Recommended Direct Mode): Radar is locked directly to your screen crosshair with zero drift.\n"
            "  The top of the radar (0°) always represents where you are aiming.\n"
            "- Checked (Mouse Gyro): Rotates threat blips using raw mouse input to keep them fixed in world space."
        )
        self.mouse_compass_cb.toggled.connect(self._on_mouse_compass_toggled)
        mode_btn_box.addWidget(self.mouse_compass_cb)

        self.reset_yaw_btn = QPushButton("Reset Heading (0°)")
        self.reset_yaw_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                font-weight: 600;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: #334155; color: white; }
            """
        )
        self.reset_yaw_btn.setToolTip(
            "Reset Gyro Heading\n"
            "Instantly snaps gyro compass heading to 0° (Center Ahead) and re-synchronizes all active threat clusters."
        )
        self.reset_yaw_btn.clicked.connect(self._on_reset_yaw_clicked)
        mode_btn_box.addWidget(self.reset_yaw_btn)

        grid_track.addLayout(mode_btn_box, 0, 1)

        # Row 1: Tracking Status Note
        lbl_stat = QLabel("Tracking Status:")
        lbl_stat.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_track.addWidget(lbl_stat, 1, 0)

        self.calib_mouse_status = QLabel("Direct Screen Mode (Locked to crosshair, zero mouse drift)")
        self.calib_mouse_status.setStyleSheet("color: #34d399; font-weight: 600;")
        grid_track.addWidget(self.calib_mouse_status, 1, 1)

        # Row 2: Threat Ray Persistence
        lbl_per = QLabel("Threat Ray Persistence:")
        lbl_per.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_track.addWidget(lbl_per, 2, 0)

        self.persistence_spinbox = QDoubleSpinBox()
        self.persistence_spinbox.setRange(2.0, 30.0)
        self.persistence_spinbox.setSingleStep(1.0)
        self.persistence_spinbox.setValue(self.config.spatial.cluster_lifetime_s)
        self.persistence_spinbox.setSuffix(" seconds")
        self.persistence_spinbox.setToolTip(
            "Threat Memory Lifespan\n"
            "How long an enemy firing ray remains visible on the radar after shooting ceases (2.0s to 30.0s).\n"
            "Higher values help track snipers or sporadic firefights."
        )
        self.persistence_spinbox.valueChanged.connect(self._on_persistence_changed)
        grid_track.addWidget(self.persistence_spinbox, 2, 1)

        # Row 3: Mouse Calibration (when gyro is active)
        lbl_sens = QLabel("Mouse Gyro Sensitivity:")
        lbl_sens.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_track.addWidget(lbl_sens, 3, 0)

        calib_row = QHBoxLayout()
        calib_row.setSpacing(10)

        self.mouse_sens_spinbox = QDoubleSpinBox()
        self.mouse_sens_spinbox.setRange(0.005, 0.500)
        self.mouse_sens_spinbox.setSingleStep(0.005)
        self.mouse_sens_spinbox.setDecimals(3)
        self.mouse_sens_spinbox.setValue(self.config.spatial.mouse_yaw_sensitivity)
        self.mouse_sens_spinbox.setSuffix(" °/count")
        self.mouse_sens_spinbox.setToolTip(
            "Mouse Hardware Sensitivity\n"
            "Degrees of in-game character turn per raw mouse hardware count.\n"
            "Use the Calibrate button to set this automatically."
        )
        self.mouse_sens_spinbox.valueChanged.connect(self._on_mouse_sens_changed)
        calib_row.addWidget(self.mouse_sens_spinbox)

        self.calib_mouse_btn = QPushButton("Calibrate 360° Turn")
        self.calib_mouse_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                font-weight: 600;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: #334155; color: white; }
            """
        )
        self.calib_mouse_btn.setToolTip(
            "Interactive Sensitivity Calibration\n"
            "Click to start, execute one precise 360° turn in-game, then click finish.\n"
            "Calculates your exact degrees per count."
        )
        self.calib_mouse_btn.clicked.connect(self._on_calibrate_mouse_clicked)
        calib_row.addWidget(self.calib_mouse_btn)

        grid_track.addLayout(calib_row, 3, 1)

        track_layout.addLayout(grid_track)
        tab_layout.addWidget(card_track)

        tab_layout.addStretch()
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "RADAR HUD")

    # -------------------------------------------------------------------------
    # Tab 2: Audio & Routing
    # -------------------------------------------------------------------------
    def _init_tab_audio_routing(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        tab = QWidget()
        tab.setStyleSheet("background-color: transparent;")
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(14, 14, 14, 14)
        tab_layout.setSpacing(12)

        # Card 1: Application Process Isolation
        card_app, app_layout = self._create_card(
            title="Game Isolation & Audio Routing",
            subtitle="Directly tap game audio streams while ignoring Discord, voice chat, and music",
        )

        grid_app = QGridLayout()
        grid_app.setHorizontalSpacing(14)
        grid_app.setVerticalSpacing(10)

        # Row 0: Target Application
        lbl_app = QLabel("Target Application:")
        lbl_app.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_app.addWidget(lbl_app, 0, 0)

        app_select_box = QHBoxLayout()
        app_select_box.setSpacing(10)

        self.app_combo = QComboBox()
        self.app_combo.setToolTip(
            "Application Process Isolation\n"
            "Select your active game process (e.g. TslGame.exe for PUBG).\n"
            "Audio will be captured exclusively from this process, completely filtering out\n"
            "Discord voice calls, Spotify music, browser videos, and Windows alert chimes."
        )
        self.app_combo.currentIndexChanged.connect(self._on_app_selection_changed)
        app_select_box.addWidget(self.app_combo, stretch=1)

        self.refresh_apps_btn = QPushButton("Refresh List")
        self.refresh_apps_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #0284c7;
                color: white;
                font-weight: 600;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #0369a1; }
            """
        )
        self.refresh_apps_btn.setToolTip("Refresh list of running applications currently producing audio.")
        self.refresh_apps_btn.clicked.connect(self._refresh_app_list)
        app_select_box.addWidget(self.refresh_apps_btn)

        grid_app.addLayout(app_select_box, 0, 1)

        # Row 1: Target Status
        lbl_iso = QLabel("Isolation Status:")
        lbl_iso.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_app.addWidget(lbl_iso, 1, 0)

        self.target_status_label = QLabel("Initializing target selection...")
        self.target_status_label.setStyleSheet("color: #38bdf8; font-weight: 600;")
        grid_app.addWidget(self.target_status_label, 1, 1)

        # Row 2: Output Endpoint
        lbl_dev = QLabel("Audio Output Device:")
        lbl_dev.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_app.addWidget(lbl_dev, 2, 0)

        dev_select_box = QHBoxLayout()
        dev_select_box.setSpacing(10)

        self.device_combo = QComboBox()
        self.device_combo.setToolTip(
            "Playback Endpoint\n"
            "Select the physical audio output device (e.g. Headphones or DAC) being captured."
        )
        self.device_combo.currentIndexChanged.connect(self._on_device_selection_changed)
        dev_select_box.addWidget(self.device_combo, stretch=1)

        refresh_dev_btn = QPushButton("Refresh Devices")
        refresh_dev_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                font-weight: 600;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #334155; color: white; }
            """
        )
        refresh_dev_btn.setToolTip("Rescan Windows audio playback endpoints.")
        refresh_dev_btn.clicked.connect(self._refresh_device_list)
        dev_select_box.addWidget(refresh_dev_btn)

        grid_app.addLayout(dev_select_box, 2, 1)

        app_layout.addLayout(grid_app)
        tab_layout.addWidget(card_app)

        # Card 2: Live Level Meters
        card_mtr, mtr_layout = self._create_card(
            title="Live Hardware Channel Meters",
            subtitle="Dual-channel acoustic monitor with peak hold and true digital dBFS ballistics",
        )

        self.left_meter = MeterBar(channel_label="L", config=self.config.meter)
        self.right_meter = MeterBar(channel_label="R", config=self.config.meter)

        mtr_layout.addWidget(self.left_meter)
        mtr_layout.addWidget(self.right_meter)

        tab_layout.addWidget(card_mtr)

        # Card 3: Acoustic Configuration & Best Practices
        card_tips, tips_layout = self._create_card(
            title="Acoustic Configuration & Best Practices",
            subtitle="Essential Windows and in-game audio setup guidelines for optimal directional accuracy",
        )

        tips_grid = QGridLayout()
        tips_grid.setHorizontalSpacing(14)
        tips_grid.setVerticalSpacing(10)

        # Tip 1: Windows Mono
        lbl_tip1_title = QLabel("1. Windows Mono Audio:")
        lbl_tip1_title.setStyleSheet("color: #38bdf8; font-weight: 700; min-width: 160px;")
        tips_grid.addWidget(lbl_tip1_title, 0, 0)

        lbl_tip1_desc = QLabel(
            "Ensure 'Mono audio' is turned OFF in Windows Settings -> Accessibility -> Audio. "
            "Directional spatial calculation requires distinct Left and Right stereo channels."
        )
        lbl_tip1_desc.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        lbl_tip1_desc.setWordWrap(True)
        tips_grid.addWidget(lbl_tip1_desc, 0, 1)

        # Tip 2: In-Game Output
        lbl_tip2_title = QLabel("2. In-Game Output:")
        lbl_tip2_title.setStyleSheet("color: #38bdf8; font-weight: 700; min-width: 160px;")
        tips_grid.addWidget(lbl_tip2_title, 1, 0)

        lbl_tip2_desc = QLabel(
            "Set in-game audio output to 'Stereo' or 'Headphones'. Avoid setting games to mono or "
            "enabling external virtual surround sound effects that blur interaural timing differences."
        )
        lbl_tip2_desc.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        lbl_tip2_desc.setWordWrap(True)
        tips_grid.addWidget(lbl_tip2_desc, 1, 1)

        # Tip 3: Headphone Format
        lbl_tip3_title = QLabel("3. Headphone Format:")
        lbl_tip3_title.setStyleSheet("color: #38bdf8; font-weight: 700; min-width: 160px;")
        tips_grid.addWidget(lbl_tip3_title, 2, 0)

        lbl_tip3_desc = QLabel(
            "Standard format of 48,000 Hz, 24-bit or 16-bit stereo is recommended. Avoid digital "
            "master volume boosting that drives audio into 0 dBFS clipping."
        )
        lbl_tip3_desc.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        lbl_tip3_desc.setWordWrap(True)
        tips_grid.addWidget(lbl_tip3_desc, 2, 1)

        tips_layout.addLayout(tips_grid)
        tab_layout.addWidget(card_tips)

        tab_layout.addStretch()
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "AUDIO & ROUTING")

    # -------------------------------------------------------------------------
    # Tab 3: Tuning & Calibration
    # -------------------------------------------------------------------------
    def _init_tab_tuning_calibration(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        tab = QWidget()
        tab.setStyleSheet("background-color: transparent;")
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(14, 14, 14, 14)
        tab_layout.setSpacing(12)

        # Card 0: Game Audio Profiles & Presets
        card_preset, preset_layout = self._create_card(
            title="Game Audio Profiles & Presets",
            subtitle="Pre-tuned DSP settings for PUBG, Valorant, CS2, and Apex, or save your own custom profiles",
        )

        preset_row = QHBoxLayout()
        preset_row.setSpacing(10)

        lbl_p = QLabel("Active Profile:")
        lbl_p.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        preset_row.addWidget(lbl_p)

        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
                min-width: 220px;
                font-weight: 600;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #0f172a;
                color: #f8fafc;
                selection-background-color: #0284c7;
            }
            """
        )
        self.preset_combo.setToolTip(
            "Game Audio Profiles\n"
            "Select a pre-tuned profile for your game, or choose a custom user-saved preset.\n"
            "Automatically updates all threshold and spatial settings."
        )
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.preset_combo)

        self.save_preset_btn = QPushButton("Save Preset As...")
        self.save_preset_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                font-weight: 600;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #334155; color: white; }
            """
        )
        self.save_preset_btn.setToolTip(
            "Save Custom Profile\n"
            "Save all current threshold and radar parameters as a new named custom profile."
        )
        self.save_preset_btn.clicked.connect(self._on_save_preset_clicked)
        preset_row.addWidget(self.save_preset_btn)

        self.delete_preset_btn = QPushButton("Delete Preset")
        self.delete_preset_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e293b;
                color: #f87171;
                font-weight: 600;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #7f1d1d; color: white; }
            QPushButton:disabled { color: #475569; border-color: #1e293b; }
            """
        )
        self.delete_preset_btn.setToolTip(
            "Delete Profile\n"
            "Delete the currently selected custom profile (built-in profiles cannot be deleted)."
        )
        self.delete_preset_btn.clicked.connect(self._on_delete_preset_clicked)
        preset_row.addWidget(self.delete_preset_btn)

        preset_row.addStretch()
        preset_layout.addLayout(preset_row)

        self.preset_desc_lbl = QLabel("")
        self.preset_desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        preset_layout.addWidget(self.preset_desc_lbl)

        tab_layout.addWidget(card_preset)

        # Card 1: Weapon Audio Calibration
        card_wpn, wpn_layout = self._create_card(
            title="Weapon Audio Calibration",
            subtitle="Isolate 1st-person weapon discharges to prevent false enemy alerts",
        )


        wpn_grid = QGridLayout()
        wpn_grid.setHorizontalSpacing(14)
        wpn_grid.setVerticalSpacing(10)

        # Row 0: Calibration Trigger
        lbl_calib = QLabel("Interactive Wizard:")
        lbl_calib.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        wpn_grid.addWidget(lbl_calib, 0, 0)

        wpn_btn_box = QHBoxLayout()
        wpn_btn_box.setSpacing(10)

        self.calibrate_btn = QPushButton("Calibrate Weapon")
        self.calibrate_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #0284c7;
                color: white;
                font-weight: 700;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #0369a1; }
            """
        )
        self.calibrate_btn.setToolTip(
            "Weapon Sound Profiler\n"
            "Click to start listening, fire 3 weapon shots in-game, and automatically\n"
            "calculate the optimal bilateral threshold for your current in-game volume."
        )
        self.calibrate_btn.clicked.connect(self._on_calibrate_clicked)
        wpn_btn_box.addWidget(self.calibrate_btn)

        self.require_mouse_cb = QCheckBox("Require LMB Click")
        self.require_mouse_cb.setChecked(self.config.spatial.require_mouse_for_self)
        self.require_mouse_cb.setToolTip(
            "Physical Mouse LMB Gating (Recommended)\n"
            "Requires physical Left Mouse Button press to classify a sound as player weapon fire.\n"
            "Prevents loud enemy shots from close range or in testing environments\n"
            "(like PUBG Sound Lab) from ever being falsely suppressed as self-sound."
        )
        self.require_mouse_cb.toggled.connect(self._on_tuning_params_changed)
        wpn_btn_box.addWidget(self.require_mouse_cb)

        wpn_btn_box.addStretch()
        wpn_grid.addLayout(wpn_btn_box, 0, 1)

        # Row 1: Calibration Status
        lbl_cstat = QLabel("Calibration Status:")
        lbl_cstat.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        wpn_grid.addWidget(lbl_cstat, 1, 0)

        self.calibrate_status = QLabel("Ready. Fire 3 shots in game to calibrate weapon threshold.")
        self.calibrate_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        wpn_grid.addWidget(self.calibrate_status, 1, 1)

        # Row 2: Bilateral Threshold & Lockout
        lbl_bila = QLabel("Bilateral Threshold:")
        lbl_bila.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        wpn_grid.addWidget(lbl_bila, 2, 0)

        wpn_param_box = QHBoxLayout()
        wpn_param_box.setSpacing(10)

        self.bilateral_spinbox = QDoubleSpinBox()
        self.bilateral_spinbox.setRange(-25.0, 0.0)
        self.bilateral_spinbox.setSingleStep(0.5)
        self.bilateral_spinbox.setValue(self.config.spatial.bilateral_self_threshold_db)
        self.bilateral_spinbox.setSuffix(" dBFS")
        self.bilateral_spinbox.setToolTip(
            "Bilateral Self-Sound Threshold\n"
            "Audio level in both ears simultaneously where a transient is identified as your weapon.\n"
            "Recommended: -4.0 dBFS (or calibrated via button above)."
        )
        self.bilateral_spinbox.valueChanged.connect(self._on_tuning_params_changed)
        wpn_param_box.addWidget(self.bilateral_spinbox)

        lbl_lock = QLabel("Echo Lockout:")
        lbl_lock.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        wpn_param_box.addWidget(lbl_lock)

        self.lockout_spinbox = QSpinBox()
        self.lockout_spinbox.setRange(40, 500)
        self.lockout_spinbox.setSingleStep(10)
        self.lockout_spinbox.setValue(int(self.config.spatial.self_echo_lockout_ms))
        self.lockout_spinbox.setSuffix(" ms")
        self.lockout_spinbox.setToolTip(
            "Weapon Echo Refractory Window\n"
            "Duration to ignore room reverberation and wall reflections after you fire your gun.\n"
            "Recommended: 180 ms."
        )
        self.lockout_spinbox.valueChanged.connect(self._on_tuning_params_changed)
        wpn_param_box.addWidget(self.lockout_spinbox)

        wpn_grid.addLayout(wpn_param_box, 2, 1)

        # Row 3: Suppression Filters
        lbl_fil = QLabel("Acoustic Suppression:")
        lbl_fil.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        wpn_grid.addWidget(lbl_fil, 3, 0)

        filter_box = QHBoxLayout()
        filter_box.setSpacing(14)

        self.suppress_self_cb = QCheckBox("Filter Self Weapon")
        self.suppress_self_cb.setChecked(self.config.spatial.suppress_self_sounds)
        self.suppress_self_cb.setToolTip(
            "Self Weapon Filtering\n"
            "When checked, your own weapon discharges will not create external blips on the radar."
        )
        self.suppress_self_cb.toggled.connect(self._on_tuning_params_changed)
        filter_box.addWidget(self.suppress_self_cb)

        self.suppress_step_cb = QCheckBox("Filter Self Footsteps")
        self.suppress_step_cb.setChecked(self.config.spatial.suppress_self_footsteps)
        self.suppress_step_cb.setToolTip(
            "Self Footstep Gating\n"
            "Suppresses centered, balanced low-level footsteps generated by your own character movement."
        )
        self.suppress_step_cb.toggled.connect(self._on_tuning_params_changed)
        filter_box.addWidget(self.suppress_step_cb)

        filter_box.addStretch()
        wpn_grid.addLayout(filter_box, 3, 1)

        wpn_layout.addLayout(wpn_grid)
        tab_layout.addWidget(card_wpn)

        # Card 2: Detector Sensitivity & Thresholds
        card_det, det_layout = self._create_card(
            title="Detector Sensitivity & Thresholds",
            subtitle="Short-Term / Long-Term Average (STA/LTA) transient trigger configuration",
        )

        grid_det = QGridLayout()
        grid_det.setHorizontalSpacing(14)
        grid_det.setVerticalSpacing(10)

        # Row 0: Ratio and Floor
        lbl_rat = QLabel("Energy Spike Ratio:")
        lbl_rat.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_det.addWidget(lbl_rat, 0, 0)

        self.ratio_spinbox = QDoubleSpinBox()
        self.ratio_spinbox.setRange(1.2, 8.0)
        self.ratio_spinbox.setSingleStep(0.1)
        self.ratio_spinbox.setValue(self.config.detector.threshold_ratio)
        self.ratio_spinbox.setSuffix(" x")
        self.ratio_spinbox.setToolTip(
            "STA/LTA Transient Ratio\n"
            "Ratio of short-term audio energy to background noise needed to trigger a detection.\n"
            "Lower = more sensitive to distant quiet shots; Higher = ignores ambient noise/wind.\n"
            "Recommended: 3.5x."
        )
        self.ratio_spinbox.valueChanged.connect(self._on_tuning_params_changed)
        grid_det.addWidget(self.ratio_spinbox, 0, 1)

        lbl_flr = QLabel("Minimum Trigger Floor:")
        lbl_flr.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_det.addWidget(lbl_flr, 0, 2)

        self.min_db_spinbox = QDoubleSpinBox()
        self.min_db_spinbox.setRange(-60.0, -10.0)
        self.min_db_spinbox.setSingleStep(1.0)
        self.min_db_spinbox.setValue(self.config.detector.min_trigger_db)
        self.min_db_spinbox.setSuffix(" dBFS")
        self.min_db_spinbox.setToolTip(
            "Noise Floor Cutoff\n"
            "Minimum sound level required to trigger any event. Sounds below this floor are ignored.\n"
            "Recommended: -45.0 dBFS."
        )
        self.min_db_spinbox.valueChanged.connect(self._on_tuning_params_changed)
        grid_det.addWidget(self.min_db_spinbox, 0, 3)

        # Row 1: Cooldown and Confidence
        lbl_cd = QLabel("Retrigger Cooldown:")
        lbl_cd.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_det.addWidget(lbl_cd, 1, 0)

        self.cooldown_spinbox = QSpinBox()
        self.cooldown_spinbox.setRange(20, 500)
        self.cooldown_spinbox.setSingleStep(10)
        self.cooldown_spinbox.setValue(int(self.config.detector.cooldown_ms))
        self.cooldown_spinbox.setSuffix(" ms")
        self.cooldown_spinbox.setToolTip(
            "Detector Debounce Window\n"
            "Minimum delay between consecutive sound triggers. Prevents rapid automatic weapon\n"
            "bursts from spamming duplicate blips.\n"
            "Recommended: 70 ms."
        )
        self.cooldown_spinbox.valueChanged.connect(self._on_tuning_params_changed)
        grid_det.addWidget(self.cooldown_spinbox, 1, 1)

        lbl_cnf = QLabel("Minimum Confidence:")
        lbl_cnf.setStyleSheet("color: #cbd5e1; font-weight: 600;")
        grid_det.addWidget(lbl_cnf, 1, 2)

        self.conf_spinbox = QSpinBox()
        self.conf_spinbox.setRange(10, 90)
        self.conf_spinbox.setSingleStep(5)
        self.conf_spinbox.setValue(int(self.config.spatial.min_confidence * 100))
        self.conf_spinbox.setSuffix(" %")
        self.conf_spinbox.setToolTip(
            "Spatial Confidence Threshold\n"
            "Minimum cross-correlation coherence required before a direction is accepted.\n"
            "Recommended: 35%."
        )
        self.conf_spinbox.valueChanged.connect(self._on_tuning_params_changed)
        grid_det.addWidget(self.conf_spinbox, 1, 3)

        det_layout.addLayout(grid_det)
        tab_layout.addWidget(card_det)

        # Card 3: Advanced Spatial Cues
        card_spa, spa_layout = self._create_card(
            title="Advanced Spatial Filtering",
            subtitle="HRTF pinna spectral ratio for rear disambiguation in 360° surround audio",
        )

        spa_row = QHBoxLayout()
        spa_row.setSpacing(10)

        self.enable_front_back_cb = QCheckBox("Enable HRTF Pinna Rear Detection (Experimental)")
        self.enable_front_back_cb.setChecked(self.config.spatial.enable_front_back)
        self.enable_front_back_cb.setToolTip(
            "HRTF Pinna Spectral Ratio (Experimental)\n"
            "Uses high-frequency roll-off cues to distinguish front vs. rear in 360° surround mode.\n"
            "Keep disabled for 100% reliable forward screen mapping and zero false rear flips."
        )
        self.enable_front_back_cb.toggled.connect(self._on_tuning_params_changed)
        spa_row.addWidget(self.enable_front_back_cb)
        spa_row.addStretch()

        spa_layout.addLayout(spa_row)
        tab_layout.addWidget(card_spa)

        tab_layout.addStretch()
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "TUNING & CALIBRATION")

    # -------------------------------------------------------------------------
    # Tab 4: Telemetry Log
    # -------------------------------------------------------------------------
    def _init_tab_telemetry_log(self) -> None:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(14, 14, 14, 14)
        tab_layout.setSpacing(10)

        card_log, log_layout = self._create_card(
            title="Acoustic Event Telemetry Stream",
            subtitle="Real-time chronological log of detected acoustic transients with bearings and ITD cues",
        )

        self.event_log_widget = EventLogWidget(max_records=50, parent=self)
        log_layout.addWidget(self.event_log_widget)

        tab_layout.addWidget(card_log, stretch=1)
        self.tabs.addTab(tab, "TELEMETRY LOG")

    # -------------------------------------------------------------------------
    # Timers and Polling
    # -------------------------------------------------------------------------
    def _init_timer(self) -> None:
        """Start the GUI update timer decoupled from the audio thread."""
        self.timer = QTimer(self)
        self.timer.setInterval(16)  # ~60 Hz update rate
        self.timer.timeout.connect(self._on_poll_queue)
        self.timer.start()

        self._flash_reset_timer = QTimer(self)
        self._flash_reset_timer.setSingleShot(True)
        self._flash_reset_timer.timeout.connect(self._reset_event_flash)

        # Debounced configuration auto-save timer (500 ms)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_config_to_disk)

    def _on_poll_queue(self) -> None:
        """Drain events from the capture queue and update GUI widgets."""
        latest_levels: Optional[LevelMetrics] = None

        processed = 0
        while processed < 30:
            try:
                item = self.capture_service.queue.get_nowait()
                processed += 1
                if isinstance(item, LevelMetrics):
                    latest_levels = item
                elif isinstance(item, StatusEvent):
                    self._handle_status_event(item)
                elif isinstance(item, SoundEvent):
                    self._handle_sound_event(item)
            except queue.Empty:
                break

        if latest_levels is not None:
            self.left_meter.set_levels(
                rms_db=latest_levels.left.rms_db,
                peak_held_db=latest_levels.left.peak_held_db,
            )
            self.right_meter.set_levels(
                rms_db=latest_levels.right.rms_db,
                peak_held_db=latest_levels.right.peak_held_db,
            )


        if self.calibrator.state == CalibrationState.RECORDING:
            timeout_res = self.calibrator.poll()
            if timeout_res is not None:
                self._apply_calibration_result(timeout_res)
            else:
                rem = self.calibrator.remaining_seconds
                shots = self.calibrator.shots_recorded
                self.calibrate_status.setText(
                    f"LISTENING: Fire in-game ({shots}/3 shots, {rem:.1f}s left)"
                )

        current_state = self.capture_service.state
        if current_state.value != self.status_badge.text():
            style = STATUS_STYLES.get(current_state, STATUS_STYLES[CaptureState.STOPPED])
            self.status_badge.setText(current_state.value)
            self.status_badge.setStyleSheet(f"border-radius: 6px; padding: 2px 12px; {style}")

    def _handle_sound_event(self, event: SoundEvent) -> None:
        """Handle incoming candidate sound event."""
        self._flash_event_indicator(event)
        self.event_log_widget.add_event(event)
        self.radar_overlay.add_sound_event(event)

        if self.calibrator.state == CalibrationState.RECORDING:
            cal_res = self.calibrator.register_shot(event.peak_db, event.peak_db)
            if cal_res is not None:
                self._apply_calibration_result(cal_res)

    def _handle_status_event(self, event: StatusEvent) -> None:
        """Update window badges and messages according to capture state."""
        self.status_badge.setText(event.state.value)
        style = STATUS_STYLES.get(event.state, STATUS_STYLES[CaptureState.STOPPED])
        self.status_badge.setStyleSheet(f"border-radius: 6px; padding: 2px 12px; {style}")

        if event.message:
            self.log_label.setText(event.message)

    def _flash_event_indicator(self, event: SoundEvent) -> None:
        """Flash the event indicator badge when a transient is detected."""
        direction = event.direction

        if event.sound_type == SoundType.SELF or (direction and direction.is_self_sound):
            type_tag = "SELF"
            badge_style = EVENT_FLASH_SELF
        else:
            type_tag = "SOUND"
            badge_style = EVENT_FLASH_ACTIVE

        if direction is not None:
            if direction.is_self_sound or event.sound_type == SoundType.SELF:
                self.event_flash_badge.setText(f"{type_tag} [{event.peak_db:.0f} dB]")
            elif getattr(direction, "is_rear", False):
                az_360 = getattr(direction, "azimuth_360_deg", direction.azimuth_deg)
                if abs(direction.azimuth_deg) <= 5.0:
                    self.event_flash_badge.setText(f"BEHIND 180° [{event.peak_db:.0f} dB]")
                elif az_360 < 0.0:
                    self.event_flash_badge.setText(f"REAR-LEFT {abs(az_360):.0f}° [{event.peak_db:.0f} dB]")
                else:
                    self.event_flash_badge.setText(f"REAR-RIGHT {az_360:.0f}° [{event.peak_db:.0f} dB]")
            elif abs(direction.azimuth_deg) <= 5.0:
                self.event_flash_badge.setText(f"AHEAD 0° [{event.peak_db:.0f} dB]")
            elif direction.azimuth_deg < -5.0:
                self.event_flash_badge.setText(f"LEFT {abs(direction.azimuth_deg):.0f}° [{event.peak_db:.0f} dB]")
            else:
                self.event_flash_badge.setText(f"RIGHT {direction.azimuth_deg:.0f}° [{event.peak_db:.0f} dB]")
        else:
            self.event_flash_badge.setText(f"{type_tag} [{event.peak_db:.0f} dB]")

        self.event_flash_badge.setStyleSheet(badge_style)
        self._flash_reset_timer.start(600)

    def _reset_event_flash(self) -> None:
        """Reset the flash indicator back to idle state."""
        self.event_flash_badge.setText("IDLE")
        self.event_flash_badge.setStyleSheet(EVENT_FLASH_IDLE)

    # -------------------------------------------------------------------------
    # Audio Routing & Device Selection Handlers
    # -------------------------------------------------------------------------
    def _refresh_device_list(self) -> None:
        """Populate the audio output devices dropdown."""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        devices = AudioCaptureService.list_playback_devices()
        selected_index = 0

        self.device_combo.addItem("Default Output Device", None)

        for idx, dev in enumerate(devices):
            label = f"{dev.name} {'(Default)' if dev.is_default else ''}"
            self.device_combo.addItem(label, dev.name)
            if self.config.audio.device_name and dev.name == self.config.audio.device_name:
                selected_index = idx + 1
            elif not self.config.audio.device_name and dev.is_default:
                selected_index = 0

        self.device_combo.setCurrentIndex(selected_index)
        self.device_combo.blockSignals(False)

    def _refresh_app_list(self) -> None:
        """Populate the running application audio targets dropdown."""
        self.app_combo.blockSignals(True)
        self.app_combo.clear()

        self.app_combo.addItem("All System Audio (Master Mix)", None)

        procs = list_active_audio_processes()
        selected_index = 0

        cur_pid = self.capture_service.target_pid or self.config.audio.target_pid
        cur_name = self.capture_service.target_process_name or self.config.audio.target_process_name

        for idx, proc in enumerate(procs):
            label = f"{proc.display_name} {'[Active]' if proc.is_active else ''}"
            self.app_combo.addItem(label, proc.pid)

            if cur_pid is not None and proc.pid == cur_pid:
                selected_index = idx + 1
            elif cur_pid is None and cur_name is not None and proc.process_name.lower() == cur_name.lower():
                selected_index = idx + 1

        self.app_combo.setCurrentIndex(selected_index)
        self.app_combo.blockSignals(False)
        self._update_app_target_status()

    def _on_app_selection_changed(self, index: int) -> None:
        """Handle user changing target application process selection."""
        pid = self.app_combo.currentData()
        name: Optional[str] = None

        if pid is not None:
            info = find_process_by_pid(pid)
            if info:
                name = info.process_name
            else:
                name = f"PID {pid}"

        logger.info("User selected audio target: PID=%s, Name=%s", pid, name)
        self.config.audio.target_pid = pid
        self.config.audio.target_process_name = name

        self.capture_service.set_target_process(pid=pid, name=name)
        self._update_app_target_status()

    def _update_app_target_status(self) -> None:
        """Update target status text."""
        if self.capture_service.is_process_mode:
            name = self.capture_service.target_process_name or f"PID {self.capture_service.target_pid}"
            status_text = f"ISOLATED: Capturing exclusively from {name} (voice & background apps excluded)"
            self.target_status_label.setText(status_text)
            self.target_status_label.setStyleSheet("color: #34d399; font-size: 11px; font-weight: bold;")
            self.app_quick_status.setText(f"Target: {name} [Isolated]")
            self.app_quick_status.setStyleSheet("color: #34d399; font-weight: 600;")
        else:
            self.target_status_label.setText("MASTER MIX: Capturing all system audio streams combined")
            self.target_status_label.setStyleSheet("color: #38bdf8; font-size: 11px;")
            self.app_quick_status.setText("Target: All System Audio (Master Mix)")
            self.app_quick_status.setStyleSheet("color: #38bdf8; font-weight: 600;")

    def _on_device_selection_changed(self, index: int) -> None:
        """Handle user changing output device selection."""
        device_name = self.device_combo.currentData()
        logger.info("User selected output device: %s", device_name)
        self.config.audio.device_name = device_name
        self.capture_service.stop()
        self.capture_service.audio_config.device_name = device_name
        self.capture_service.start()
        self.toggle_btn.setText("Pause Capture")

    def _on_toggle_capture(self) -> None:
        """Toggle audio capture state."""
        if self.capture_service.state == CaptureState.STOPPED:
            self.capture_service.start()
            self.toggle_btn.setText("Pause Capture")
        else:
            self.capture_service.stop()
            self.left_meter.set_levels(self.config.meter.min_db, self.config.meter.min_db)
            self.right_meter.set_levels(self.config.meter.min_db, self.config.meter.min_db)
            self.toggle_btn.setText("Resume Capture")

    # -------------------------------------------------------------------------
    # Overlay HUD Handlers
    # -------------------------------------------------------------------------
    def _on_toggle_hud_visibility(self) -> None:
        """Toggle visibility of the floating overlay HUD."""
        if self.radar_overlay.isVisible():
            self.radar_overlay.hide()
            self.hud_toggle_btn.setText("Show Overlay")
        else:
            self.radar_overlay.show()
            self.hud_toggle_btn.setText("Hide Overlay")

    def _on_toggle_hud_lock(self) -> None:
        """Toggle click-through lock state for the radar HUD."""
        new_locked = not self.radar_overlay.is_locked
        self.radar_overlay.set_locked(new_locked)
        if new_locked:
            self.hud_lock_btn.setText("Locked (Click-Through)")
            self.hud_lock_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #065f46;
                    color: #34d399;
                    font-weight: 700;
                    border: 1px solid #059669;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #047857; }
                """
            )
        else:
            self.hud_lock_btn.setText("Unlocked (Drag to Move)")
            self.hud_lock_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #92400e;
                    color: #fde68a;
                    font-weight: 700;
                    border: 1px solid #d97706;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #b45309; }
                """
            )

    def _on_hud_size_changed(self, value: int) -> None:
        """Update HUD overlay physical diameter."""
        self.radar_overlay.set_hud_diameter(value)
        self.hud_size_px.setText(f"{value} px")
        self.config.overlay_diameter = value
        self._schedule_config_save()

    def _on_overlay_position_changed(self, x: int, y: int) -> None:
        """Track user repositioning of the radar HUD on screen."""
        self.config.overlay_x = x
        self.config.overlay_y = y
        self._schedule_config_save()

    def _on_toggle_hud_visibility(self) -> None:
        """Toggle visibility of the floating overlay HUD."""
        if self.radar_overlay.isVisible():
            self.radar_overlay.hide()
            self.hud_toggle_btn.setText("Show Overlay")
        else:
            self.radar_overlay.show()
            self.hud_toggle_btn.setText("Hide Overlay")
        self.config.overlay_visible = self.radar_overlay.isVisible()
        self._schedule_config_save()

    def _on_toggle_hud_lock(self) -> None:
        """Toggle click-through lock state for the radar HUD."""
        new_locked = not self.radar_overlay.is_locked
        self.radar_overlay.set_locked(new_locked)
        self.config.overlay_locked = new_locked
        self._schedule_config_save()
        if new_locked:
            self.hud_lock_btn.setText("Locked (Click-Through)")
            self.hud_lock_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #065f46;
                    color: #34d399;
                    font-weight: 700;
                    border: 1px solid #059669;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #047857; }
                """
            )
        else:
            self.hud_lock_btn.setText("Unlocked (Drag to Move)")
            self.hud_lock_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #92400e;
                    color: #fde68a;
                    font-weight: 700;
                    border: 1px solid #d97706;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #b45309; }
                """
            )

    def _on_hud_opacity_changed(self, value: int) -> None:
        """Update HUD background opacity."""
        opacity = value / 100.0
        self.radar_overlay.set_hud_opacity(opacity)
        self.hud_opacity_pct.setText(f"{value}%")
        self.config.overlay_opacity = opacity
        self._schedule_config_save()

    def _on_hud_self_toggled(self, checked: bool) -> None:
        """Toggle whether self-sounds create a halo pulse on the HUD."""
        self.radar_overlay.set_show_self_sounds(checked)

    def _on_hud_mode_changed(self, index: int) -> None:
        """Handle spatial audio mode changes (360 Polar vs 180 Stereo)."""
        mode = self.hud_mode_combo.currentData()
        self.config.spatial.spatial_mode = mode
        self.capture_service.update_spatial_config(self.config.spatial)
        self.radar_overlay.set_spatial_mode(mode)
        self._schedule_config_save()

    def _on_radar_type_changed(self, index: int) -> None:
        """Handle radar visualization style changes ('rays' vs 'zones')."""
        style = self.radar_type_combo.currentData()
        if style:
            self.config.overlay_type = style
            self.radar_overlay.set_radar_type(style)
            self._schedule_config_save()

    def _on_toggle_sound_circles(self, checked: bool) -> None:
        """Toggle visibility of individual sound mini-circles on the radar."""
        self.config.show_sound_circles = checked
        self.radar_overlay.set_show_sound_circles(checked)
        self._schedule_config_save()

    def _on_toggle_sound_numbers(self, checked: bool) -> None:
        """Toggle visibility of numeric indicators and counters on the radar."""
        self.config.show_sound_numbers = checked
        self.radar_overlay.set_show_sound_numbers(checked)
        self._schedule_config_save()

    def _on_mouse_compass_toggled(self, checked: bool) -> None:
        """Toggle mouse gyro compass rotation on the HUD."""
        self.config.spatial.enable_mouse_compass = checked
        self.radar_overlay.set_mouse_compass_enabled(checked)
        self.capture_service.update_spatial_config(self.config.spatial)
        self._schedule_config_save()
        if checked:
            self.calib_mouse_status.setText("Gyro Tracking Active (Calibrate turn or Reset if drifting)")
            self.calib_mouse_status.setStyleSheet("color: #fbbf24; font-weight: 600;")
        else:
            self.calib_mouse_status.setText("Direct Screen Mode (Locked to crosshair, zero mouse drift)")
            self.calib_mouse_status.setStyleSheet("color: #34d399; font-weight: 600;")

    def _on_reset_yaw_clicked(self) -> None:
        """Instantly reset player gyro heading to 0.0° (Center Ahead)."""
        self.radar_overlay.reset_gyro_heading()
        self.calib_mouse_status.setText("Heading reset to 0° Ahead")
        self.calib_mouse_status.setStyleSheet("color: #38bdf8; font-weight: 600;")

    def _on_persistence_changed(self, value: float) -> None:
        """Update ray persistence duration in seconds."""
        self.config.spatial.cluster_lifetime_s = float(value)
        self.radar_overlay.set_cluster_lifetime(float(value))
        self.capture_service.update_spatial_config(self.config.spatial)
        self._schedule_config_save()

    def _on_mouse_sens_changed(self, value: float) -> None:
        """Update mouse degrees per hardware count sensitivity."""
        self.config.spatial.mouse_yaw_sensitivity = float(value)
        self.radar_overlay.set_mouse_sensitivity(float(value))
        self.capture_service.update_spatial_config(self.config.spatial)
        self._schedule_config_save()

    def _on_calibrate_mouse_clicked(self) -> None:
        """Handle interactive 360-degree mouse turn calibration."""
        tracker = self.radar_overlay.mouse_tracker
        if tracker.is_calibrating:
            new_sens = tracker.finish_calibration(target_turn_deg=360.0)
            self.calib_mouse_btn.setText("Calibrate 360° Turn")
            self.calib_mouse_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #1e293b;
                    color: #cbd5e1;
                    font-weight: 600;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
                QPushButton:hover { background-color: #334155; color: white; }
                """
            )
            self.mouse_sens_spinbox.setValue(new_sens)
            self.calib_mouse_status.setText(f"Calibrated: {new_sens:.4f}°/count")
            self.calib_mouse_status.setStyleSheet("color: #34d399; font-weight: 600;")
            self._schedule_config_save()
        else:
            tracker.start_calibration()
            self.calib_mouse_btn.setText("Finish 360° Turn")
            self.calib_mouse_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #991b1b;
                    color: white;
                    font-weight: 700;
                    border: 1px solid #ef4444;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
                QPushButton:hover { background-color: #b91c1c; }
                """
            )
            self.calib_mouse_status.setText("Make one full 360° turn in-game, then click Finish.")
            self.calib_mouse_status.setStyleSheet("color: #fb923c; font-weight: 600;")

    # -------------------------------------------------------------------------
    # Game Profiles & Preset Handlers
    # -------------------------------------------------------------------------
    def _refresh_preset_combo(self, select_name: Optional[str] = None) -> None:
        """Populate the preset combobox with built-in and user custom presets."""
        if not hasattr(self, "preset_combo"):
            return
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()

        all_presets = get_all_presets(self.config.user_presets)
        for name in all_presets.keys():
            self.preset_combo.addItem(name)

        target = select_name or self.config.active_preset
        idx = self.preset_combo.findText(target)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        else:
            self.preset_combo.setCurrentIndex(0)

        current_name = self.preset_combo.currentText()
        preset = all_presets.get(current_name, BUILTIN_PRESETS["Default (Balanced)"])
        self.preset_desc_lbl.setText(preset.description)
        self.delete_preset_btn.setEnabled(current_name in self.config.user_presets)

        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        """Handle selection of a game audio preset from the combobox."""
        if index < 0 or not hasattr(self, "preset_combo"):
            return
        preset_name = self.preset_combo.currentText()
        all_presets = get_all_presets(self.config.user_presets)
        preset = all_presets.get(preset_name)
        if not preset:
            return

        self.preset_desc_lbl.setText(preset.description)
        self.delete_preset_btn.setEnabled(preset_name in self.config.user_presets)
        self.config.active_preset = preset_name

        self._apply_preset_to_widgets(preset)
        self._schedule_config_save()

    def _apply_preset_to_widgets(self, preset: GamePreset) -> None:
        """Apply a GamePreset's parameters to UI controls and active audio engine."""
        self._suppress_preset_change_signals = True
        try:
            self.ratio_spinbox.setValue(preset.trigger_ratio)
            self.min_db_spinbox.setValue(preset.min_trigger_db)
            self.cooldown_spinbox.setValue(preset.cooldown_ms)
            self.conf_spinbox.setValue(int(preset.min_confidence * 100))
            self.bilateral_spinbox.setValue(preset.bilateral_self_threshold_db)
            self.lockout_spinbox.setValue(int(preset.self_echo_lockout_ms))
            self.require_mouse_cb.setChecked(preset.require_mouse_for_self)
            self.enable_front_back_cb.setChecked(preset.enable_front_back)
            self.persistence_spinbox.setValue(preset.cluster_lifetime_s)

            idx = self.hud_mode_combo.findData(preset.spatial_mode)
            if idx >= 0:
                self.hud_mode_combo.setCurrentIndex(idx)
        finally:
            self._suppress_preset_change_signals = False

        self._on_tuning_params_changed()
        self._on_persistence_changed(preset.cluster_lifetime_s)
        self._on_hud_mode_changed(self.hud_mode_combo.currentIndex())

    def _on_save_preset_clicked(self) -> None:
        """Prompt user for a preset name and save current parameters as a custom preset."""
        name, ok = QInputDialog.getText(
            self,
            "Save Custom Preset",
            "Enter a name for the new profile:",
            text=f"Custom Profile {len(self.config.user_presets) + 1}",
        )
        if not ok or not name.strip():
            return
        clean_name = name.strip()
        if clean_name in BUILTIN_PRESETS:
            QMessageBox.warning(
                self,
                "Reserved Name",
                f"'{clean_name}' is a built-in profile name. Please choose a different name for your custom profile.",
            )
            return

        current_mode = self.hud_mode_combo.currentData() or "stereo_180"
        new_preset = GamePreset(
            name=clean_name,
            description=f"User-created custom profile (saved {time.strftime('%Y-%m-%d %H:%M')}).",
            trigger_ratio=float(self.ratio_spinbox.value()),
            min_trigger_db=float(self.min_db_spinbox.value()),
            cooldown_ms=int(self.cooldown_spinbox.value()),
            min_confidence=float(self.conf_spinbox.value() / 100.0),
            spatial_mode=str(current_mode),
            bilateral_self_threshold_db=float(self.bilateral_spinbox.value()),
            self_echo_lockout_ms=float(self.lockout_spinbox.value()),
            require_mouse_for_self=bool(self.require_mouse_cb.isChecked()),
            enable_front_back=bool(self.enable_front_back_cb.isChecked()),
            cluster_lifetime_s=float(self.persistence_spinbox.value()),
        )

        self.config.user_presets[clean_name] = new_preset.to_dict()
        self.config.active_preset = clean_name
        self._refresh_preset_combo(select_name=clean_name)
        self._schedule_config_save()
        self.log_label.setText(f"Profile '{clean_name}' saved successfully.")

    def _on_delete_preset_clicked(self) -> None:
        """Delete currently selected user custom preset."""
        current_name = self.preset_combo.currentText()
        if current_name not in self.config.user_presets:
            return

        ret = QMessageBox.question(
            self,
            "Delete Profile",
            f"Are you sure you want to delete custom profile '{current_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            del self.config.user_presets[current_name]
            self.config.active_preset = "Default (Balanced)"
            self._refresh_preset_combo(select_name="Default (Balanced)")
            self._on_preset_selected(self.preset_combo.currentIndex())
            self._schedule_config_save()
            self.log_label.setText(f"Profile '{current_name}' deleted.")

    # -------------------------------------------------------------------------
    # Auto-Save & Configuration Persistence
    # -------------------------------------------------------------------------
    def _schedule_config_save(self) -> None:
        """Trigger debounced auto-save of application configuration."""
        if hasattr(self, "_save_timer"):
            self._save_timer.start(500)

    def _save_config_to_disk(self) -> None:
        """Immediately serialize configuration to config.json."""
        try:
            if hasattr(self, "hud_size_slider"):
                self.config.overlay_diameter = self.hud_size_slider.value()
            if hasattr(self, "hud_opacity_slider"):
                self.config.overlay_opacity = self.hud_opacity_slider.value() / 100.0
            if hasattr(self, "radar_overlay"):
                self.config.overlay_locked = self.radar_overlay.is_locked
                self.config.overlay_visible = self.radar_overlay.isVisible()
                self.config.overlay_x = self.radar_overlay.x()
                self.config.overlay_y = self.radar_overlay.y()
            if hasattr(self, "radar_type_combo"):
                self.config.overlay_type = self.radar_type_combo.currentData()
            elif hasattr(self, "radar_overlay"):
                self.config.overlay_type = getattr(self.radar_overlay, "radar_type", "rays")

            if hasattr(self, "show_circles_cb"):
                self.config.show_sound_circles = self.show_circles_cb.isChecked()
            elif hasattr(self, "radar_overlay"):
                self.config.show_sound_circles = getattr(self.radar_overlay, "show_sound_circles", True)

            if hasattr(self, "show_numbers_cb"):
                self.config.show_sound_numbers = self.show_numbers_cb.isChecked()
            elif hasattr(self, "radar_overlay"):
                self.config.show_sound_numbers = getattr(self.radar_overlay, "show_sound_numbers", True)

            self.config.window_width = self.width()
            self.config.window_height = self.height()

            self.config.save_to_file("config.json")
        except Exception as exc:
            logger.warning("Failed to auto-save configuration: %s", exc)

    # -------------------------------------------------------------------------
    # Tuning & Weapon Calibration Handlers
    # -------------------------------------------------------------------------
    def _on_tuning_params_changed(self) -> None:
        """Propagate updated detector and spatial parameters to capture service."""
        self.config.detector.threshold_ratio = float(self.ratio_spinbox.value())
        self.config.detector.min_trigger_db = float(self.min_db_spinbox.value())
        self.config.detector.cooldown_ms = float(self.cooldown_spinbox.value())
        self.capture_service.update_detector_config(self.config.detector)

        self.config.spatial.bilateral_self_threshold_db = float(self.bilateral_spinbox.value())
        self.config.spatial.self_echo_lockout_ms = float(self.lockout_spinbox.value())
        self.config.spatial.min_confidence = float(self.conf_spinbox.value()) / 100.0
        self.config.spatial.suppress_self_sounds = self.suppress_self_cb.isChecked()
        self.config.spatial.suppress_self_footsteps = self.suppress_step_cb.isChecked()
        self.config.spatial.require_mouse_for_self = self.require_mouse_cb.isChecked()
        if hasattr(self, "enable_front_back_cb"):
            self.config.spatial.enable_front_back = self.enable_front_back_cb.isChecked()
        self.capture_service.update_spatial_config(self.config.spatial)

        if not getattr(self, "_suppress_preset_change_signals", False):
            self._schedule_config_save()

    def _on_calibrate_clicked(self) -> None:
        """Start or cancel interactive weapon sound calibration."""
        if self.calibrator.state == CalibrationState.RECORDING:
            self.calibrator.cancel()
            self.calibrate_btn.setText("Calibrate Weapon")
            self.calibrate_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #0284c7;
                    color: white;
                    font-weight: 700;
                    border: 1px solid #38bdf8;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #0369a1; }
                """
            )
            self.calibrate_status.setText("Calibration cancelled.")
            self.calibrate_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        else:
            self.calibrator.start()
            self.calibrate_btn.setText("Cancel Calibration")
            self.calibrate_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #991b1b;
                    color: white;
                    font-weight: 700;
                    border: 1px solid #ef4444;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #b91c1c; }
                """
            )
            self.calibrate_status.setText("LISTENING: Fire 3 weapon shots in-game... (0/3)")
            self.calibrate_status.setStyleSheet("color: #fb923c; font-size: 11px; font-weight: bold;")

    def _apply_calibration_result(self, result: CalibrationResult) -> None:
        """Apply the computed calibration threshold."""
        self.calibrate_btn.setText("Calibrate Weapon")
        self.calibrate_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #0284c7;
                color: white;
                font-weight: 700;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #0369a1; }
            """
        )
        self.calibrate_status.setText(result.message)
        if result.success:
            self.bilateral_spinbox.setValue(result.recommended_threshold_db)
            self.calibrate_status.setStyleSheet("color: #34d399; font-size: 11px; font-weight: bold;")
            self._on_tuning_params_changed()
        else:
            self.calibrate_status.setStyleSheet("color: #f87171; font-size: 11px;")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure clean shutdown of audio capture, overlay, and timers before window closes."""
        logger.info("Window closing. Saving configuration and stopping capture service...")
        self.timer.stop()
        self._flash_reset_timer.stop()
        self._save_config_to_disk()
        self.radar_overlay.close()
        self.capture_service.stop(timeout_s=2.0)
        event.accept()

