# Sound Overlay Radar — Comprehensive Analysis

After reading every source file in the codebase, here is my deep analysis covering your three questions.

---

## 1. How to Make the Radar More Accurate

### 1A. Direction Estimation Pipeline Issues

#### Problem: Single-Subframe Direction Estimation (512 samples ≈ 10.7ms)
Your direction estimate is computed on a single 512-sample subframe — that's only ~10.7ms of audio at 48kHz. This is extremely tight for cross-correlation. The FFT frequency resolution at N=512 is `48000/512 ≈ 93.75 Hz`, meaning your multi-band decomposition has very coarse bin edges. At 512 samples, the `mask_low (80–1200 Hz)` band has only ~12 FFT bins, and `mask_high (4000+ Hz)` has ~10 bins.

**Fix:** When a transient is triggered, capture a **wider context window** around the trigger point (e.g., 1024–2048 samples backward + forward from the subframe that triggered). Feed this wider buffer to `DirectionEstimator.estimate()` instead of the raw 512-sample subframe. This dramatically improves both FFT frequency resolution and cross-correlation temporal precision.

#### Problem: Brick-Wall FFT Band Filtering Creates Spectral Leakage
In [`_extract_dominant_band()`](file:///d:/Projects/sound-overlay/src/direction_estimation/estimator.py#L194-L240), the FFT is computed without any windowing function. You zero out FFT bins outside the chosen band and IFFT back — this is a **rectangular spectral filter** that produces severe ringing artifacts (Gibbs phenomenon) in the reconstructed time-domain signal, smearing the ITD cross-correlation peak.

**Fix:** Apply a Hann or Hamming window before FFT, and use smooth roll-off filters (e.g., cosine-tapered band edges) instead of hard rectangular masks. Even better, use proper FIR bandpass filtering (e.g., `scipy.signal.firwin` + `lfilter`) for the band decomposition instead of FFT zeroing.

#### Problem: Non-GCC-PHAT Cross-Correlation
Your [`compute_gcc_phat_itd()`](file:///d:/Projects/sound-overlay/src/direction_estimation/cross_correlation.py#L11-L94) function name says "GCC-PHAT" but the implementation is standard energy-normalized cross-correlation. True GCC-PHAT divides the cross-power spectrum by its magnitude (`|G(f)|`), which whitens the spectrum and produces a much sharper, unambiguous correlation peak — critical for accurate ITD in reverberant game audio.

**Fix:** Replace:
```python
cross_spectrum = xl * np.conj(xr)
```
with:
```python
cross_spectrum = xl * np.conj(xr)
magnitude = np.abs(cross_spectrum) + 1e-10
cross_spectrum = cross_spectrum / magnitude  # GCC-PHAT whitening
```
This single change will significantly sharpen directional accuracy, especially in reverberant game environments (indoor maps, corridors, etc.).

#### Problem: ILD-to-Angle Mapping is Linear (Non-Physical)
In [`estimator.py` line 83-85](file:///d:/Projects/sound-overlay/src/direction_estimation/estimator.py#L83-L85):
```python
theta_ild_deg = (ild_db / 15.0) * 90.0
```
This assumes a linear relationship between ILD and angle. In reality, the ILD-to-angle function follows a sigmoidal/logarithmic curve — small ILD changes near center correspond to large angular shifts, while large ILD changes near 90° correspond to smaller angular changes. A linear map compresses the center and stretches the extremes.

**Fix:** Use a non-linear mapping:
```python
# Sigmoidal ILD-to-angle (closer to psychoacoustic reality)
ild_norm = max(-1.0, min(1.0, ild_db / head_shadow_max_db))
theta_ild_deg = math.asin(ild_norm) * (180.0 / math.pi)
```

### 1B. Event Detection Pipeline Issues

#### Problem: STA Updated Before Ratio Check
In [`detector.py` line 156](file:///d:/Projects/sound-overlay/src/event_detection/detector.py#L156), STA is updated **before** the trigger ratio is checked at line 176. This means the onset energy is already blended into STA by the time you compute the ratio, diluting the sharp STA/LTA spike that a sudden transient should produce.

**Fix:** Compute the ratio using the **previous** STA value (before updating), then update STA afterward. Or compute the ratio using the raw subframe energy directly against LTA:
```python
# Compute ratio BEFORE updating STA
ratio = frame_energy / (self._lta_energy + noise_floor)
# Then update STA for next iteration
self._sta_energy = (1.0 - alpha_sta) * self._sta_energy + alpha_sta * frame_energy
```

#### Problem: `is_onset` Check Uses STA Circularly
The onset verification ([`detector.py` line 172](file:///d:/Projects/sound-overlay/src/event_detection/detector.py#L172)):
```python
is_onset = frame_energy >= (self._sta_energy * 0.4)
```
But STA was **just updated** to include `frame_energy` on line 156. So this is essentially checking `frame_energy >= 0.4 * blend(old_sta, frame_energy)`, which is almost always true when `frame_energy` is large. This makes the onset gate nearly ineffective for its stated purpose of rejecting decay tails.

**Fix:** Use the pre-update STA for the onset check, or compare `frame_energy` against the **previous** subframe's raw energy to verify a rising edge.

---

## 2. Missing Features for AAA-Level Quality

### 2A. Critical Missing Features

| Feature | Why It Matters |
|---|---|
| **Audio Environment Health Dashboard** | Show sample rate, channel count, bit depth, buffer underruns, latency stats, and whether the audio stream is actually stereo or has collapsed to mono in real time |
| **Distance Estimation** | You have `peak_db` but never map it to approximate range. Games with distance attenuation models (all modern engines) produce predictable dB falloff. A coarse near/mid/far ring mapping gives hugely more useful radar blips |
| **Acoustic Echo / Reverb Detection** | Game maps have vastly different reverb characteristics (open field vs. building interior vs. tunnel). Detecting high reverb (via RT60-like energy decay analysis) and lowering confidence in reverberant environments prevents phantom directional readings from wall reflections |
| **Adaptive Sensitivity Profiles / Game Presets** | Different games have wildly different audio engines, dynamic ranges, and spatial implementations. Providing presets (Valorant, CS2, PUBG, Apex, Fortnite, etc.) or an auto-learning mode that tunes parameters over a play session would dramatically improve out-of-box accuracy |
| **Multi-Monitor DPI Awareness** | The overlay HUD doesn't handle DPI scaling or multi-monitor setups. On a 4K monitor at 150% Windows scaling, the overlay will be tiny or mispositioned |
| **Persistent Settings** | `AppConfig.save_to_file()` exists but is never called automatically. User calibrations and tuning are lost on restart |
| **System Tray / Minimize** | No tray icon — the main window cannot be minimized while keeping the overlay running. AAA utilities run from the tray |
| **Audio Output Device Change Detection** | If the user switches headphones mid-game (Bluetooth to wired), the app reconnects but resets all calibration without warning |
| **Performance Metrics** | No CPU usage tracking, processing latency histogram, or frame timing. Users on older hardware have no insight into whether the tool is keeping up |
| **Hotkey Controls** | No global hotkeys for toggling the overlay, resetting compass, muting pings, etc. without alt-tabbing out of the game |
| **First-Run Setup Wizard** | No onboarding for first-time users. The calibration workflow and mode selection are buried in the UI |

### 2B. Visual / UX Missing Features

| Feature | Why It Matters |
|---|---|
| **Range rings with distance labels** | Current rings are unlabeled — users can't tell what "33%" and "66%" represent |
| **History trail / radar sweep animation** | A rotating sweep beam (like classic radar) gives temporal context to when sounds were detected |
| **Sound intensity color gradient** | Current blips are uniform cyan regardless of volume. A heat gradient (dim→bright) based on dB would convey threat urgency |
| **Minimap anchor mode** | Allow pinning the overlay directly over a game's minimap and scaling to match, so directional intel integrates visually with the game's own spatial UI |
| **Audio waveform preview** | Show a tiny oscilloscope or spectrogram of the last detected transient, so power users can verify what triggered the alert |

---

## 3. Edge Cases Not Handled

### 3A. Windows / OS-Level Edge Cases

| Edge Case | Impact | Suggested Handling |
|---|---|---|
| **Mono audio system-wide** (you identified this) | All stereo cues collapse — ILD=0, ITD=0, every sound maps to 0° | Detect `channels==1` or `L≡R` correlation ≈ 1.0 over sustained periods → show permanent warning banner: "MONO AUDIO DETECTED — Directional radar disabled" |
| **Windows Spatial Sound enabled** (Windows Sonic / Dolby Atmos for Headphones / DTS:X) | Windows applies its own HRTF processing to the output **before** loopback captures it. This double-HRTF (game HRTF + Windows HRTF) creates mangled spectral cues with unpredictable ILD/ITD artifacts, making your pinna front/back ratio unreliable and potentially inverting directional readings | Detect via Windows registry or audio endpoint properties. Warn: "Windows Spatial Sound is active. Disable it in Sound Settings → Device Properties for best accuracy" |
| **Windows Loudness Equalization / Audio Enhancements** | Compresses dynamic range, equalizes L/R levels, destroys ILD cues. Can completely eliminate the level differences your detector depends on | Query audio endpoint enhancement state. Warn if enhancements are active |
| **Sample rate mismatch** | Your config defaults to 48kHz, but the system audio device might be 44.1kHz or 96kHz. `soundcard` may resample silently, introducing phase artifacts that corrupt ITD | Read the actual device sample rate at connection time and match it, or at minimum warn |
| **Exclusive mode applications** | Some games (especially with WASAPI Exclusive Mode) bypass the mixer entirely. Loopback capture gets silence even though the game is playing audio | Detect sustained silence when a known game process is running and warn the user |
| **USB audio device unplugged mid-game** | Your reconnect logic works, but calibration and threat clusters are silently lost | Persist calibration state across reconnects, and show a clear "Recalibration recommended" banner after device change |
| **VPN / Remote Desktop** | RDP sessions redirect audio to remote machine. Loopback captures remote audio, not local game audio. Also, Raw Input may behave differently | Detect RDP session and warn |
| **Virtual audio cables (VoiceMeeter, etc.)** | Users routing audio through VoiceMeeter may add latency and alter channel mapping | Detect known virtual audio device names and warn about potential latency |

### 3B. In-Game Settings Edge Cases

| Edge Case | Impact | Suggested Handling |
|---|---|---|
| **Game set to Mono audio output** | Same as system mono — all cues collapse to center | Detect via the `L≡R` correlation method described above |
| **Game's HRTF toggle OFF while you're in `hrtf_360` mode** | Your pinna spectral ratio front/back detection assumes the game is applying HRTF. If the game has HRTF disabled (stereo panning only), your `front_back_ratio` will produce random front/back flips because there's no spectral shaping to detect | Guide users to match: if game HRTF is OFF → use `stereo_180` mode. Consider auto-detection by measuring whether `front_back_ratio` variance is low (suggesting no HRTF spectral shaping present) |
| **Game master volume set very low (< 10%)** | All sounds arrive near the noise floor. STA/LTA ratios are valid but ILD precision degrades dramatically — a 1dB directional ILD cue at -50 dBFS is lost in quantization noise | Detect when sustained signal levels are below -45 dBFS and show a recommendation: "Game volume is very low — directional accuracy may be reduced" |
| **Game master volume at 100% + Windows at 100% (clipping)** | Audio clipping (samples hard-limited at ±1.0) destroys ILD cues because both channels are clamped to the same ceiling. Every loud sound maps to 0° regardless of actual direction | Detect persistent clipping (multiple consecutive samples at ±1.0 in both channels) and warn: "Audio clipping detected — reduce volume for accurate direction" |
| **Surround sound (5.1 / 7.1) configured in game but hardware is stereo** | Game downmixes surround to stereo, often with non-standard pan laws that don't match your ITD/ILD assumptions. Rear channels may be mixed in-phase or anti-phase depending on the engine | Detect more than 2 channels in the audio stream, or warn users to set the game to "Stereo" or "Headphones" output |
| **In-game equalizer / loudness normalization** | Games like Apex Legends and PUBG have in-game audio presets (e.g., "Treble Boost", "Loudness Equalization") that aggressively modify the spectral profile, destroying your pinna ratio assumptions | Document recommended in-game audio settings per game |
| **Night mode / reduced dynamic range** | Some games (PUBG, Warzone) have "Night Mode" or "Reduce Loud Sounds" that heavily compress dynamics. Gunshots and footsteps have very similar energy envelopes, making STA/LTA ratios smaller and less reliable | Lower the threshold ratio automatically, or detect compressed dynamic range and adjust |
| **In-game music / voice lines playing** | Ambient music, kill announcements, voice lines, and menu sounds are all captured. These are non-directional or have arbitrary panning, creating false radar pings | This is partially solved by process isolation, but the game's own non-spatial audio (UI sounds, music) still contaminates. Consider a spectral stationarity check — music/voice have sustained spectral content vs. transients |
| **Weapon skins with different audio** | Some games (Valorant, CS2) have weapon skins with altered firing sounds. Calibration done with one weapon won't match another | Recommend re-calibrating when changing weapons, or tracking calibration per weapon profile |

### 3C. Hardware / Physical Edge Cases

| Edge Case | Impact | Suggested Handling |
|---|---|---|
| **Speaker output (not headphones)** | Room acoustics completely invalidate stereo directional assumptions. Sound reflects off walls, creating wildly incorrect ILD/ITD readings | Detect speaker output (via Windows device type endpoint property if possible), or warn: "Headphones recommended for directional accuracy" |
| **One earbud removed / L or R channel dead** | If one channel is silent or significantly attenuated (broken cable, single earbud), all sounds bias to the working ear | Detect persistent unilateral level imbalance (e.g., one channel consistently > 15dB louder than the other over 5+ seconds) and warn |
| **Bluetooth headphones with SBC/AAC codec** | Bluetooth audio codecs add 50-200ms latency and can apply joint-stereo encoding that combines L/R channels, destroying subtle ILD cues | Detect Bluetooth audio endpoint and warn about degraded accuracy |
| **Mouse DPI changed mid-game** | Players who switch DPI profiles (e.g., sniper button on mouse) will see the compass yaw sensitivity become incorrect until recalibrated | Track if mouse delta patterns suddenly change (same physical movement → dramatically different counts) and notify |
| **Ultra-high DPI mice (16000+)** | Very high DPI produces extreme hardware count deltas even for tiny movements. The 0.05 deg/count default becomes extremely sensitive, causing the compass to spin wildly | Clamp maximum angular velocity per frame, or auto-detect unreasonable yaw accumulation rates |

### 3D. Application-Level Edge Cases

| Edge Case | Impact | Suggested Handling |
|---|---|---|
| **Process target crashes and restarts** (e.g., game crash → relaunch) | PID changes. The app shows "Target application closed" but doesn't auto-reattach when the game restarts | Periodically scan for the process name and automatically re-attach to the new PID |
| **Multiple instances of same game** | `process_scanner.py` may return multiple PIDs for the same executable name | Show all instances with PID disambiguation in the dropdown |
| **Game running as admin, app running as user** | `proctap` may fail to attach due to privilege mismatch. Process audio capture requires matching or higher privilege level | Detect privilege mismatch and prompt for elevation, or show a clear error |
| **Alt-tab / game minimized** | Game may reduce audio processing when unfocused, changing its audio output characteristics (lower sample rate, muted spatial, etc.) | Detect sudden signal characteristic changes coinciding with focus loss |
| **Thread starvation under CPU load** | Your audio capture thread is a daemon thread. Under heavy CPU load (game + streaming + Discord), Python's GIL may cause the capture thread to miss audio blocks, creating gaps in the STA/LTA baseline | Monitor timestamp gaps between processed chunks and flag when latency exceeds acceptable thresholds |

---

## Summary of Highest-Impact Changes

> [!IMPORTANT]
> **Top 5 changes that would most dramatically improve radar accuracy:**

1. **Implement true GCC-PHAT whitening** — single biggest directional accuracy improvement
2. **Widen the direction estimation buffer** from 512 to 1024–2048 samples around the trigger point
3. **Apply windowing function** (Hann) before FFT and use smooth bandpass filters instead of brick-wall rectangular masks
4. **Fix STA/LTA ordering** — compute ratio before updating STA to preserve the sharp onset spike
5. **Detect and warn about mono audio, Windows Spatial Sound, audio clipping, and speaker output** — these are the edge cases that silently make the radar completely useless without the user knowing why

> [!TIP]
> The application architecture is excellent — the decoupled pipeline, process isolation, threat clustering, and gyro compass are all strong engineering. The accuracy problems are concentrated in the DSP numerics (cross-correlation method, FFT filtering, buffer sizing) and the lack of environment sanity checks.
