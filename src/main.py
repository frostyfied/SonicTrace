"""Entry point for the sound overlay application.

Supports both interactive PySide6 GUI mode and headless CLI diagnostic mode.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

if sys.platform == "win32" and not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED for clean Qt OleInitialize

from src.audio_capture.service import AudioCaptureService
from src.audio_capture.types import CaptureState, StatusEvent
from src.audio_processing.types import LevelMetrics
from src.config.settings import AppConfig
from src.event_detection.types import SoundEvent


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging format and severity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%H:%M:%S",
    )


def run_headless_monitor(config: AppConfig, duration_s: float | None = None) -> int:
    """Run audio capture and level calculation in the console without GUI."""
    logger = logging.getLogger("HeadlessMonitor")
    logger.info("Starting headless audio monitor...")

    capture_service = AudioCaptureService(
        audio_config=config.audio,
        meter_config=config.meter,
        detector_config=config.detector,
        spatial_config=config.spatial,
    )
    capture_service.start()

    start_time = time.monotonic()
    last_print = 0.0

    try:
        while True:
            if duration_s is not None and (time.monotonic() - start_time) >= duration_s:
                logger.info("Requested duration of %.1fs reached.", duration_s)
                break

            try:
                item = capture_service.queue.get(timeout=0.2)
                if isinstance(item, StatusEvent):
                    logger.info("[%s] %s (%s)", item.state.value, item.message, item.device_name)
                elif isinstance(item, SoundEvent):
                    if item.direction is not None:
                        dir_info = (
                            f"Azimuth: {item.direction.azimuth_deg:+.1f}° | "
                            f"ITD: {item.direction.itd_ms:+.2f}ms | Conf: {int(item.direction.confidence * 100)}%"
                        )
                        if item.direction.is_self_sound:
                            dir_info += " [SELF SOUND]"
                    else:
                        dir_info = f"Bias: {item.channel_bias:+.2f}"
                    print(
                        f"\n[SOUND EVENT {item.event_id}] Peak: {item.peak_db:.1f} dB | Ratio: {item.energy_ratio:.1f}x | {dir_info}",
                        flush=True,
                    )
                elif isinstance(item, LevelMetrics):
                    now = time.monotonic()
                    # Rate limit console output to ~10 Hz
                    if now - last_print >= 0.1:
                        last_print = now
                        silent_tag = "[SILENCE]" if item.is_silent else "         "
                        print(
                            f"\r{silent_tag} L: {item.left.rms_db:5.1f} dB (peak: {item.left.peak_held_db:5.1f} dB) | "
                            f"R: {item.right.rms_db:5.1f} dB (peak: {item.right.peak_held_db:5.1f} dB)",
                            end="",
                            flush=True,
                        )
            except Exception:
                pass
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        print()  # newline after carriage return line
        logger.info("Stopping capture service...")
        capture_service.stop(timeout_s=2.0)

    return 0


def main() -> int:
    """Parse CLI arguments and dispatch execution."""
    parser = argparse.ArgumentParser(
        description="Audio loopback capture and level visualization"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to configuration JSON file (default: config.json)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless console mode without PySide6 UI",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Duration in seconds to run (useful with --headless for testing)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all detected playback audio devices and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.list_devices:
        devices = AudioCaptureService.list_playback_devices()
        print("\nAvailable Playback Devices:")
        for idx, dev in enumerate(devices, 1):
            default_marker = " [DEFAULT]" if dev.is_default else ""
            print(f"  {idx}. {dev.name}{default_marker} (id: {dev.id})")
        print()
        return 0

    config = AppConfig.load_from_file(args.config)

    if args.headless:
        return run_headless_monitor(config, duration_s=args.duration)

    # Launch PySide6 GUI
    from src.ui.app import run_gui_application

    return run_gui_application(config)


if __name__ == "__main__":
    sys.exit(main())
