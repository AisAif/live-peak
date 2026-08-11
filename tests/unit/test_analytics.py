from datetime import datetime, timezone
from app.services.analytics import SlidingWindowAnalytics
from app.services.merger import PeakMerger
from app.models.domain import ChatMessage


def test_analytics_and_peak_merging():
    analytics = SlidingWindowAnalytics(video_id="test_123", window_duration_seconds=10, z_score_threshold=2.0)
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
