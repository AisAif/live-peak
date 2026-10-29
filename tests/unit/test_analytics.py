import pytest

from datetime import datetime, timedelta, timezone
from app.services.analytics import SlidingWindowAnalytics
from app.services.merger import PeakMerger
from app.models.domain import ChatMessage, WindowStats


def _chat(ts: datetime, text: str = "hello world") -> ChatMessage:
    return ChatMessage(
        video_id="test_123",
        author_name="user",
        message=text,
        timestamp=ts
    )


def test_analytics_and_peak_merging():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        enable_ewma_detection=False,
        enable_cusum_detection=False
    )
    merger = PeakMerger(video_id="test_123", merge_gap_seconds=30)

    # 1. Populate baseline history with slight natural variation (1 to 3 msgs per window)
    now = datetime.now(timezone.utc)
    baseline_counts = [1, 2, 2, 3, 2, 1, 2, 3, 2, 1]
    for count in baseline_counts:
        analytics.current_messages = [
            ChatMessage(video_id="test_123", author_name="user", message="hello world", timestamp=now)
            for _ in range(count)
        ]
        stats = analytics.finalize_window()
        assert stats.is_peak is False
        peak_event = merger.process_window(stats)
        assert peak_event is None

    # 2. Simulate sudden peak window (20 msgs burst)
    analytics.current_messages = [
        ChatMessage(video_id="test_123", author_name="user", message="WKWKWK GOAL 🔥", timestamp=now)
        for _ in range(20)
    ]
    peak_stats = analytics.finalize_window()
    assert peak_stats.is_peak is True
    assert peak_stats.z_score >= 2.0
    assert any(k in ["wkwkwk", "goal"] for k in [kw.lower() for kw in peak_stats.top_keywords])

    # Process peak window in merger
    merger.process_window(peak_stats)
    assert merger.current_active_peak is not None

    # 3. Flush active peak
    final_peak = merger.flush()
    assert final_peak is not None
    assert final_peak.video_id == "test_123"
    assert final_peak.total_messages == 20


def test_process_message_does_not_drop_boundary_message():
    analytics = SlidingWindowAnalytics(video_id="test_123", window_duration_seconds=10)
    start = analytics.current_window_start

    analytics.process_message(_chat(start + timedelta(seconds=1)))
    completed = analytics.process_message(_chat(start + timedelta(seconds=11)))

    assert len(completed) == 1
    assert completed[0].message_count == 1
    # The message that closed the window belongs to the next window
    assert len(analytics.current_messages) == 1


def test_tick_emits_zero_message_windows_for_silence():
    analytics = SlidingWindowAnalytics(video_id="test_123", window_duration_seconds=10)
    start = analytics.current_window_start

    completed = analytics.tick(start + timedelta(seconds=25))

    assert len(completed) == 2
    assert all(w.message_count == 0 for w in completed)
    assert all(w.chat_velocity == 0.0 for w in completed)
    assert analytics.current_window_start == start + timedelta(seconds=20)


def test_burst_after_silence_is_detected():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        min_baseline_windows=5
    )
    start = analytics.current_window_start

    analytics.tick(start + timedelta(seconds=60))
    for _ in range(20):
        analytics.process_message(_chat(start + timedelta(seconds=61), "GOAL 🔥"))

    completed = analytics.process_message(_chat(start + timedelta(seconds=71)))

    assert len(completed) == 1
    assert completed[0].message_count == 20
    assert completed[0].is_peak is True
    assert completed[0].z_score >= 2.0
    assert "z" in (completed[0].peak_source or "")


def test_peak_padding_is_clamped_to_stream_bounds():
    start = datetime.now(timezone.utc)
    merger = PeakMerger(
        video_id="test_123",
        padding_before=15,
        padding_after=15,
        stream_start=start
    )
    peak_window = WindowStats(
        video_id="test_123",
        window_start=start,
        window_end=start + timedelta(seconds=10),
        message_count=10,
        chat_velocity=1.0,
        z_score=3.0,
        is_peak=True
    )

    assert merger.process_window(peak_window) is None
    final_peak = merger.flush(end_time=start + timedelta(seconds=20))

    assert final_peak is not None
    assert final_peak.padded_start_time == start
    assert final_peak.padded_end_time == start + timedelta(seconds=20)
    assert final_peak.video_start_time == "00:00"
    assert final_peak.video_end_time == "00:20"
    assert final_peak.start_offset_seconds == 0.0
    assert final_peak.end_offset_seconds == 20.0


def _feed_baseline(analytics: SlidingWindowAnalytics, counts: list[int]) -> None:
    for count in counts:
        analytics.current_messages = [
            _chat(datetime.now(timezone.utc)) for _ in range(count)
        ]
        analytics.finalize_window()


def test_mad_detects_peak_despite_baseline_outlier():
    baseline = [1, 2, 1, 2, 1, 2, 1, 2, 1, 100]
    burst = [20]

    robust = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        z_score_method="mad",
        enable_ewma_detection=False,
        enable_cusum_detection=False
    )
    _feed_baseline(robust, baseline)
    _feed_baseline(robust, burst)
    assert robust.history[-1].is_peak is True

    standard = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        z_score_method="std",
        enable_ewma_detection=False,
        enable_cusum_detection=False
    )
    _feed_baseline(standard, baseline)
    _feed_baseline(standard, burst)
    assert standard.history[-1].is_peak is False


def test_mad_falls_back_to_std_when_baseline_mad_is_zero():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        z_score_method="mad",
        enable_ewma_detection=False,
        enable_cusum_detection=False
    )
    _feed_baseline(analytics, [1, 1, 1, 1, 1, 3])

    # Median = 0.1, MAD = 0 -> std fallback should still be usable
    _feed_baseline(analytics, [10])
    stats = analytics.history[-1]

    assert stats.is_peak is True
    assert stats.z_score > 0.0


def test_invalid_z_score_method_is_rejected():
    with pytest.raises(ValueError):
        SlidingWindowAnalytics(video_id="test_123", z_score_method="unknown")


def test_ewma_detects_sustained_shift():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=100.0,
        enable_ewma_detection=True,
        ewma_alpha=0.3,
        ewma_z_threshold=2.0,
        enable_cusum_detection=False
    )
    _feed_baseline(analytics, [1, 2, 1, 2, 1, 2, 1, 2, 1, 2])
    _feed_baseline(analytics, [5, 5, 5, 5, 5])

    ewma_peaks = [
        w for w in analytics.history if "ewma" in (w.peak_source or "")
    ]
    assert ewma_peaks
    assert ewma_peaks[0].z_score < 100.0


def test_cusum_detects_persistent_increase():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=100.0,
        enable_ewma_detection=False,
        enable_cusum_detection=True,
        cusum_drift_sigma=0.5,
        cusum_threshold_sigma=3.0
    )
    _feed_baseline(analytics, [1, 2, 1, 2, 1, 2, 1, 2, 1, 2])
    _feed_baseline(analytics, [4, 4, 4, 4, 4])

    cusum_peaks = [
        w for w in analytics.history if "cusum" in (w.peak_source or "")
    ]
    assert cusum_peaks
    assert cusum_peaks[0].z_score < 100.0


def test_invalid_ewma_alpha_is_rejected():
    with pytest.raises(ValueError):
        SlidingWindowAnalytics(video_id="test_123", ewma_alpha=0.0)
