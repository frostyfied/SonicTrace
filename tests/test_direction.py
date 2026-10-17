"""Unit tests for direction estimation, GCC-PHAT ITD, ILD, and spatial gating."""

from __future__ import annotations

import math
import numpy as np
import pytest

from src.config.settings import SpatialConfig
from src.direction_estimation.cross_correlation import compute_gcc_phat_itd
from src.direction_estimation.estimator import DirectionEstimator
from tests.conftest import make_sine_wave


def test_spatial_config_validation() -> None:
    config = SpatialConfig()
    assert config.self_sound_threshold_db == -3.5
    assert config.max_itd_ms == 0.70
    assert config.min_confidence == 0.35

    with pytest.raises(ValueError, match="max_itd_ms must be positive"):
        SpatialConfig(max_itd_ms=-0.5)

    with pytest.raises(ValueError, match="min_confidence must be in"):
        SpatialConfig(min_confidence=1.5)

    with pytest.raises(ValueError, match="Weights must be non-negative"):
        SpatialConfig(itd_weight=-0.2)


def test_gcc_phat_pure_delay_retrieval() -> None:
    fs = 48000
    dur_s = 0.02  # 20ms burst
    tone = make_sine_wave(frequency_hz=1500.0, amplitude=0.8, duration_s=dur_s, sample_rate=fs)

    # Shift Right channel by +12 samples (0.25 ms delay, sound arriving at Right first)
    shift_samples = 12
    expected_itd_ms = (shift_samples / float(fs)) * 1000.0  # +0.25 ms

    left = np.pad(tone, (shift_samples, 0))[: len(tone)]
    right = tone

    itd_ms, conf = compute_gcc_phat_itd(left, right, sample_rate=fs, max_itd_ms=0.70)

    # Right leads Left -> positive ITD
    assert itd_ms == pytest.approx(expected_itd_ms, abs=0.04)
    assert conf > 0.65


def test_gcc_phat_negative_delay_retrieval() -> None:
    fs = 48000
    tone = make_sine_wave(frequency_hz=1200.0, amplitude=0.8, duration_s=0.02, sample_rate=fs)

    # Shift Left channel (sound arriving at Left first)
    shift_samples = 14
    expected_itd_ms = -(shift_samples / float(fs)) * 1000.0  # -0.2917 ms

    left = tone
    right = np.pad(tone, (shift_samples, 0))[: len(tone)]

    itd_ms, conf = compute_gcc_phat_itd(left, right, sample_rate=fs, max_itd_ms=0.70)

    # Left leads Right -> negative ITD
    assert itd_ms == pytest.approx(expected_itd_ms, abs=0.04)
    assert conf > 0.65


def test_zero_delay_centered_sound() -> None:
    fs = 48000
    tone = make_sine_wave(frequency_hz=1000.0, amplitude=0.5, duration_s=0.02, sample_rate=fs)

    estimator = DirectionEstimator(sample_rate=fs)
    estimate = estimator.estimate(tone, tone, peak_db=-15.0)

    assert estimate.itd_ms == pytest.approx(0.0, abs=0.02)
    assert estimate.ild_db == pytest.approx(0.0, abs=0.1)
    # Zero delay / zero ILD must map to 0.0° (Ahead / Front)
    assert estimate.azimuth_deg == pytest.approx(0.0, abs=1.0)
    assert not estimate.is_self_sound
    assert not estimate.is_uncertain


def test_ild_dominant_lateral_bias() -> None:
    fs = 48000
    tone_loud = make_sine_wave(frequency_hz=3000.0, amplitude=0.8, duration_s=0.02, sample_rate=fs)
    tone_quiet = make_sine_wave(frequency_hz=3000.0, amplitude=0.1, duration_s=0.02, sample_rate=fs)

    estimator = DirectionEstimator(sample_rate=fs)

    # 1. Right much louder (+18 dB ILD)
    est_r = estimator.estimate(tone_quiet, tone_loud, peak_db=-10.0)
    assert est_r.ild_db > 10.0
    assert est_r.azimuth_deg > 30.0  # Points into right hemisphere

    # 2. Left much louder (-18 dB ILD)
    est_l = estimator.estimate(tone_loud, tone_quiet, peak_db=-10.0)
    assert est_l.ild_db < -10.0
    assert est_l.azimuth_deg < -30.0  # Points into left hemisphere


def test_self_sound_gating() -> None:
    fs = 48000
    # Point blank weapon: peak = -1.0 dBFS (> self_sound_threshold_db of -3.5)
    tone = make_sine_wave(frequency_hz=800.0, amplitude=0.9, duration_s=0.02, sample_rate=fs)

    # 1. With require_mouse_for_self=False (audio-only test mode)
    estimator = DirectionEstimator(sample_rate=fs, config=SpatialConfig(require_mouse_for_self=False))
    # Centered loud gunshot
    self_shot = estimator.estimate(tone, tone, peak_db=-1.0)
    assert self_shot.is_self_sound
    assert abs(self_shot.azimuth_deg) <= 5.0

    # Distant enemy gunshot: centered, but peak = -18.0 dBFS
    enemy_shot = estimator.estimate(tone, tone, peak_db=-18.0)
    assert not enemy_shot.is_self_sound
    assert enemy_shot.azimuth_deg == pytest.approx(0.0, abs=1.0)

    # 2. In PUBG Sound Lab mode (require_mouse_for_self=True, player is NOT clicking):
    # Even a loud -1.0 dBFS gunshot directly from Ahead MUST NOT be marked as self!
    pubg_estimator = DirectionEstimator(sample_rate=fs, config=SpatialConfig(require_mouse_for_self=True))
    pubg_enemy_shot = pubg_estimator.estimate(tone, tone, peak_db=-1.0, is_firing=False)
    assert not pubg_enemy_shot.is_self_sound


def test_uncorrelated_noise_uncertainty() -> None:
    fs = 48000
    rng = np.random.default_rng(seed=42)
    # 512 samples of independent white noise
    noise_l = rng.normal(0.0, 0.1, 512).astype(np.float32)
    noise_r = rng.normal(0.0, 0.1, 512).astype(np.float32)

    estimator = DirectionEstimator(sample_rate=fs)
    estimate = estimator.estimate(noise_l, noise_r, peak_db=-20.0)

    # Uncorrelated noise lacks coherent correlation peak -> should be marked uncertain
    assert estimate.is_uncertain
    assert estimate.confidence < 0.50


def test_bilateral_self_sound_pins_azimuth_to_zero() -> None:
    fs = 48000
    # Simulate a wide-stereo weapon held in right hand:
    # Right channel has full amplitude 0.95 (-0.45 dBFS).
    # Left channel has amplitude 0.70 (-3.1 dBFS), and leads by 0.25ms (causing angle swing without gating).
    tone_r = make_sine_wave(frequency_hz=1200.0, amplitude=0.95, duration_s=0.02, sample_rate=fs)
    delay_samples = int(round(0.00025 * fs))
    tone_l = np.roll(tone_r * (0.70 / 0.95), delay_samples)

    estimator = DirectionEstimator(sample_rate=fs, config=SpatialConfig(require_mouse_for_self=False))
    estimate = estimator.estimate(tone_l, tone_r, peak_db=-0.45)

    # Both channels exceed bilateral_self_threshold_db (-4.0 dBFS)
    assert estimate.is_self_sound
    # Azimuth MUST be pinned to 0.0° (Center/Origin) instead of swinging left/right!
    assert estimate.azimuth_deg == 0.0


def test_weapon_calibrator_workflow() -> None:
    from src.direction_estimation.calibrator import CalibrationState, WeaponCalibrator

    calibrator = WeaponCalibrator(duration_s=2.0, target_shots=3, safety_margin_db=2.0)
    assert calibrator.state == CalibrationState.IDLE

    calibrator.start()
    assert calibrator.state == CalibrationState.RECORDING

    # Register shot 1: L = -2.0 dB, R = -1.0 dB
    res1 = calibrator.register_shot(-2.0, -1.0)
    assert res1 is None
    assert calibrator.shots_recorded == 1

    # Register shot 2: L = -2.2 dB, R = -0.8 dB
    res2 = calibrator.register_shot(-2.2, -0.8)
    assert res2 is None
    assert calibrator.shots_recorded == 2

    # Register shot 3: L = -1.8 dB, R = -1.2 dB (hits target_shots=3)
    res3 = calibrator.register_shot(-1.8, -1.2)
    assert res3 is not None
    assert res3.success
    assert res3.shot_count == 3
    # Average L = -2.0, Average R = -1.0. Quieter is -2.0. Margin = 2.0 -> Recommended = -4.0 dBFS
    assert res3.recommended_threshold_db == -4.0
    assert calibrator.state == CalibrationState.COMPLETED


def test_stereo_amplitude_panned_directional_sound() -> None:
    fs = 48000
    # Simulate a game gunshot panned hard-left using stereo pan law (zero ITD delay, -12 dB ILD):
    t = np.linspace(0, 0.02, int(0.02 * fs), endpoint=False)
    burst = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    left_shot = burst * 0.80  # loud on left (-1.9 dBFS)
    right_shot = burst * 0.15 # quiet on right (-16.5 dBFS)

    estimator = DirectionEstimator(sample_rate=fs)
    estimate = estimator.estimate(left_shot, right_shot, peak_db=-1.9)

    # Must NOT be classified as self sound (despite high peak_db) because energy is lateral
    assert not estimate.is_self_sound
    # Must NOT be locked at 0.0°; must point strongly to the left (between -50° and -90°)
    assert estimate.azimuth_deg < -45.0
    assert estimate.ild_db < -10.0


def test_stereo_amplitude_panned_right_sound() -> None:
    fs = 48000
    # Gunshot panned hard-right:
    t = np.linspace(0, 0.02, int(0.02 * fs), endpoint=False)
    burst = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    left_shot = burst * 0.15
    right_shot = burst * 0.80

    estimator = DirectionEstimator(sample_rate=fs)
    estimate = estimator.estimate(left_shot, right_shot, peak_db=-1.9)

    assert not estimate.is_self_sound
    assert estimate.azimuth_deg > 45.0
    assert estimate.ild_db > 10.0


def test_front_vs_behind_pinna_spectral_discrimination() -> None:
    """Validate that high-shelf roll-off classifies sound as rear in HRTF mode."""
    fs = 48000
    dur = 0.025
    t = np.linspace(0, dur, int(dur * fs), endpoint=False).astype(np.float32)

    # 1. Front sound: strong mid-band (2.5 kHz) AND strong high-frequency presence (10 kHz)
    front_wave = (0.4 * np.sin(2 * np.pi * 2500 * t) + 0.5 * np.sin(2 * np.pi * 10000 * t)).astype(np.float32)
    # Panned slightly right (ILD ~ +3 dB)
    left_front = front_wave * 0.5
    right_front = front_wave * 0.7

    cfg = SpatialConfig(spatial_mode="hrtf_360", enable_front_back=True, rear_ratio_threshold=0.35)
    estimator = DirectionEstimator(config=cfg, sample_rate=fs)

    est_front = estimator.estimate(left_front, right_front, peak_db=-10.0)
    assert not est_front.is_rear
    assert est_front.front_back_ratio >= 0.35
    assert est_front.azimuth_360_deg == pytest.approx(est_front.azimuth_deg)

    # 2. Rear sound: pinna shadow filters out >7.5 kHz, keeping strong mid-band (2.5 kHz)
    rear_wave = (0.7 * np.sin(2 * np.pi * 2500 * t) + 0.02 * np.sin(2 * np.pi * 10000 * t)).astype(np.float32)
    left_rear = rear_wave * 0.5
    right_rear = rear_wave * 0.7

    est_rear = estimator.estimate(left_rear, right_rear, peak_db=-10.0)
    assert est_rear.is_rear
    assert est_rear.front_back_ratio < 0.35
    # Lateral angle is positive (Right), so 360 bearing must be in the rear hemisphere (+90° to +180°)
    assert est_rear.azimuth_360_deg > 90.0
    assert est_rear.azimuth_360_deg == pytest.approx(180.0 - est_rear.azimuth_deg, abs=0.1)


def test_stereo_180_mode_disables_rear_classification() -> None:
    """Games without HRTF (stereo_180 mode) must never guess rear hemisphere from missing highs."""
    fs = 48000
    dur = 0.025
    t = np.linspace(0, dur, int(dur * fs), endpoint=False).astype(np.float32)

    # Sound with no high frequencies
    low_high_wave = (0.7 * np.sin(2 * np.pi * 1800 * t)).astype(np.float32)
    left = low_high_wave * 0.4
    right = low_high_wave * 0.8

    cfg = SpatialConfig(spatial_mode="stereo_180")
    estimator = DirectionEstimator(config=cfg, sample_rate=fs)

    est = estimator.estimate(left, right, peak_db=-10.0)
    assert not est.is_rear
    assert est.azimuth_360_deg == pytest.approx(est.azimuth_deg)


def test_pubg_direct_facing_gunshot_never_shows_behind() -> None:
    """PUBG PC Sound Lab test: Facing enemy gunshot (0°) must NEVER flip to 180° BEHIND."""
    fs = 48000
    dur = 0.025
    t = np.linspace(0, dur, int(dur * fs), endpoint=False).astype(np.float32)

    # Realistic gunshot: dominant low-mid crack (2000 Hz) + low barrel punch (180 Hz), zero high frequencies (>7500 Hz)
    gunshot = (0.7 * np.sin(2 * np.pi * 2000 * t) + 0.5 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    left_shot = gunshot * 0.6
    right_shot = gunshot * 0.6  # Perfectly centered (facing shooter at 0°)

    # 1. In default stereo_180 mode:
    est_default = DirectionEstimator(sample_rate=fs).estimate(left_shot, right_shot, peak_db=-6.0)
    assert not est_default.is_rear
    assert est_default.azimuth_deg == 0.0
    assert est_default.azimuth_360_deg == 0.0

    # 2. In hrtf_360 mode with enable_front_back=True:
    cfg_360 = SpatialConfig(spatial_mode="hrtf_360", enable_front_back=True, rear_ratio_threshold=0.35)
    est_360 = DirectionEstimator(config=cfg_360, sample_rate=fs).estimate(left_shot, right_shot, peak_db=-6.0)
    # Centered sounds (|azimuth| <= 6.0°) are strictly protected from rear flipping!
    assert not est_360.is_rear
    assert est_360.azimuth_deg == 0.0
    assert est_360.azimuth_360_deg == 0.0


def test_pubg_near_center_gunshot_preserves_front_bearing() -> None:
    """PUBG PC Sound Lab: Slight aim offset (+3° / -3°) must stay in FRONT, never flipped to ±177°."""
    fs = 48000
    dur = 0.025
    t = np.linspace(0, dur, int(dur * fs), endpoint=False).astype(np.float32)

    gunshot = (0.7 * np.sin(2 * np.pi * 1800 * t)).astype(np.float32)
    # Very slight stereo imbalance (near-center)
    left_shot = gunshot * 0.58
    right_shot = gunshot * 0.62

    cfg_360 = SpatialConfig(spatial_mode="hrtf_360", enable_front_back=True)
    estimator = DirectionEstimator(config=cfg_360, sample_rate=fs)

    est = estimator.estimate(left_shot, right_shot, peak_db=-6.0)
    assert not est.is_rear
    # Must stay in the front arc near 0°, NEVER 170°+ behind!
    assert abs(est.azimuth_deg) < 10.0
    assert abs(est.azimuth_360_deg) < 10.0







def test_high_frequency_transient_itd_no_cycle_skipping() -> None:
    """High-frequency decaying transient (5.5 kHz bullet crack) must recover true ITD without carrier cycle skipping."""
    fs = 48000
    t = np.arange(2048) / float(fs)
    crack = (np.exp(-t * 120.0) * np.sin(2.0 * np.pi * 5500.0 * t)).astype(np.float32)
    # Delay Left channel by +19 samples (+0.396 ms -> Right hemisphere)
    right = crack * 0.70
    left = np.pad(crack * 0.60, (19, 0))[:2048]

    estimator = DirectionEstimator(sample_rate=fs)
    est = estimator.estimate(left, right, peak_db=-10.0)

    assert est.itd_ms == pytest.approx(0.396, abs=0.03)
    assert est.azimuth_deg > 10.0


def test_low_dominant_transient_preserves_high_band_ild() -> None:
    """A bass-heavy footstep thud (250 Hz) + high-frequency scuff (3500 Hz) must preserve the high-band ILD cue."""
    fs = 48000
    t = np.arange(2048) / float(fs)
    thud_low = (0.70 * np.sin(2.0 * np.pi * 250.0 * t)).astype(np.float32)
    scuff_r = (0.25 * np.sin(2.0 * np.pi * 3500.0 * t)).astype(np.float32)
    scuff_l = scuff_r * 0.25  # +12 dB ILD in the 3.5 kHz head-shadow band

    estimator = DirectionEstimator(sample_rate=fs)
    est = estimator.estimate(thud_low + scuff_l, thud_low + scuff_r, peak_db=-20.0)

    assert est.dominant_band == "low"
    assert est.ild_db > 8.0
    assert est.azimuth_deg > 30.0


def test_corridor_reflection_haas_precedence_window() -> None:
    """Direct sound followed 8ms later by an opposite-wall reflection must prioritize the direct arrival."""
    fs = 48000
    burst_len = 240
    tb = np.arange(burst_len) / float(fs)
    wave = (np.hanning(burst_len) * np.sin(2.0 * np.pi * 1600.0 * tb)).astype(np.float32)

    sig_l = np.zeros(2048, dtype=np.float32)
    sig_r = np.zeros(2048, dtype=np.float32)
    # Direct wave from Right at sample 600
    sig_r[600 : 600 + burst_len] += wave * 0.75
    sig_l[610 : 610 + burst_len] += wave * 0.45
    # Opposite-wall reflection from Left at sample 980 (~7.9 ms later)
    sig_l[980 : 980 + burst_len] += wave * 0.72
    sig_r[992 : 992 + burst_len] += wave * 0.42

    estimator = DirectionEstimator(sample_rate=fs)
    est = estimator.estimate(sig_l, sig_r, peak_db=-10.0)

    # Must stay in the Right (+azimuth) hemisphere of the direct arrival
    assert est.azimuth_deg > 5.0


def test_distant_front_gunshot_not_flipped_to_rear_in_hrtf_360() -> None:
    """Distant muffled front gunshots (LPF < 4 kHz, peak_db < -20 dBFS) must not flip to rear in hrtf_360 mode."""
    fs = 48000
    t = np.arange(2048) / float(fs)
    dist_shot = (0.6 * np.sin(2.0 * np.pi * 1800.0 * t) + 0.3 * np.sin(2.0 * np.pi * 3200.0 * t)).astype(np.float32)

    cfg = SpatialConfig(spatial_mode="hrtf_360", enable_front_back=True)
    estimator = DirectionEstimator(config=cfg, sample_rate=fs)
    est = estimator.estimate(dist_shot * 0.50, dist_shot * 0.75, peak_db=-28.0)

    assert not est.is_rear
    assert 0.0 < est.azimuth_360_deg < 45.0
