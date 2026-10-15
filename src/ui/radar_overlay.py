"""Transparent, always-on-top circular 360-degree radar overlay HUD with persistent gyro compass tracking."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from PySide6.QtWidgets import QWidget

from src.direction_estimation.mouse_tracker import MouseYawTracker
from src.direction_estimation.threat_tracker import SpatialThreatTracker, ThreatCluster
from src.event_classification.types import SoundType
from src.event_detection.types import SoundEvent


@dataclass
class RadarPing:
    """An active visual ping rendered on the radar overlay."""

    azimuth_deg: float      # 360° bearing or 180° lateral
    peak_db: float
    confidence: float
    is_self_sound: bool
    is_uncertain: bool
    timestamp: float
    lifetime_s: float = 1.8
    sound_type: SoundType = SoundType.SOUND
    is_rear: bool = False


class RadarOverlayWindow(QWidget):
    """Circular, transparent, always-on-top 360° radar HUD with persistent rays and mouse gyro compass."""

    position_changed = Signal(int, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Acoustic Radar HUD")
        self.setMinimumSize(220, 220)
        self.resize(320, 320)

        # Frameless, translucent, always-on-top, tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._is_locked: bool = True
        self._show_self_sounds: bool = True
        self._hud_opacity: float = 0.85
        self._spatial_mode: str = "stereo_180"
        self._radar_type: str = "rays"  # "rays" (lines) or "zones" (curved sector arcs)
        self._show_sound_circles: bool = True  # If False, hides mini-circles for sounds
        self._show_sound_numbers: bool = True  # If False, hides numeric counters/metrics on radar
        self._pings: List[RadarPing] = []
        self._drag_pos: Optional[QPoint] = None

        # Persistent multi-threat spatial clustering engine (8.0s default persistence)
        self.threat_tracker = SpatialThreatTracker(
            angular_tolerance_deg=20.0,
            cluster_lifetime_s=8.0,
            on_target_tolerance_deg=6.0,
        )

        # Mouse gyro compass tracking engine (disabled by default for Direct Screen-Locked Mode)
        self.mouse_tracker = MouseYawTracker(sensitivity_deg_per_count=0.05, enabled=False)
        self.mouse_tracker.start()

        # Latest event tracking for active directional sweep beam
        self._latest_azimuth_deg: Optional[float] = None
        self._latest_event_time: float = 0.0
        self._latest_is_self: bool = False
        self._latest_peak_db: float = -60.0
        self._latest_sound_type: SoundType = SoundType.SOUND
        self._latest_is_rear: bool = False

        # Lock mode setup
        self._apply_lock_state()

        # Animation timer (60 FPS)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)
        self._anim_timer.start()

    def closeEvent(self, event) -> None:
        """Clean shutdown of mouse tracking thread."""
        self.mouse_tracker.stop()
        super().closeEvent(event)

    def set_locked(self, locked: bool) -> None:
        """Toggle mouse click-through lock state."""
        self._is_locked = locked
        self._apply_lock_state()
        self.update()

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    def set_show_self_sounds(self, show: bool) -> None:
        """Control whether self-sounds produce a center pulse."""
        self._show_self_sounds = show

    def set_hud_opacity(self, opacity: float) -> None:
        """Adjust overall HUD background and ring opacity [0.2, 1.0]."""
        self._hud_opacity = max(0.2, min(1.0, opacity))
        self.update()

    def set_hud_diameter(self, diameter: int) -> None:
        """Adjust physical scale and pixel diameter of the radar overlay."""
        clamped = max(200, min(800, int(diameter)))
        self.resize(clamped, clamped)
        self.update()


    def set_spatial_mode(self, mode: str) -> None:
        """Switch between 'hrtf_360' and 'stereo_180' radar display modes."""
        self._spatial_mode = mode
        self.update()

    @property
    def spatial_mode(self) -> str:
        return self._spatial_mode

    def set_radar_type(self, radar_type: str) -> None:
        """Switch radar visualization style: 'rays' (lines) or 'zones' (tactical sector arcs)."""
        if radar_type in ("rays", "zones"):
            self._radar_type = radar_type
            self.update()

    @property
    def radar_type(self) -> str:
        return self._radar_type

    def set_show_sound_circles(self, show: bool) -> None:
        """Control whether mini-circles / pips for individual sounds are rendered on the radar."""
        self._show_sound_circles = show
        self.update()

    @property
    def show_sound_circles(self) -> bool:
        return self._show_sound_circles

    def set_show_sound_numbers(self, show: bool) -> None:
        """Control whether numbers (burst multipliers, metrics, etc.) are rendered on the radar."""
        self._show_sound_numbers = show
        self.update()

    @property
    def show_sound_numbers(self) -> bool:
        return self._show_sound_numbers

    def set_mouse_compass_enabled(self, enabled: bool) -> None:
        """Enable or disable mouse gyro rotation."""
        self.mouse_tracker.set_enabled(enabled)
        self.update()

    def set_mouse_sensitivity(self, sens: float) -> None:
        """Update mouse degrees per hardware count sensitivity."""
        self.mouse_tracker.set_sensitivity(sens)

    def reset_gyro_heading(self) -> None:
        """Reset player gyro heading to 0.0° (Center Ahead) and re-synchronize active threats."""
        self.mouse_tracker.reset_yaw(0.0)
        for cluster in self.threat_tracker._clusters:
            cluster.world_azimuth_deg = cluster.azimuth_deg
        self.update()

    def set_cluster_lifetime(self, lifetime_s: float) -> None:
        """Set persistence duration of threat rays in seconds."""
        self.threat_tracker.cluster_lifetime_s = max(2.0, min(30.0, lifetime_s))

    def _apply_lock_state(self) -> None:
        """Apply mouse click-through so game clicks pass through completely when locked."""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, self._is_locked)

        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if self._is_locked:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def add_sound_event(self, event: SoundEvent) -> None:
        """Push a newly detected directional sound event to the radar display."""
        direction = event.direction
        if direction is None:
            return

        is_self = direction.is_self_sound or event.sound_type == SoundType.SELF
        if is_self and not self._show_self_sounds:
            return

        current_yaw = self.mouse_tracker.get_yaw_deg()

        # Update persistent threat cluster tracking
        if not is_self:
            self.threat_tracker.update(event, current_yaw=current_yaw)

        # Select display bearing
        if self._spatial_mode == "hrtf_360":
            bearing = getattr(direction, "azimuth_360_deg", direction.azimuth_deg)
            is_rear = getattr(direction, "is_rear", False)
        else:
            bearing = direction.azimuth_deg
            is_rear = False

        ping = RadarPing(
            azimuth_deg=bearing,
            peak_db=event.peak_db,
            confidence=direction.confidence,
            is_self_sound=is_self,
            is_uncertain=direction.is_uncertain,
            timestamp=time.monotonic(),
            lifetime_s=1.8,
            sound_type=event.sound_type,
            is_rear=is_rear,
        )
        self._pings.append(ping)

        # Update latest active beam direction
        self._latest_azimuth_deg = bearing
        self._latest_event_time = time.monotonic()
        self._latest_is_self = is_self
        self._latest_peak_db = event.peak_db
        self._latest_sound_type = event.sound_type
        self._latest_is_rear = is_rear

        if len(self._pings) > 20:
            self._pings.pop(0)

        self.update()

    def _on_tick(self) -> None:
        """Update active clusters with latest gyro yaw and trigger repaint."""
        now = time.monotonic()
        alive_pings = [p for p in self._pings if now - p.timestamp < p.lifetime_s]
        current_yaw = self.mouse_tracker.get_yaw_deg()
        clusters = self.threat_tracker.get_active_clusters(current_yaw=current_yaw, now=now)
        has_active_beam = (
            self._latest_azimuth_deg is not None
            and (now - self._latest_event_time) < 2.5
        )
        if (
            len(alive_pings) != len(self._pings)
            or len(alive_pings) > 0
            or len(clusters) > 0
            or has_active_beam
            or not self._is_locked
        ):
            self._pings = alive_pings
            self.update()

    # Mouse events for repositioning when unlocked
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._is_locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._is_locked and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._is_locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self.position_changed.emit(self.x(), self.y())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        """Render circular radar HUD with glowing range rings, persistent threat rays, and target alignment."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        side = min(width, height)
        margin = 16.0 if not self._is_locked else 10.0
        radius = (side - 2.0 * margin) / 2.0
        center = QPointF(width / 2.0, height / 2.0)

        now = time.monotonic()
        is_hrtf_360 = (self._spatial_mode == "hrtf_360")
        current_yaw = self.mouse_tracker.get_yaw_deg()
        clusters = self.threat_tracker.get_active_clusters(current_yaw=current_yaw, now=now)

        # 1. Unlocked guide border
        if not self._is_locked:
            guide_pen = QPen(QColor(59, 130, 246, 180), 2.0, Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            painter.setBrush(QBrush(QColor(15, 23, 42, 70)))
            painter.drawRoundedRect(QRectF(4, 4, width - 8, height - 8), 12, 12)

            painter.setPen(QColor(147, 197, 253, 220))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(
                QRectF(0, 8, width, 18),
                Qt.AlignmentFlag.AlignCenter,
                "HUD UNLOCKED (DRAG TO MOVE)",
            )

        # 2. Radar Glass Disc Background
        bg_alpha = int(180 * self._hud_opacity)
        bg_grad = QRadialGradient(center, radius)
        bg_grad.setColorAt(0.0, QColor(10, 15, 29, int(bg_alpha * 0.9)))
        bg_grad.setColorAt(0.7, QColor(15, 23, 42, bg_alpha))
        bg_grad.setColorAt(1.0, QColor(8, 14, 26, int(bg_alpha * 1.1)))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg_grad))
        painter.drawEllipse(center, radius, radius)

        # 3. Outer Perimeter Ring (Sleek Neutral Tactical Border)
        outer_ring_pen = QPen(QColor(30, 41, 59, int(220 * self._hud_opacity)), 2.5)
        painter.setPen(outer_ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)

        # 4. Concentric Range Rings (33%, 66%)
        ring_pen = QPen(QColor(51, 65, 85, int(150 * self._hud_opacity)), 1.2, Qt.PenStyle.DashLine)
        painter.setPen(ring_pen)
        for frac in (0.33, 0.66):
            r = radius * frac
            painter.drawEllipse(center, r, r)

        # 5. Radial Spokes
        spoke_pen = QPen(QColor(51, 65, 85, int(120 * self._hud_opacity)), 1.0)
        painter.setPen(spoke_pen)
        if is_hrtf_360:
            spoke_angles = (0.0, -45.0, 45.0, -90.0, 90.0, -135.0, 135.0, 180.0)
        else:
            spoke_angles = (0.0, -60.0, -30.0, 30.0, 60.0, -90.0, 90.0)

        for deg in spoke_angles:
            rad = math.radians(deg - 90.0)
            p_edge = QPointF(
                center.x() + radius * math.cos(rad),
                center.y() + radius * math.sin(rad),
            )
            painter.drawLine(center, p_edge)

        # Perimeter ticks
        tick_pen = QPen(QColor(71, 85, 105, int(160 * self._hud_opacity)), 1.2)
        painter.setPen(tick_pen)
        tick_range = range(0, 360, 30) if is_hrtf_360 else range(-90, 91, 15)
        for deg in tick_range:
            rad = math.radians(deg - 90.0)
            p_out = QPointF(center.x() + radius * math.cos(rad), center.y() + radius * math.sin(rad))
            tick_l = 6.0 if (deg % 30 == 0) else 3.5
            p_in = QPointF(center.x() + (radius - tick_l) * math.cos(rad), center.y() + (radius - tick_l) * math.sin(rad))
            painter.drawLine(p_in, p_out)

        # 6. Direction Labels & Status Mode Pill
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))

        # 0° Ahead Top Indicator (Clean Tactical Crosshair Label)
        ahead_p = QPointF(center.x(), center.y() - radius + 12.0)
        painter.setPen(QColor(56, 189, 248, int(240 * self._hud_opacity)))
        ahead_lbl = "▲ 0°" if self._show_sound_numbers else "▲"
        painter.drawText(
            QRectF(ahead_p.x() - 30, ahead_p.y() - 10, 60, 20),
            Qt.AlignmentFlag.AlignCenter,
            ahead_lbl,
        )

        # Tactical Status Pill (DIRECT vs GYRO)
        pill_rect = QRectF(center.x() - 40, center.y() - radius + 25.0, 80, 15)
        pill_pen = QPen(QColor(30, 41, 59, int(190 * self._hud_opacity)), 1.0)
        pill_bg = QColor(15, 23, 42, int(170 * self._hud_opacity))
        painter.setPen(pill_pen)
        painter.setBrush(QBrush(pill_bg))
        painter.drawRoundedRect(pill_rect, 7, 7)

        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        if self.mouse_tracker.enabled:
            painter.setPen(QColor(52, 211, 153, int(220 * self._hud_opacity)))  # Emerald
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, "GYRO YAW")
        else:
            painter.setPen(QColor(148, 163, 184, int(200 * self._hud_opacity)))  # Slate
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, "DIRECT HUD")

        # Left (-90°) & Right (+90°)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QColor(148, 163, 184, int(200 * self._hud_opacity)))
        left_lbl = "-90° L" if self._show_sound_numbers else "L"
        right_lbl = "R +90°" if self._show_sound_numbers else "R"
        painter.drawText(
            QRectF(center.x() - radius + 4, center.y() - 10, 34, 20),
            Qt.AlignmentFlag.AlignCenter,
            left_lbl,
        )
        painter.drawText(
            QRectF(center.x() + radius - 38, center.y() - 10, 34, 20),
            Qt.AlignmentFlag.AlignCenter,
            right_lbl,
        )

        # 180° Behind Indicator in 360° mode, or Shaded Forward Dome in 180° mode
        if is_hrtf_360:
            behind_p = QPointF(center.x(), center.y() + radius - 14.0)
            rear_lbl = "180° REAR" if self._show_sound_numbers else "REAR"
            painter.drawText(
                QRectF(behind_p.x() - 30, behind_p.y() - 10, 60, 20),
                Qt.AlignmentFlag.AlignCenter,
                rear_lbl,
            )
        else:
            # Subtle shaded visor for the rear half in 180 mode
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(6, 10, 20, int(120 * self._hud_opacity))))
            painter.drawPie(QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0), 180 * 16, 180 * 16)

            # Horizon separator
            painter.setPen(QPen(QColor(51, 65, 85, int(140 * self._hud_opacity)), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))

            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
            painter.setPen(QColor(100, 116, 139, int(150 * self._hud_opacity)))
            dome_lbl = "180° FORWARD DOME" if self._show_sound_numbers else "FORWARD DOME"
            painter.drawText(
                QRectF(center.x() - 65, center.y() + (radius * 0.40), 130, 16),
                Qt.AlignmentFlag.AlignCenter,
                dome_lbl,
            )

        # 7. Persistent Threat Rays (Rotating with Mouse Gyro Heading)
        newest_cluster = max(clusters, key=lambda c: c.last_seen) if clusters else None
        freshness_window = 2.0  # Seconds for high-intensity newest sound flaring

        for cluster in clusters:
            cluster_age = now - cluster.last_seen
            decay = max(0.0, 1.0 - (cluster_age / self.threat_tracker.cluster_lifetime_s))
            # Smooth persistent alpha curve (persists with minimum visible alpha)
            alpha_int = int(max(60, 255 * (decay ** 0.8)))

            rad = math.radians(cluster.azimuth_deg - 90.0)
            db_norm = max(0.0, min(1.0, (cluster.peak_db + 50.0) / 45.0))
            r_dist = radius * (0.50 + 0.45 * db_norm)

            pip_pos = QPointF(
                center.x() + r_dist * math.cos(rad),
                center.y() + r_dist * math.sin(rad),
            )
            edge_pos = QPointF(
                center.x() + radius * math.cos(rad),
                center.y() + radius * math.sin(rad),
            )

            is_newest = (cluster == newest_cluster)
            is_recent_shot = (cluster_age < freshness_window)

            if is_newest:
                # Newest sound / active firing threat: High-Visibility Electric Flame Orange
                threat_col = QColor(249, 115, 22, alpha_int)  # #F97316
                glow_col = QColor(251, 146, 60, int(alpha_int * 0.60))  # #FB923C
                pen_width = 3.2 if is_recent_shot else 2.5
                halo_r = 18.0 if is_recent_shot else 14.0
                core_r = 7.0 if is_recent_shot else 5.5
            elif cluster.is_primary:
                # Primary lingering threat: Tactical Neon Cyan
                threat_col = QColor(6, 182, 212, alpha_int)  # #06B6D4
                glow_col = QColor(34, 211, 238, int(alpha_int * 0.45))
                pen_width = 2.2
                halo_r = 13.0
                core_r = 5.0
            else:
                # Secondary lingering threat: Subdued Tactical Slate Blue
                threat_col = QColor(56, 189, 248, int(alpha_int * 0.75))
                glow_col = QColor(14, 116, 144, int(alpha_int * 0.30))
                pen_width = 1.6
                halo_r = 10.0
                core_r = 4.0

            if self._radar_type == "zones":
                # Render Tactical Threat Zone (Angular Sector Arc)
                zone_span_deg = 32.0
                center_qt_deg = 90.0 - cluster.azimuth_deg
                start_qt_deg = center_qt_deg - (zone_span_deg / 2.0)

                r_in = radius * 0.42
                r_out = radius - 1.5

                rect_out = QRectF(center.x() - r_out, center.y() - r_out, 2.0 * r_out, 2.0 * r_out)
                rect_in = QRectF(center.x() - r_in, center.y() - r_in, 2.0 * r_in, 2.0 * r_in)

                zone_path = QPainterPath()
                zone_path.arcMoveTo(rect_out, start_qt_deg)
                zone_path.arcTo(rect_out, start_qt_deg, zone_span_deg)
                zone_path.arcTo(rect_in, start_qt_deg + zone_span_deg, -zone_span_deg)
                zone_path.closeSubpath()

                # Radial depth gradient for the threat sector
                zone_grad = QRadialGradient(center, radius)
                zone_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
                zone_grad.setColorAt(0.38, QColor(threat_col.red(), threat_col.green(), threat_col.blue(), 0))
                zone_grad.setColorAt(0.55, QColor(glow_col.red(), glow_col.green(), glow_col.blue(), int(alpha_int * 0.25)))
                zone_grad.setColorAt(0.85, QColor(threat_col.red(), threat_col.green(), threat_col.blue(), int(alpha_int * 0.50)))
                zone_grad.setColorAt(1.0, QColor(threat_col.red(), threat_col.green(), threat_col.blue(), int(alpha_int * 0.70)))

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(zone_grad))
                painter.drawPath(zone_path)

                # Crisp perimeter arc rim
                outer_pen = QPen(threat_col, pen_width + 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(outer_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(rect_out, int(start_qt_deg * 16), int(zone_span_deg * 16))

                # Radial boundary rays
                bnd_col = QColor(threat_col.red(), threat_col.green(), threat_col.blue(), int(alpha_int * 0.45))
                painter.setPen(QPen(bnd_col, 1.2, Qt.PenStyle.SolidLine))
                rad_left = math.radians((cluster.azimuth_deg - zone_span_deg / 2.0) - 90.0)
                rad_right = math.radians((cluster.azimuth_deg + zone_span_deg / 2.0) - 90.0)
                p_in_left = QPointF(center.x() + r_in * math.cos(rad_left), center.y() + r_in * math.sin(rad_left))
                p_out_left = QPointF(center.x() + r_out * math.cos(rad_left), center.y() + r_out * math.sin(rad_left))
                p_in_right = QPointF(center.x() + r_in * math.cos(rad_right), center.y() + r_in * math.sin(rad_right))
                p_out_right = QPointF(center.x() + r_out * math.cos(rad_right), center.y() + r_out * math.sin(rad_right))
                painter.drawLine(p_in_left, p_out_left)
                painter.drawLine(p_in_right, p_out_right)

                # Inner dashed boundary arc
                inner_pen = QPen(QColor(threat_col.red(), threat_col.green(), threat_col.blue(), int(alpha_int * 0.35)), 1.0, Qt.PenStyle.DashLine)
                painter.setPen(inner_pen)
                painter.drawArc(rect_in, int(start_qt_deg * 16), int(zone_span_deg * 16))
            else:
                # Persistent directional beacon ray (from center reticle to perimeter)
                beam_pen = QPen(threat_col, pen_width)
                painter.setPen(beam_pen)
                painter.drawLine(center, edge_pos)

            if self._show_sound_circles:
                # Outer glow halo
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(glow_col))
                painter.drawEllipse(pip_pos, halo_r, halo_r)

                # Core pip blip
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(threat_col))
                painter.drawEllipse(pip_pos, core_r, core_r)

            # Burst Shot Counter Badge (e.g. x3)
            if self._show_sound_numbers and cluster.shot_count > 1:
                badge_text = f"x{cluster.shot_count}"
                painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
                painter.setPen(QColor(248, 250, 252, int(alpha_int * 0.95)))
                badge_x = pip_pos.x() + (9 if self._show_sound_circles else 4)
                badge_y = pip_pos.y() - 10
                painter.drawText(
                    QRectF(badge_x, badge_y, 28, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    badge_text,
                )

        # 8. Render Active Transient Pings & Expanding Purple Halo for Self-Sounds
        for ping in self._pings:
            age = now - ping.timestamp
            if age >= ping.lifetime_s:
                continue

            progress = age / ping.lifetime_s
            decay = max(0.0, 1.0 - progress)
            alpha_int = int(255 * (decay ** 1.3))

            if ping.is_self_sound or ping.sound_type == SoundType.SELF:
                # Self-sound: Expanding purple shockwave from player reticle
                halo_radius = radius * (0.15 + 0.40 * progress)
                halo_pen = QPen(QColor(168, 85, 247, alpha_int), 3.0)
                painter.setPen(halo_pen)
                painter.setBrush(QBrush(QColor(168, 85, 247, int(alpha_int * 0.25))))
                painter.drawEllipse(center, halo_radius, halo_radius)
            elif self._show_sound_circles:
                # External transient ping: Expanding orange shockwave along bearing
                rad = math.radians(ping.azimuth_deg - 90.0)
                ping_dist = radius * (0.45 + 0.50 * progress)
                ping_pos = QPointF(
                    center.x() + ping_dist * math.cos(rad),
                    center.y() + ping_dist * math.sin(rad),
                )
                ping_pen = QPen(QColor(249, 115, 22, alpha_int), 2.0)
                painter.setPen(ping_pen)
                painter.setBrush(QBrush(QColor(251, 146, 60, int(alpha_int * 0.30))))
                ping_size = 8.0 * (1.0 + progress)
                painter.drawEllipse(ping_pos, ping_size, ping_size)

        # 9. Center Player Crosshair Reticle (Clean Tactical Design)
        reticle_color = QColor(148, 163, 184, int(220 * self._hud_opacity))
        painter.setPen(QPen(reticle_color, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 5.0, 5.0)

        painter.setPen(QPen(QColor(56, 189, 248, int(240 * self._hud_opacity)), 2.0))
        chevron = [
            QPointF(center.x(), center.y() - 9.0),
            QPointF(center.x() - 4.5, center.y() - 3.0),
            QPointF(center.x() + 4.5, center.y() - 3.0),
        ]
        painter.drawPolyline(chevron)

        # 10. Dynamic Multi-Threat Readout Badge
        badge_rect = QRectF(center.x() - 130.0, center.y() + radius - 26.0, 260.0, 20.0)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))

        if self._latest_is_self and (now - self._latest_event_time) < 2.5:
            badge_col = QColor(192, 132, 252, int(240 * self._hud_opacity))
            if self._show_sound_numbers:
                badge_text = f"SELF [{self._latest_peak_db:.0f} dB]"
            else:
                badge_text = "SELF"
            painter.setPen(badge_col)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
        elif clusters:
            if newest_cluster is not None and (now - newest_cluster.last_seen) < 2.5:
                # Active Newest Threat Highlight
                badge_col = QColor(249, 115, 22, int(255 * self._hud_opacity))
                newest_label = self._format_bearing_label(newest_cluster.azimuth_deg)
                if len(clusters) > 1:
                    if self._show_sound_numbers:
                        badge_text = f"NEW: {newest_label} | {len(clusters)} THREATS [x{newest_cluster.shot_count}]"
                    else:
                        badge_text = f"NEW: {newest_label} | MULTIPLE THREATS"
                else:
                    if self._show_sound_numbers:
                        badge_text = f"NEW: {newest_label} [{newest_cluster.peak_db:.0f} dB] [x{newest_cluster.shot_count}]"
                    else:
                        badge_text = f"NEW: {newest_label}"
            else:
                primary = clusters[0]
                pri_name = self._format_bearing_label(primary.azimuth_deg)
                if len(clusters) > 1:
                    badge_col = QColor(245, 158, 11, int(240 * self._hud_opacity))
                    if self._show_sound_numbers:
                        badge_text = f"{len(clusters)} THREATS | PRI: {pri_name} [x{primary.shot_count}]"
                    else:
                        badge_text = f"THREATS | PRI: {pri_name}"
                else:
                    badge_col = QColor(34, 211, 238, int(230 * self._hud_opacity))
                    if self._show_sound_numbers:
                        badge_text = f"{pri_name} [{primary.peak_db:.0f} dB] [x{primary.shot_count}]"
                    else:
                        badge_text = pri_name

            painter.setPen(badge_col)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
        elif self._latest_azimuth_deg is not None and (now - self._latest_event_time) < 2.5:
            badge_col = QColor(249, 115, 22, int(240 * self._hud_opacity))
            label = self._format_bearing_label(self._latest_azimuth_deg)
            if self._show_sound_numbers:
                badge_text = f"{label} [{self._latest_peak_db:.0f} dB]"
            else:
                badge_text = label
            painter.setPen(badge_col)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
        else:
            painter.setPen(QColor(100, 116, 139, int(180 * self._hud_opacity)))
            compass_tag = "GYRO COMPASS" if self.mouse_tracker.enabled else "DIRECT LOCKED"
            if self._show_sound_numbers:
                mode_lbl = "360° POLAR" if is_hrtf_360 else "180° STEREO"
            else:
                mode_lbl = "POLAR" if is_hrtf_360 else "STEREO"
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"RADAR: {mode_lbl} [{compass_tag}]")

    def _format_bearing_label(self, azimuth: float) -> str:
        """Format 360 bearing into human-readable tactical bearing name."""
        abs_az = abs(azimuth)
        deg_str = f" {azimuth:.0f}°" if self._show_sound_numbers else ""
        deg_str_abs = f" {abs_az:.0f}°" if self._show_sound_numbers else ""
        if abs_az <= 6.0:
            return f"AHEAD{deg_str}"
        elif abs_az >= 170.0:
            return f"BEHIND{deg_str}"
        elif 6.0 < azimuth <= 75.0:
            return f"FRONT-RIGHT{deg_str}"
        elif 75.0 < azimuth < 105.0:
            return f"RIGHT{deg_str}"
        elif 105.0 <= azimuth < 170.0:
            return f"BEHIND-RIGHT{deg_str}"
        elif -75.0 <= azimuth < -6.0:
            return f"FRONT-LEFT{deg_str_abs}"
        elif -105.0 < azimuth < -75.0:
            return f"LEFT{deg_str_abs}"
        else:
            return f"BEHIND-LEFT{deg_str_abs}"
