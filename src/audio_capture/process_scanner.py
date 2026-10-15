"""Audio process discovery and enumeration for Windows audio sessions."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioProcessInfo:
    """Represents a running application process with an active Windows audio session."""

    pid: int
    process_name: str
    display_name: str
    is_active: bool = True


def _query_audio_processes_impl() -> List[AudioProcessInfo]:
    """Internal helper to query active CoreAudio sessions via pycaw."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        from pycaw.pycaw import AudioUtilities
    except Exception as exc:
        logger.warning("pycaw is not available: %s", exc)
        return []

    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as exc:
        logger.error("Failed to query Windows audio sessions: %s", exc)
        return []

    seen_pids: set[int] = set()
    process_list: List[AudioProcessInfo] = []

    for session in sessions:
        proc = getattr(session, "Process", None)
        if not proc:
            continue

        try:
            pid = int(proc.pid)
            if pid <= 0 or pid in seen_pids:
                continue

            name = proc.name()
            if not name:
                continue

            # Check if session is active (State 1 = Active, 0 = Inactive, 2 = Expired)
            state = getattr(session, "State", 0)
            is_active = (state == 1)

            seen_pids.add(pid)
            display_name = f"{name} (PID: {pid})"
            process_list.append(
                AudioProcessInfo(
                    pid=pid,
                    process_name=name,
                    display_name=display_name,
                    is_active=is_active,
                )
            )
        except Exception as exc:
            logger.debug("Error querying process from audio session: %s", exc)
            continue

    # Sort alphabetically by process name (case-insensitive)
    process_list.sort(key=lambda p: p.process_name.lower())
    return process_list


def list_active_audio_processes() -> List[AudioProcessInfo]:
    """Enumerate running applications that have an active Windows CoreAudio session.

    Runs in a dedicated worker thread to ensure an isolated COM apartment,
    preventing any conflict with main thread GUI OleInitialize or soundcard MTA modes.

    Returns:
        List of AudioProcessInfo objects, deduplicated by PID and sorted alphabetically.
    """
    result: List[AudioProcessInfo] = []
    error: List[Exception] = []

    def _worker() -> None:
        try:
            result.extend(_query_audio_processes_impl())
        except Exception as exc:
            error.append(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=3.0)

    if error:
        logger.warning("Failed to query Windows audio sessions: %s", error[0])

    return result


def find_process_by_pid(pid: int) -> Optional[AudioProcessInfo]:
    """Find AudioProcessInfo for a specific PID among active sessions."""
    for proc in list_active_audio_processes():
        if proc.pid == pid:
            return proc
    return None


def find_process_by_name(name: str) -> Optional[AudioProcessInfo]:
    """Find AudioProcessInfo matching a process name (case-insensitive)."""
    target = name.lower()
    for proc in list_active_audio_processes():
        if proc.process_name.lower() == target:
            return proc
    return None
