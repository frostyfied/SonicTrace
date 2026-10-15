"""Passive mouse yaw rotation tracker using Windows Raw Input for world-space compass orientation."""

from __future__ import annotations

import ctypes
import logging
import platform
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system().lower() == "windows"

_active_mouse_tracker: Optional[MouseYawTracker] = None
_mock_mouse_firing: Optional[bool] = None


def set_mock_mouse_firing(firing: Optional[bool]) -> None:
    """Override mouse firing state for unit testing."""
    global _mock_mouse_firing
    _mock_mouse_firing = firing


def is_left_mouse_down(recent_window_s: float = 0.20) -> bool:
    """Check if the physical left mouse button is currently held or was clicked within recent_window_s.

    Used for gating player weapon self-sounds to eliminate false positives on enemy gunfire.
    """
    global _mock_mouse_firing
    if _mock_mouse_firing is not None:
        return _mock_mouse_firing

    if not IS_WINDOWS:
        return False

    # 1. Check if the active Raw Input tracker recorded a recent LMB click
    global _active_mouse_tracker
    if _active_mouse_tracker is not None:
        if (time.monotonic() - _active_mouse_tracker.last_lmb_time) <= recent_window_s:
            return True

    # 2. Check real-time physical key state via Win32 (VK_LBUTTON = 0x01)
    try:
        if ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:
            return True
    except Exception:
        pass

    return False


if IS_WINDOWS:
    from ctypes import wintypes

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wintypes.USHORT),
            ("usUsage", wintypes.USHORT),
            ("dwFlags", wintypes.DWORD),
            ("hwndTarget", wintypes.HWND),
        ]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [
            ("dwType", wintypes.DWORD),
            ("dwSize", wintypes.DWORD),
            ("hDevice", wintypes.HANDLE),
            ("wParam", wintypes.WPARAM),
        ]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [
            ("usFlags", wintypes.USHORT),
            ("ulButtons", wintypes.ULONG),
            ("ulRawButtons", wintypes.ULONG),
            ("lLastX", ctypes.c_long),
            ("lLastY", ctypes.c_long),
            ("ulExtraInformation", wintypes.ULONG),
        ]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [
            ("header", RAWINPUTHEADER),
            ("mouse", RAWMOUSE),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    ctypes.windll.user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    ctypes.windll.user32.DefWindowProcW.restype = wintypes.LPARAM

    WNDPROC = ctypes.WINFUNCTYPE(
        wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )


class MouseYawTracker:
    """Tracks physical mouse horizontal movement to rotate the radar HUD into world-space compass coordinates."""

    def __init__(
        self,
        sensitivity_deg_per_count: float = 0.05,
        enabled: bool = True,
        on_yaw_changed: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.sensitivity_deg_per_count = max(0.001, sensitivity_deg_per_count)
        self.enabled = enabled
        self.on_yaw_changed = on_yaw_changed

        self._lock = threading.Lock()
        self._current_yaw_deg: float = 0.0
        self._last_lmb_time: float = 0.0

        # Calibration state
        self._is_calibrating: bool = False
        self._calib_start_counts: int = 0
        self._total_hardware_counts: int = 0

        # Background thread state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sink_hwnd: Optional[int] = None
        self._wndproc_ref = None  # Prevent GC of ctypes callback

    def start(self) -> bool:
        """Start the background raw mouse input listener."""
        global _active_mouse_tracker
        _active_mouse_tracker = self

        if not IS_WINDOWS:
            logger.info("Non-Windows OS detected; mouse raw input listener disabled.")
            return False

        if self._thread is not None and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="MouseYawTrackerThread",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the background raw input listener thread."""
        global _active_mouse_tracker
        if _active_mouse_tracker is self:
            _active_mouse_tracker = None

        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def record_lmb_down(self) -> None:
        """Record physical left mouse button press timestamp."""
        with self._lock:
            self._last_lmb_time = time.monotonic()

    @property
    def last_lmb_time(self) -> float:
        """Timestamp of the most recent physical left mouse button press."""
        with self._lock:
            return self._last_lmb_time


    def get_yaw_deg(self) -> float:
        """Retrieve the current player yaw heading in degrees [-180.0, 180.0]."""
        with self._lock:
            if not self.enabled:
                return 0.0
            return (self._current_yaw_deg + 180.0) % 360.0 - 180.0

    def reset_yaw(self, angle_deg: float = 0.0) -> None:
        """Reset player heading to a specific angle (default: 0.0° Ahead)."""
        with self._lock:
            self._current_yaw_deg = angle_deg
        if self.on_yaw_changed:
            self.on_yaw_changed(self.get_yaw_deg())

    def add_delta_x(self, dx: int) -> None:
        """Incorporate a relative mouse horizontal movement in hardware counts.

        Positive dx (moving mouse right) turns player right (clockwise), so yaw increases.
        """
        if not self.enabled or dx == 0:
            return

        with self._lock:
            self._total_hardware_counts += dx
            angle_delta = dx * self.sensitivity_deg_per_count
            self._current_yaw_deg += angle_delta
            yaw = (self._current_yaw_deg + 180.0) % 360.0 - 180.0

        if self.on_yaw_changed:
            self.on_yaw_changed(yaw)

    def set_sensitivity(self, deg_per_count: float) -> None:
        """Update degrees per mouse count sensitivity."""
        with self._lock:
            self.sensitivity_deg_per_count = max(0.001, deg_per_count)

    def set_enabled(self, enabled: bool) -> None:
        """Toggle mouse compass tracking on or off."""
        with self._lock:
            self.enabled = enabled
            if not enabled:
                self._current_yaw_deg = 0.0
        if self.on_yaw_changed:
            self.on_yaw_changed(0.0)

    # --- Interactive 360° Calibration ---

    def start_calibration(self) -> None:
        """Begin tracking mouse movement for a 360-degree rotation calibration."""
        with self._lock:
            self._is_calibrating = True
            self._calib_start_counts = self._total_hardware_counts

    def cancel_calibration(self) -> None:
        """Cancel ongoing calibration without modifying sensitivity."""
        with self._lock:
            self._is_calibrating = False

    def finish_calibration(self, target_turn_deg: float = 360.0) -> float:
        """Complete calibration and apply calculated degrees per mouse count.

        Returns:
            The newly calibrated sensitivity in degrees per count.
        """
        with self._lock:
            self._is_calibrating = False
            total_counts = abs(self._total_hardware_counts - self._calib_start_counts)
            if total_counts < 50:
                logger.warning("Insufficient mouse movement for calibration (%d counts)", total_counts)
                return self.sensitivity_deg_per_count

            new_sens = target_turn_deg / float(total_counts)
            self.sensitivity_deg_per_count = round(max(0.005, min(0.50, new_sens)), 4)
            return self.sensitivity_deg_per_count

    @property
    def is_calibrating(self) -> bool:
        with self._lock:
            return self._is_calibrating

    # --- Background Windows Raw Input Pump ---

    def _worker_loop(self) -> None:
        """Windows thread running a lightweight hidden sink window and Raw Input pump."""
        if not IS_WINDOWS:
            return

        try:
            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HANDLE),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            def _wnd_proc(hwnd, msg, wp, lp):
                if msg == 0x00FF:  # WM_INPUT
                    raw = RAWINPUT()
                    size = wintypes.UINT(ctypes.sizeof(RAWINPUT))
                    res = ctypes.windll.user32.GetRawInputData(
                        lp,
                        0x10000003,  # RID_INPUT
                        ctypes.byref(raw),
                        ctypes.byref(size),
                        ctypes.sizeof(RAWINPUTHEADER),
                    )
                    if res != -1 and raw.header.dwType == 0:  # RIM_TYPEMOUSE
                        button_flags = raw.mouse.ulButtons & 0xFFFF
                        if button_flags & 0x0001:  # RI_MOUSE_LEFT_BUTTON_DOWN
                            self.record_lmb_down()
                        if not (raw.mouse.usFlags & 0x01):  # MOUSE_MOVE_RELATIVE
                            dx = raw.mouse.lLastX
                            if dx != 0:
                                self.add_delta_x(dx)
                    return 0
                return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wp, lp)

            self._wndproc_ref = WNDPROC(_wnd_proc)
            class_name = f"MouseYawSinkClass_{threading.get_ident()}"

            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc_ref
            wc.lpszClassName = class_name
            ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

            # Create an invisible top-level utility window (required for RIDEV_INPUTSINK)
            hwnd = ctypes.windll.user32.CreateWindowExW(
                0x00000080,  # WS_EX_TOOLWINDOW
                class_name,
                "MouseYawSink",
                0x80000000,  # WS_POPUP
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )
            self._sink_hwnd = hwnd

            # Register for raw mouse packets even when in background (RIDEV_INPUTSINK)
            rid = RAWINPUTDEVICE(0x01, 0x02, 0x00000100, hwnd)
            reg_ok = ctypes.windll.user32.RegisterRawInputDevices(
                ctypes.byref(rid), 1, ctypes.sizeof(rid)
            )
            if not reg_ok:
                logger.warning("Failed to register Windows Raw Input for mouse compass.")

            msg = MSG()
            while not self._stop_event.is_set():
                while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, 1):
                    ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                    ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
                self._stop_event.wait(0.005)

            if hwnd:
                ctypes.windll.user32.DestroyWindow(hwnd)
                ctypes.windll.user32.UnregisterClassW(class_name, None)
        except Exception as exc:
            logger.debug("Mouse raw input worker encountered error: %s", exc)
