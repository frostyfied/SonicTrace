"""Audio capture service using Windows WASAPI loopback via soundcard.

Runs in a dedicated background thread, captures live stereo playback audio,
calculates level metrics, and resiliently handles device disconnection and silence.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import warnings
from typing import Optional, Union

import numpy as np
import psutil
import soundcard as sc

# Filter expected WASAPI loopback buffer discontinuities to prevent console spam
warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

from src.audio_capture.types import CaptureState, DeviceInfo, StatusEvent
from src.audio_processing.metrics import LevelMetricsCalculator
from src.audio_processing.types import LevelMetrics
from src.config.settings import AudioConfig, DetectorConfig, MeterConfig, SpatialConfig
from src.event_detection.detector import TransientEventDetector
from src.event_detection.types import SoundEvent

logger = logging.getLogger(__name__)


class AudioCaptureService:
    """Manages background WASAPI loopback audio capture and processing."""

    def __init__(
        self,
        audio_config: Optional[AudioConfig] = None,
        meter_config: Optional[MeterConfig] = None,
        detector_config: Optional[DetectorConfig] = None,
        spatial_config: Optional[SpatialConfig] = None,
        event_queue: Optional[queue.Queue[Union[LevelMetrics, StatusEvent, SoundEvent]]] = None,
    ) -> None:
        self.audio_config = audio_config or AudioConfig()
        self.meter_config = meter_config or MeterConfig()
        self.detector_config = detector_config or DetectorConfig()
        self.spatial_config = spatial_config or SpatialConfig()
        self.queue: queue.Queue[Union[LevelMetrics, StatusEvent, SoundEvent]] = (
            event_queue if event_queue is not None else queue.Queue(maxsize=100)
        )

        self._calculator = LevelMetricsCalculator(
            meter_config=self.meter_config,
            silence_threshold_db=self.audio_config.silence_threshold_db,
        )
        self._detector = TransientEventDetector(
            config=self.detector_config,
            spatial_config=self.spatial_config,
            sample_rate=self.audio_config.sample_rate,
        )

        self._stop_event = threading.Event()
        self._switch_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = CaptureState.STOPPED
        self._active_device_name = "None"
        self._target_pid: Optional[int] = self.audio_config.target_pid
        self._target_process_name: Optional[str] = self.audio_config.target_process_name

    @property
    def state(self) -> CaptureState:
        """Current lifecycle state of the capture service."""
        return self._state

    @property
    def active_device_name(self) -> str:
        """Name of the currently opened audio device."""
        return self._active_device_name

    @property
    def target_pid(self) -> Optional[int]:
        """Target application PID for process loopback, or None for master loopback."""
        return self._target_pid

    @property
    def target_process_name(self) -> Optional[str]:
        """Target application name."""
        return self._target_process_name

    @property
    def is_process_mode(self) -> bool:
        """Whether capture is currently targeting a specific application."""
        return self._target_pid is not None

    def set_target_process(self, pid: Optional[int], name: Optional[str] = None) -> None:
        """Set or clear the target application for isolated process loopback capture.

        Args:
            pid: Process ID to capture audio exclusively from, or None for Master Loopback.
            name: Friendly display name of the application (e.g. 'TslGame.exe').
        """
        self._target_pid = pid
        self._target_process_name = name
        self.audio_config.target_pid = pid
        self.audio_config.target_process_name = name
        logger.info("Updated audio capture target: PID=%s, Name=%s", pid, name)
        # Signal capture loop to immediately switch modes
        self._switch_event.set()

    def update_detector_config(self, config: DetectorConfig) -> None:
        """Update detector thresholds and re-arm detector."""
        self.detector_config = config
        self._detector.config = config

    def update_spatial_config(self, config: SpatialConfig) -> None:
        """Update spatial parameters and re-arm direction estimator."""
        self.spatial_config = config
        self._detector.update_spatial_config(config)

    @classmethod
    def list_playback_devices(cls) -> list[DeviceInfo]:
        """Enumerate all available playback devices and loopback endpoints."""
        devices: list[DeviceInfo] = []
        try:
            default_spk = sc.default_speaker()
            default_id = default_spk.id if default_spk else None
        except Exception:
            default_id = None

        try:
            speakers = sc.all_speakers()
            for spk in speakers:
                devices.append(
                    DeviceInfo(
                        id=spk.id,
                        name=spk.name,
                        is_default=(spk.id == default_id),
                    )
                )
        except Exception as exc:
            logger.warning("Error enumerating playback devices: %s", exc)

        return devices

    def start(self) -> None:
        """Start the background audio capture thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("AudioCaptureService is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_capture_loop,
            name="AudioCaptureThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("Audio capture thread started.")

    def stop(self, timeout_s: float = 3.0) -> None:
        """Signal the capture thread to stop and wait for termination."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)
            if self._thread.is_alive():
                logger.warning("Capture thread did not exit within %s seconds.", timeout_s)
        self._set_state(CaptureState.STOPPED, "Capture stopped by user.")
        logger.info("Audio capture stopped cleanly.")

    def _set_state(self, state: CaptureState, message: str = "") -> None:
        """Update state and emit status event into the queue."""
        self._state = state
        event = StatusEvent(
            timestamp=time.time(),
            state=state,
            device_name=self._active_device_name,
            message=message,
        )
        self._push_queue(event)

    def _push_queue(self, item: Union[LevelMetrics, StatusEvent, SoundEvent]) -> None:
        """Push an item into the queue, evicting the oldest element if full."""
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                pass

    def _resolve_loopback_device(self) -> Optional[sc.Microphone]:
        """Locate the loopback recording device for the selected or default speaker."""
        target_name = self.audio_config.device_name

        try:
            if target_name:
                speakers = sc.all_speakers()
                matched = next((s for s in speakers if target_name in s.name), None)
                if matched:
                    return sc.get_microphone(id=matched.id, include_loopback=True)

            default_speaker = sc.default_speaker()
            if default_speaker:
                return sc.get_microphone(id=default_speaker.id, include_loopback=True)
        except Exception as exc:
            logger.warning("Failed to locate default speaker loopback: %s", exc)

        # Fallback: Find any available loopback microphone
        try:
            mics = sc.all_microphones(include_loopback=True)
            for mic in mics:
                if getattr(mic, "isloopback", False):
                    return mic
        except Exception as exc:
            logger.error("Failed to query loopback devices: %s", exc)

        return None

    def _run_capture_loop(self) -> None:
        """Main capture loop running inside the background thread."""
        while not self._stop_event.is_set():
            self._switch_event.clear()
            if self._target_pid is not None:
                self._run_process_capture(self._target_pid)
            else:
                self._run_master_capture()

    def _run_master_capture(self) -> None:
        """Capture loop for system master audio loopback via soundcard."""
        self._switch_event.clear()
        self._set_state(CaptureState.STARTING, "Initializing audio capture device...")

        consecutive_silent_frames = 0
        silence_state_active = False

        while not self._stop_event.is_set() and not self._switch_event.is_set():
            loopback_device = self._resolve_loopback_device()

            if loopback_device is None:
                self._set_state(
                    CaptureState.ERROR,
                    "No playback loopback device available. Retrying...",
                )
                self._stop_event.wait(self.audio_config.reconnect_interval_s)
                continue

            self._active_device_name = loopback_device.name
            logger.info("Opening loopback device: %s", self._active_device_name)

            try:
                with loopback_device.recorder(
                    samplerate=self.audio_config.sample_rate,
                    channels=self.audio_config.channels,
                    blocksize=self.audio_config.block_size,
                ) as recorder:
                    self._calculator.reset()
                    self._detector.reset()
                    self._set_state(
                        CaptureState.ACTIVE,
                        f"Capturing from {self._active_device_name}",
                    )
                    consecutive_silent_frames = 0
                    silence_state_active = False

                    while not self._stop_event.is_set() and not self._switch_event.is_set():
                        data = recorder.record(numframes=self.audio_config.block_size)
                        metrics = self._calculator.compute_levels(data)
                        self._push_queue(metrics)

                        # Event detection
                        detected_events = self._detector.process_chunk(data)
                        for ev in detected_events:
                            self._push_queue(ev)

                        if metrics.is_silent:
                            consecutive_silent_frames += 1
                            frames_for_half_sec = max(
                                1,
                                int(
                                    0.5
                                    * self.audio_config.sample_rate
                                    / self.audio_config.block_size
                                ),
                            )
                            if (
                                consecutive_silent_frames >= frames_for_half_sec
                                and not silence_state_active
                            ):
                                silence_state_active = True
                                self._set_state(
                                    CaptureState.SILENCE,
                                    "No system audio output detected (silence)",
                                )
                        else:
                            consecutive_silent_frames = 0
                            if silence_state_active:
                                silence_state_active = False
                                self._set_state(
                                    CaptureState.ACTIVE,
                                    f"Active audio playback on {self._active_device_name}",
                                )

            except Exception as exc:
                if self._stop_event.is_set() or self._switch_event.is_set():
                    break
                logger.warning(
                    "Capture error on '%s': %s. Reconnecting in %.1fs...",
                    self._active_device_name,
                    exc,
                    self.audio_config.reconnect_interval_s,
                )
                self._set_state(
                    CaptureState.RECONNECTING,
                    f"Device error ({exc}). Reconnecting...",
                )
                self._stop_event.wait(self.audio_config.reconnect_interval_s)

    def _run_process_capture(self, pid: int) -> None:
        """Capture loop for a specific application process via WASAPI process loopback."""
        self._switch_event.clear()
        try:
            from proctap import ProcessAudioCapture
        except ImportError:
            logger.error("proctap is not installed; cannot capture process audio.")
            self._set_state(CaptureState.ERROR, "proctap package not installed.")
            self._stop_event.wait(self.audio_config.reconnect_interval_s)
            return

        proc_name = self._target_process_name or f"PID {pid}"
        if not psutil.pid_exists(pid):
            self._set_state(
                CaptureState.ERROR,
                f"Target application {proc_name} is not running.",
            )
            self._stop_event.wait(self.audio_config.reconnect_interval_s)
            return

        self._active_device_name = f"App: {proc_name}"
        self._set_state(CaptureState.STARTING, f"Attaching to {proc_name}...")

        try:
            tap = ProcessAudioCapture(pid=pid)
            tap.start()
        except Exception as exc:
            logger.error("Failed to start ProcessAudioCapture for PID %d: %s", pid, exc)
            self._set_state(
                CaptureState.ERROR,
                f"Failed to attach to {proc_name}: {exc}",
            )
            self._stop_event.wait(self.audio_config.reconnect_interval_s)
            return

        self._calculator.reset()
        self._detector.reset()
        self._set_state(
            CaptureState.ACTIVE,
            f"Capturing isolated audio from {proc_name}",
        )

        consecutive_silent_frames = 0
        silence_state_active = False

        try:
            while not self._stop_event.is_set() and not self._switch_event.is_set():
                chunk_bytes = tap.read(timeout=0.15)
                if chunk_bytes is None or len(chunk_bytes) == 0:
                    if not psutil.pid_exists(pid):
                        logger.info("Target process %s (PID %d) terminated.", proc_name, pid)
                        self._set_state(
                            CaptureState.SILENCE,
                            f"Target application {proc_name} closed.",
                        )
                        break
                    continue

                # PCM format: 48kHz, 2ch, float32
                data = np.frombuffer(chunk_bytes, dtype=np.float32).reshape(-1, 2)
                if data.shape[0] == 0:
                    continue

                metrics = self._calculator.compute_levels(data)
                self._push_queue(metrics)

                detected_events = self._detector.process_chunk(data)
                for ev in detected_events:
                    self._push_queue(ev)

                if metrics.is_silent:
                    consecutive_silent_frames += 1
                    frames_for_half_sec = max(
                        1,
                        int(
                            0.5
                            * self.audio_config.sample_rate
                            / max(1, data.shape[0])
                        ),
                    )
                    if consecutive_silent_frames >= frames_for_half_sec and not silence_state_active:
                        silence_state_active = True
                        self._set_state(
                            CaptureState.SILENCE,
                            f"Silence in {proc_name}",
                        )
                else:
                    consecutive_silent_frames = 0
                    if silence_state_active:
                        silence_state_active = False
                        self._set_state(
                            CaptureState.ACTIVE,
                            f"Audio active in {proc_name}",
                        )

        except Exception as exc:
            if not (self._stop_event.is_set() or self._switch_event.is_set()):
                logger.warning("Error in process capture loop for PID %d: %s", pid, exc)
                self._set_state(
                    CaptureState.RECONNECTING,
                    f"Capture error in {proc_name}: {exc}",
                )
                self._stop_event.wait(self.audio_config.reconnect_interval_s)
        finally:
            try:
                tap.stop()
                tap.close()
            except Exception:
                pass
