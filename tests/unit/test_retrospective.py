from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.retrospective import (
    detect_regime_shifts,
    find_shape_discords,
    run_retrospective_audit,
)


def test_detect_regime_shifts_identifies_mean_jump():
    # 12 quiet windows (~0.2 msg/s), then 12 high-activity windows (~4.0 msg/s)
    velocities = [0.2, 0.3, 0.1, 0.2, 0.2, 0.3, 0.2, 0.1, 0.2, 0.3, 0.2, 0.2] + [
        4.0, 4.2, 3.8, 4.1, 4.0, 3.9, 4.2, 4.1, 4.0, 3.9, 4.2, 4.0
    ]

    shifts = detect_regime_shifts(velocities, min_size=6)

    assert len(shifts) >= 1
    assert any(10 <= idx <= 14 for idx in shifts)


def test_find_shape_discords_locates_unique_waveform():
    # Repeating sawtooth baseline with one sudden sharp spike+drop discord at index 18..23
    baseline = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    velocities = baseline * 3 + [1.0, 15.0, 25.0, 3.0, 1.0, 1.0] + baseline * 2

    discords = find_shape_discords(velocities, subsequence_len=6, top_k=1)

    assert len(discords) == 1
    start_idx, dist = discords[0]
    assert 14 <= start_idx <= 21
    assert dist > 0.0


def test_run_retrospective_audit_matches_overlapping_peak():
    t0 = datetime.now(timezone.utc)
    baseline = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    velocities = baseline * 2 + [1.0, 12.0, 22.0, 4.0, 1.0, 1.0] + baseline * 2

    windows = [
        SimpleNamespace(
            window_start=t0 + timedelta(seconds=i * 10),
            window_end=t0 + timedelta(seconds=(i + 1) * 10),
            chat_velocity=v,
        )
        for i, v in enumerate(velocities)
    ]
    peaks = [
        SimpleNamespace(
            id=99,
            start_time=t0 + timedelta(seconds=120),
            end_time=t0 + timedelta(seconds=160),
        )
    ]

    audit = run_retrospective_audit("vid_audit", windows, peaks, stream_start=t0)

    assert audit.video_id == "vid_audit"
    assert audit.total_windows == len(windows)
    assert len(audit.shape_discords) >= 1
    assert any(d.matched_peak_id == 99 for d in audit.shape_discords)
