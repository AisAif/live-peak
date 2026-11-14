from collections import Counter
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import WindowStats, PeakEvent
from app.utils.stats_helpers import (
    calculate_composite_highlight_score,
    calculate_diversity_ratio,
    format_seconds_to_timestamp,
)
from app.utils.text_helpers import classify_moment_category


class PeakMerger:
    """
    Service responsible for merging consecutive or closely-occurring Peak Windows (<= gap seconds),
    applying dual-threshold hysteresis to prevent peak flickering, computing composite highlight
    scores, and applying pre/post video time padding (e.g. -15s before, +15s after peak).

    Padded boundaries are clamped to the known stream lifetime so clip offsets never
    point outside the actual broadcast.
    """

    def __init__(
        self,
        video_id: str,
        merge_gap_seconds: int = settings.PEAK_MERGE_GAP_SECONDS,
        hysteresis_low_z: float = settings.PEAK_HYSTERESIS_LOW_Z,
        padding_before: int = settings.PEAK_PADDING_BEFORE_SECONDS,
        padding_after: int = settings.PEAK_PADDING_AFTER_SECONDS,
        stream_start: datetime | None = None,
        stream_end: datetime | None = None
    ):
        self.video_id = video_id
        self.merge_gap_seconds = merge_gap_seconds
        self.hysteresis_low_z = hysteresis_low_z
        self.padding_before = timedelta(seconds=padding_before)
        self.padding_after = timedelta(seconds=padding_after)
        self.stream_start = stream_start
        self.stream_end = stream_end

        self.current_active_peak: PeakEvent | None = None
        self.accumulated_keywords: list[str] = []
        self.keyword_counts: Counter[str] = Counter()
        self.accumulated_sources: list[str] = []
        self.accumulated_samples: list[str] = []
        self.accumulated_authors: set[str] = set()
        self.accumulated_z_score: float = 0.0

    def _clamp_time(self, value: datetime) -> datetime:
        """Clamps a timestamp to the known stream start/end boundaries."""
        if self.stream_start is not None and value < self.stream_start:
            return self.stream_start
        if self.stream_end is not None and value > self.stream_end:
            return self.stream_end
        return value

    def _calculate_video_offsets(
        self, start: datetime, end: datetime
    ) -> tuple[str | None, str | None, float | None, float | None]:
        """Calculates video timestamp strings and second offsets relative to stream start."""
        if self.stream_start is None:
            return None, None, None, None
        start_sec = max(0.0, (start - self.stream_start).total_seconds())
        end_sec = max(start_sec, (end - self.stream_start).total_seconds())
        return (
            format_seconds_to_timestamp(start_sec),
            format_seconds_to_timestamp(end_sec),
            round(start_sec, 2),
            round(end_sec, 2),
        )

    def _recompute_derived_metrics(self, peak: PeakEvent) -> None:
        """Recomputes video clip offsets, diversity ratio, and composite highlight score."""
        v_start, v_end, s_sec, e_sec = self._calculate_video_offsets(
            peak.padded_start_time,
            peak.padded_end_time,
        )
        peak.video_start_time = v_start
        peak.video_end_time = v_end
        peak.start_offset_seconds = s_sec
        peak.end_offset_seconds = e_sec

        peak.diversity_ratio = calculate_diversity_ratio(
            peak.unique_authors, peak.total_messages
        )
        duration_sec = max(0.0, (peak.end_time - peak.start_time).total_seconds())
        peak.highlight_score = calculate_composite_highlight_score(
            max_z_score=peak.max_z_score,
            total_messages=peak.total_messages,
            unique_authors=peak.unique_authors,
            emoji_count=peak.emoji_count,
            duration_seconds=duration_sec,
            superchat_count=peak.superchat_count,
            cumulative_z_score=self.accumulated_z_score,
        )
        peak.moment_category = classify_moment_category(
            peak.highlight_keywords,
            peak.sample_messages,
            peak.superchat_count,
        )

    @staticmethod
    def _parse_sources(peak_source: str | None) -> list[str]:
        if not peak_source:
            return []
        return [s for s in peak_source.split("+") if s]

    def _is_hysteresis_active(self, window: WindowStats) -> bool:
        """
        Dual-threshold hysteresis check: keeps an active peak open while
        Z-score or EWMA Z-score stays above the lower hysteresis bound.
        """
        return window.message_count >= 2 and (
            window.z_score >= self.hysteresis_low_z
            or window.ewma_z_score >= self.hysteresis_low_z
        )

    def _new_peak(self, window: WindowStats) -> PeakEvent:
        padded_start = self._clamp_time(window.window_start - self.padding_before)
        padded_end = self._clamp_time(window.window_end + self.padding_after)
        self.accumulated_keywords = list(window.top_keywords)
        self.keyword_counts = Counter(window.top_keywords)
        self.accumulated_sources = self._parse_sources(window.peak_source)
        self.accumulated_samples = list(window.sample_messages[:5])
        self.accumulated_authors = set(window.author_names)
        self.accumulated_z_score = max(0.0, window.z_score)
        unique_authors = len(self.accumulated_authors) if self.accumulated_authors else window.unique_authors
        peak = PeakEvent(
            video_id=self.video_id,
            start_time=window.window_start,
            peak_time=window.window_end,
            end_time=window.window_end,
            padded_start_time=padded_start,
            padded_end_time=padded_end,
            max_z_score=window.z_score,
            max_chat_velocity=window.chat_velocity,
            total_messages=window.message_count,
            unique_authors=unique_authors,
            emoji_count=window.emoji_count,
            superchat_count=window.superchat_count,
            peak_sources=self.accumulated_sources[:],
            highlight_keywords=window.top_keywords[:],
            sample_messages=self.accumulated_samples[:],
        )
        self._recompute_derived_metrics(peak)
        return peak

    def _extend_peak(self, window: WindowStats) -> None:
        """Extends the currently active peak with an adjacent or hysteresis-active window."""
        peak = self.current_active_peak
        assert peak is not None

        peak.end_time = window.window_end
        peak.padded_end_time = self._clamp_time(window.window_end + self.padding_after)
        peak.total_messages += window.message_count
        if window.author_names:
            self.accumulated_authors.update(window.author_names)
            peak.unique_authors = len(self.accumulated_authors)
        else:
            peak.unique_authors += window.unique_authors
        self.accumulated_z_score += max(0.0, window.z_score)
        peak.emoji_count += window.emoji_count
        peak.superchat_count += window.superchat_count

        is_new_best_z = window.z_score > peak.max_z_score
        if is_new_best_z:
            peak.max_z_score = window.z_score
            peak.peak_time = window.window_end

        if window.chat_velocity > peak.max_chat_velocity:
            peak.max_chat_velocity = window.chat_velocity

        self.keyword_counts.update(window.top_keywords)
        self.accumulated_keywords = [kw for kw, _ in self.keyword_counts.most_common(7)]
        peak.highlight_keywords = self.accumulated_keywords[:]

        for src in self._parse_sources(window.peak_source):
            if src not in self.accumulated_sources:
                self.accumulated_sources.append(src)
        peak.peak_sources = self.accumulated_sources[:]

        if is_new_best_z and window.sample_messages:
            merged_samples: list[str] = []
            for msg in list(window.sample_messages) + self.accumulated_samples:
                if len(merged_samples) >= 5:
                    break
                if msg not in merged_samples:
                    merged_samples.append(msg)
            self.accumulated_samples = merged_samples
        else:
            for msg in window.sample_messages:
                if len(self.accumulated_samples) >= 5:
                    break
                if msg not in self.accumulated_samples:
                    self.accumulated_samples.append(msg)
        peak.sample_messages = self.accumulated_samples[:]

        self._recompute_derived_metrics(peak)

    def process_window(self, window: WindowStats) -> PeakEvent | None:
        """
        Processes a WindowStats object.
        If a peak is active and window is not a peak (nor hysteresis-active) and exceeds gap,
        finalizes and returns the PeakEvent.
        """
        if window.is_peak:
            if self.current_active_peak is None:
                self.current_active_peak = self._new_peak(window)
            else:
                gap = (window.window_start - self.current_active_peak.end_time).total_seconds()
                if gap <= self.merge_gap_seconds:
                    self._extend_peak(window)
                else:
                    completed_peak = self.current_active_peak
                    self.current_active_peak = self._new_peak(window)
                    return completed_peak
        elif self.current_active_peak is not None:
            gap = (window.window_start - self.current_active_peak.end_time).total_seconds()
            if gap <= self.merge_gap_seconds and self._is_hysteresis_active(window):
                self._extend_peak(window)
            elif gap > self.merge_gap_seconds:
                completed_peak = self.current_active_peak
                self.current_active_peak = None
                self.accumulated_keywords = []
                self.keyword_counts.clear()
                self.accumulated_sources = []
                self.accumulated_samples = []
                self.accumulated_authors = set()
                self.accumulated_z_score = 0.0
                return completed_peak

        return None

    def flush(self, end_time: datetime | None = None) -> PeakEvent | None:
        """
        Flushes and returns any currently active peak when stream ends.
        If end_time is provided, it also becomes the upper clamp for padded clip bounds.
        """
        if end_time is not None:
            self.stream_end = end_time
        else:
            self.stream_end = datetime.now(timezone.utc)

        if self.current_active_peak is not None:
            completed_peak = self.current_active_peak
            completed_peak.padded_start_time = self._clamp_time(completed_peak.padded_start_time)
            completed_peak.padded_end_time = self._clamp_time(completed_peak.padded_end_time)
            self._recompute_derived_metrics(completed_peak)
            self.current_active_peak = None
            self.accumulated_keywords = []
            self.keyword_counts.clear()
            self.accumulated_sources = []
            self.accumulated_samples = []
            self.accumulated_authors = set()
            self.accumulated_z_score = 0.0
            return completed_peak
        return None
