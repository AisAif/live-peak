from datetime import datetime, timedelta, timezone
import numpy as np
import pytest

from app.models.domain import ChatMessage, WindowStats
from app.services.analytics import SlidingWindowAnalytics
from app.services.merger import PeakMerger
from app.services.semantic import SemanticAnalyzer
from app.utils.stats_helpers import calculate_composite_highlight_score
from app.utils.text_helpers import classify_moment_category


class _FakeEmbeddingModel:
    """Deterministic orthogonal-topic embedding model for offline unit tests."""

    def embed(self, texts):
        vecs = []
        for t in texts:
            low = t.lower()
            if any(k in low for k in ("lag", "buffering", "mute", "suara hilang", "putus", "freeze")):
                vecs.append([1.0, 0.0, 0.0, 0.0])
            elif any(k in low for k in ("clutch", "gila", "clip", "hype", "comeback")):
                vecs.append([0.0, 1.0, 0.0, 0.0])
            elif any(k in low for k in ("wkwk", "ngakak", "lucu")):
                vecs.append([0.0, 0.0, 1.0, 0.0])
            else:
                vecs.append([0.0, 0.0, 0.0, 1.0])
        return np.asarray(vecs, dtype=np.float32)


def test_semantic_analyzer_detects_convergence_and_tech_issue():
    analyzer = SemanticAnalyzer(enabled=True, embedding_model=_FakeEmbeddingModel())

    hype_res = analyzer.analyze_window([
        "gila clutch banget!",
        "clip itu cepet!",
        "gila mainnya!",
    ])
    assert hype_res.convergence_score > 0.5
    assert hype_res.is_tech_issue is False

    tech_res = analyzer.analyze_window([
        "stream lag banget",
        "buffering terus min",
        "suara hilang mute ya?",
    ])
    assert tech_res.convergence_score > 0.5
    assert tech_res.is_tech_issue is True


def test_semantic_analyzer_mmr_prioritizes_diverse_samples():
    analyzer = SemanticAnalyzer(enabled=True, embedding_model=_FakeEmbeddingModel())
    samples = [
        "u1: clutch gila",
        "u2: clutch banget",
        "u3: wkwkwk ngakak",
        "u4: stream lag",
    ]

    ranked = analyzer.select_diverse_samples_mmr(samples, limit=3, lambda_mult=0.5)

    assert len(ranked) == 3
    # Should pick the dominant topic first, then include distinct topics instead of duplicates
    assert ranked[0].startswith("u1:")
    assert "u3: wkwkwk ngakak" in ranked


def test_tech_issue_classification_and_highlight_score_penalty():
    assert classify_moment_category(["lag", "buffering"]) == "Technical Issue"

    normal_score = calculate_composite_highlight_score(
        max_z_score=4.0,
        total_messages=30,
        unique_authors=20,
        emoji_count=5,
        duration_seconds=20.0,
        semantic_convergence=0.8,
        is_tech_issue=False,
    )
    tech_score = calculate_composite_highlight_score(
        max_z_score=4.0,
        total_messages=30,
        unique_authors=20,
        emoji_count=5,
        duration_seconds=20.0,
        semantic_convergence=0.8,
        is_tech_issue=True,
    )
    assert tech_score < normal_score
    assert tech_score == pytest.approx(normal_score * 0.5, abs=0.02)


def test_analytics_integrates_river_detector_and_semantic_analyzer():
    class _FakeRiverDetector:
        def __init__(self):
            self.calls = 0

        def score_one(self, features):
            self.calls += 1
            return 0.9 if features["velocity"] > 0.4 else 0.1

        def learn_one(self, features):
            pass

    analyzer = SemanticAnalyzer(enabled=True, embedding_model=_FakeEmbeddingModel())
    analytics = SlidingWindowAnalytics(
        video_id="vid_ml",
        window_duration_seconds=10,
        sliding_window_size=10,
        z_score_threshold=100.0,  # Disable Z-score trigger so River alone triggers
        enable_ewma_detection=False,
        enable_cusum_detection=False,
        enable_river_detection=True,
        river_threshold=0.75,
        river_detector=_FakeRiverDetector(),
        semantic_analyzer=analyzer,
    )

    t0 = analytics.current_window_start
    # Build 6 baseline windows (1 msg each)
    for i in range(6):
        analytics.process_message(ChatMessage(
            video_id="vid_ml",
            author_name=f"base_{i}",
            message="halo",
            timestamp=t0 + timedelta(seconds=i * 10 + 1),
        ))

    # Send 6 messages in window 6 -> River triggers
    burst_ts = t0 + timedelta(seconds=60)
    for i in range(6):
        analytics.process_message(ChatMessage(
            video_id="vid_ml",
            author_name=f"hype_{i}",
            message="gila clutch!",
            timestamp=burst_ts + timedelta(seconds=i),
        ))
    completed = analytics.process_message(ChatMessage(
        video_id="vid_ml",
        author_name="next",
        message="ok",
        timestamp=burst_ts + timedelta(seconds=11),
    ))

    river_peaks = [w for w in completed if w.is_peak]
    assert len(river_peaks) == 1
    assert "river" in (river_peaks[0].peak_source or "")
    assert river_peaks[0].river_score == 0.9
    assert river_peaks[0].semantic_convergence > 0.5


def test_semantic_zero_shot_classify_moment_and_merger_fallback():
    analyzer = SemanticAnalyzer(enabled=True, embedding_model=_FakeEmbeddingModel())

    assert analyzer.classify_moment(["u1: ngakak parah", "u2: lucu banget"]) == "Comedy / Ngakak"
    assert analyzer.classify_moment(["u1: suara hilang min"]) == "Technical Issue"

    # "clip" is not in regex _HYPE_WORD_RE, so regex returns "General Spike" and semantic classifies it
    merger = PeakMerger(video_id="vid_sem", semantic_analyzer=analyzer)
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    win = WindowStats(
        video_id="vid_sem",
        window_start=t0,
        window_end=t0 + timedelta(seconds=10),
        message_count=20,
        unique_authors=15,
        chat_velocity=2.0,
        z_score=4.5,
        is_peak=True,
        peak_source="z",
        top_keywords=["clip"],
        sample_messages=["u1: clip itu cepet!"],
    )
    merger.process_window(win)
    finalized = merger.flush()
    assert finalized is not None
    assert finalized.moment_category == "Hype / Clutch"
