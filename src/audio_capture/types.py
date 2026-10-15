"""Types and state definitions for audio capture."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaptureState(str, Enum):
    """Lifecycle states of the audio capture service."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    SILENCE = "SILENCE"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


@dataclass(slots=True)
class DeviceInfo:
    """Metadata describing an audio playback device."""

    id: str
    name: str
    is_default: bool = False


@dataclass(slots=True)
class StatusEvent:
    """State transition or status update emitted by the audio capture service."""

    timestamp: float
    state: CaptureState
    device_name: str
    message: str
