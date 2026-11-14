import pytest

from datetime import datetime, timedelta, timezone
from app.services.analytics import SlidingWindowAnalytics
from app.services.merger import PeakMerger
from app.models.domain import ChatMessage, WindowStats


def _chat(ts: datetime, text: str = "hello world", author: str = "user") -> ChatMessage:
    return ChatMessage(
        video_id="test_123",
        author_name=author,
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

    # 2. Simulate sudden peak window (20 msgs burst from distinct viewers)
    analytics.current_messages = [
        ChatMessage(video_id="test_123", author_name=f"viewer_{i}", message="WKWKWK GOAL 🔥", timestamp=now)
        for i in range(20)
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
    for i in range(20):
        analytics.process_message(_chat(start + timedelta(seconds=61), "GOAL 🔥", author=f"viewer_{i}"))

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
            _chat(datetime.now(timezone.utc), author=f"viewer_{i}") for i in range(count)
        ]
        analytics.finalize_window()


def test_mad_detects_peak_despite_baseline_outlier():
    baseline = [1, 2, 1, 2, 1, 2, 1, 2, 1]
    burst = [20]

    def feed_with_spam_outlier(analytics: SlidingWindowAnalytics) -> None:
        _feed_baseline(analytics, baseline)
        # Single-author 100-message spam outlier (blocked by spam gate, enters baseline)
        now = datetime.now(timezone.utc)
        analytics.current_messages = [_chat(now, author="spammer") for _ in range(100)]
        analytics.finalize_window()
        _feed_baseline(analytics, burst)

    robust = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        z_score_method="mad",
        enable_ewma_detection=False,
        enable_cusum_detection=False
    )
    feed_with_spam_outlier(robust)
    assert robust.history[-1].is_peak is True

    standard = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        z_score_method="std",
        enable_ewma_detection=False,
        enable_cusum_detection=False
    )
    feed_with_spam_outlier(standard)
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


def test_window_stats_tracks_unique_authors_diversity_and_superchats():
    analytics = SlidingWindowAnalytics(video_id="test_123", window_duration_seconds=10)
    now = datetime.now(timezone.utc)
    analytics.current_messages = [
        ChatMessage(video_id="test_123", author_name=f"user_{i}", message="POG 🔥", timestamp=now, amount_str="$5" if i == 0 else None)
        for i in range(10)
    ]
    stats = analytics.finalize_window()
    assert stats.unique_authors == 10
    assert stats.diversity_ratio == 1.0
    assert stats.superchat_count == 1


def test_peak_merger_hysteresis_extends_peak_without_splitting():
    start = datetime.now(timezone.utc)
    merger = PeakMerger(
        video_id="test_123",
        merge_gap_seconds=10,
        hysteresis_low_z=1.2,
        padding_before=10,
        padding_after=10,
        stream_start=start,
    )

    w1 = WindowStats(
        video_id="test_123",
        window_start=start,
        window_end=start + timedelta(seconds=10),
        message_count=20,
        unique_authors=18,
        diversity_ratio=0.9,
        chat_velocity=2.0,
        emoji_count=10,
        z_score=3.2,
        peak_source="z",
        is_peak=True,
    )
    # Below main threshold (is_peak=False), but above hysteresis_low_z=1.2
    w2 = WindowStats(
        video_id="test_123",
        window_start=start + timedelta(seconds=10),
        window_end=start + timedelta(seconds=20),
        message_count=10,
        unique_authors=9,
        diversity_ratio=0.9,
        chat_velocity=1.0,
        emoji_count=4,
        z_score=1.5,
        is_peak=False,
    )
    # Drops below hysteresis_low_z=1.2 and exceeds merge_gap_seconds=10
    w3 = WindowStats(
        video_id="test_123",
        window_start=start + timedelta(seconds=35),
        window_end=start + timedelta(seconds=45),
        message_count=1,
        unique_authors=1,
        diversity_ratio=1.0,
        chat_velocity=0.1,
        z_score=0.2,
        is_peak=False,
    )

    assert merger.process_window(w1) is None
    assert merger.process_window(w2) is None
    completed = merger.process_window(w3)

    assert completed is not None
    assert completed.end_time == start + timedelta(seconds=20)
    assert completed.total_messages == 30
    assert completed.unique_authors == 27
    assert completed.diversity_ratio == 0.9
    assert completed.highlight_score > 0.0
    assert completed.peak_sources == ["z"]


def test_spam_gate_blocks_single_author_burst():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        z_score_threshold=2.0,
        min_unique_authors=3,
    )
    _feed_baseline(analytics, [1, 2, 1, 2, 1, 2, 1, 2])
    now = datetime.now(timezone.utc)

    # 1 spammer sending 30 messages -> blocked by anti-spam gate
    analytics.current_messages = [
        _chat(now, "SPAM COPYPASTA", author="spam_bot") for _ in range(30)
    ]
    spam_stats = analytics.finalize_window()
    assert spam_stats.z_score >= 2.0
    assert spam_stats.unique_authors == 1
    assert spam_stats.is_peak is False


def test_winsorized_baseline_prevents_self_pollution_after_long_peak():
    analytics = SlidingWindowAnalytics(
        video_id="test_123",
        window_duration_seconds=10,
        sliding_window_size=15,
        z_score_threshold=2.5,
        min_unique_authors=3,
    )
    _feed_baseline(analytics, [1, 2, 1, 2, 1, 2, 1, 2, 1, 2])
    # Sustained 6-window massive peak
    _feed_baseline(analytics, [30, 30, 30, 30, 30, 30])
    # One quiet window, then a moderate burst (15 msgs)
    _feed_baseline(analytics, [2, 15])

    assert analytics.history[-1].is_peak is True


def test_peak_merger_deduplicates_unique_authors_across_windows():
    start = datetime.now(timezone.utc)
    merger = PeakMerger(video_id="test_123", stream_start=start)

    w1 = WindowStats(
        video_id="test_123",
        window_start=start,
        window_end=start + timedelta(seconds=10),
        message_count=3,
        unique_authors=3,
        diversity_ratio=1.0,
        author_names=["alice", "bob", "charlie"],
        chat_velocity=0.3,
        z_score=3.5,
        is_peak=True,
    )
    w2 = WindowStats(
        video_id="test_123",
        window_start=start + timedelta(seconds=10),
        window_end=start + timedelta(seconds=20),
        message_count=3,
        unique_authors=3,
        diversity_ratio=1.0,
        author_names=["bob", "charlie", "dave"],
        chat_velocity=0.3,
        z_score=3.2,
        is_peak=True,
    )

    merger.process_window(w1)
    merger.process_window(w2)
    final_peak = merger.flush(end_time=start + timedelta(seconds=20))

    assert final_peak is not None
    assert final_peak.total_messages == 6
    assert final_peak.unique_authors == 4
    assert final_peak.diversity_ratio == round(4 / 6, 4)


def test_peak_merger_accumulates_sample_messages_and_category():
    start = datetime.now(timezone.utc)
    merger = PeakMerger(video_id="test_123", stream_start=start)

    w1 = WindowStats(
        video_id="test_123",
        window_start=start,
        window_end=start + timedelta(seconds=10),
        message_count=4,
        unique_authors=4,
        diversity_ratio=1.0,
        author_names=["a1", "a2", "a3", "a4"],
        chat_velocity=0.4,
        z_score=3.5,
        top_keywords=["wkwkwk", "ngakak"],
        sample_messages=["wkwkwk ngakak banget", "parah kocak abis"],
        is_peak=True,
    )
    w2 = WindowStats(
        video_id="test_123",
        window_start=start + timedelta(seconds=10),
        window_end=start + timedelta(seconds=20),
        message_count=3,
        unique_authors=3,
        diversity_ratio=1.0,
        author_names=["a5", "a6", "a7"],
        chat_velocity=0.3,
        z_score=3.0,
        top_keywords=["lucu"],
        sample_messages=["wkwkwk ngakak banget", "bikin sakit perut"],
        is_peak=True,
    )

    merger.process_window(w1)
    merger.process_window(w2)
    final_peak = merger.flush(end_time=start + timedelta(seconds=20))

    assert final_peak is not None
    assert final_peak.moment_category == "Comedy / Ngakak"
    assert final_peak.sample_messages == [
        "wkwkwk ngakak banget",
        "parah kocak abis",
        "bikin sakit perut",
    ]


def test_peak_merger_prioritizes_highest_z_samples_and_keyword_frequency():
    start = datetime.now(timezone.utc)
    merger = PeakMerger(video_id="test_123", stream_start=start)

    w1 = WindowStats(
        video_id="test_123",
        window_start=start,
        window_end=start + timedelta(seconds=10),
        message_count=4,
        unique_authors=4,
        diversity_ratio=1.0,
        author_names=["a1", "a2", "a3", "a4"],
        chat_velocity=0.4,
        z_score=2.6,
        top_keywords=["awal", "gg"],
        sample_messages=["a1: awal1", "a2: awal2", "a3: awal3", "a4: awal4"],
        is_peak=True,
    )
    w2 = WindowStats(
        video_id="test_123",
        window_start=start + timedelta(seconds=10),
        window_end=start + timedelta(seconds=20),
        message_count=6,
        unique_authors=6,
        diversity_ratio=1.0,
        author_names=["b1", "b2", "b3", "b4", "b5", "b6"],
        chat_velocity=0.6,
        z_score=5.2,
        top_keywords=["clutch", "gg"],
        sample_messages=["b1: puncak1", "b2: puncak2"],
        is_peak=True,
    )

    merger.process_window(w1)
    merger.process_window(w2)
    final_peak = merger.flush(end_time=start + timedelta(seconds=20))

    assert final_peak is not None
    assert final_peak.highlight_keywords[0] == "gg"
    assert final_peak.sample_messages[:2] == ["b1: puncak1", "b2: puncak2"]
    assert len(final_peak.sample_messages) == 5


