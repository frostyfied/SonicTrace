# System Playback Audio & Sound Event Monitor (Milestone 2)

A clean, modular Windows 11 desktop application that captures system playback audio via WASAPI loopback, calculates stereo levels, detects transient sound events (candidate gunshots, footsteps, impacts) using adaptive STA/LTA energy ratios, and visualizes them in a decoupled PySide6 interface.

This application is completely game-independent: it does not inspect game memory, inject DLLs, modify game files, or interface with any game APIs.

---

## Architecture & Responsibilities

The codebase strictly decouples audio acquisition, digital signal processing, event detection, and GUI rendering:

- **Audio Capture (`src/audio_capture/`)**:
  - Connects to Windows WASAPI loopback using `soundcard` (CFFI).
  - Automatically identifies the default speaker output and handles dynamic device switching.
  - Resilient state machine (`ACTIVE`, `SILENCE`, `RECONNECTING`, `ERROR`, `STOPPED`) with auto-reconnect backoff.
  - Feeds audio into processing pipelines and pushes metrics/events over a thread-safe `queue.Queue`.
- **Audio Processing (`src/audio_processing/`)**:
  - Calculates true RMS and peak amplitudes in linear and dBFS units (-60 dB to 0 dB).
  - Broadcast-standard meter ballistics: instantaneous attack, smooth exponential decay, and configurable peak hold.
  - Instantaneous silence detection below configurable noise floor.
- **Event Detection (`src/event_detection/`)**:
  - **STA/LTA Energy Analysis**: Compares Short-Term Average energy ($\tau \approx 20\text{ms}$) to rolling Long-Term Average baseline energy ($\tau \approx 300\text{ms}$) in subframes for high temporal onset precision.
  - **Refractory Cooldown Debouncing**: Configurable cooldown (60–100ms) prevents duplicate triggers on sound decay tails while capturing rapid successive shots/footsteps.
  - **Stereo Bias Estimation**: Computes initial Left/Right channel energy asymmetry (-1.0 = hard left, 0.0 = centered, +1.0 = hard right).
  - Emits strongly typed `SoundEvent` records carrying timestamp, peak dB, trigger ratio, and stereo bias.
- **User Interface (`src/ui/`)**:
  - PySide6 desktop window with modern dark slate styling.
  - Stereo `MeterBar` level indicators with dB markings and peak needles.
  - **Event Flash Badge**: Moments of detected sound events light up in cyan.
  - **Detector Tuning Controls**: Live interactive controls for threshold ratio, minimum floor, and cooldown ms.
  - **Live Event Log (`EventLogWidget`)**: Scrolling table displaying recent timestamped sound events with peak dB, ratio, and directional bias.
  - Polling at 60 FPS via `QTimer`, avoiding any UI thread blocking.
- **Configuration (`src/config/`)**:
  - Strongly typed dataclasses (`AudioConfig`, `MeterConfig`, `DetectorConfig`, `AppConfig`).
  - JSON serialization with robust error recovery and default fallback.

---

## Setup & Installation (Windows PowerShell)

### 1. Prerequisites
- Windows 10/11
- Python 3.11+ (Python 3.12 recommended)

### 2. Environment Setup
In PowerShell from the repository root:

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

---

## Running the Application

### 1. Interactive Desktop UI (Default)
To launch the full PySide6 live audio visualizer and event monitor:

```powershell
python -m src.main
```

### 2. Headless Console Diagnostic Mode
To run in the console without GUI (useful for automated testing or monitoring audio on headless systems):

```powershell
# Run headless monitor (Ctrl+C to stop)
python -m src.main --headless

# Run headless monitor for a fixed duration (e.g., 5 seconds)
python -m src.main --headless --duration 5
```

When transients occur in `--headless` mode, events are logged live to stdout:
```text
[SOUND EVENT evt_1] Peak: -8.2 dB | Ratio: 6.4x | Bias: L (-0.68)
```

### 3. List Audio Output Devices
To query and display all detected Windows playback endpoints:

```powershell
python -m src.main --list-devices
```

---

## Running the Automated Test Suite

All signal processing algorithms, ballistic decays, STA/LTA onset calculations, refractory cooldowns, and configuration serialization are tested using synthetic audio fixtures (impulses, rapid burst sequences, gradual crescendos, steady tones, and panned signals):

```powershell
pytest -v
```

---

## Technical Notes

1. **Adaptive Detection**:
   - Because the detector compares short-term attack energy to a rolling baseline (STA/LTA), it adapts automatically whether game master volume is high, medium, or low, without needing fixed absolute thresholds.
2. **Stereo Channel Bias**:
   - Standard stereo audio allows estimating lateral bias (Left vs. Right) from channel energy asymmetry. True 3D front/back elevation localization is not physically present in standard 2-channel stereo without binaural HRTF game simulation.
