from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import WindowStats, PeakEvent
from app.utils.stats_helpers import format_seconds_to_timestamp


class PeakMerger:
    """
    Service responsible for merging consecutive or closely-occurring Peak Windows (<= gap seconds)
    and applying pre/post video time padding (e.g. -15s before, +15s after peak).

    Padded boundaries are clamped to the known stream lifetime so clip offsets never
    point outside the actual broadcast.
    """

    def __init__(
        self,
        video_id: str,
        merge_gap_seconds: int = settings.PEAK_MERGE_GAP_SECONDS,
        padding_before: int = settings.PEAK_PADDING_BEFORE_SECONDS,
        padding_after: int = settings.PEAK_PADDING_AFTER_SECONDS,
        stream_start: datetime | None = None,
        stream_end: datetime | None = None
    ):
        self.video_id = video_id
        self.merge_gap_seconds = merge_gap_seconds
        self.padding_before = timedelta(seconds=padding_before)
        self.padding_after = timedelta(seconds=padding_after)
        self.stream_start = stream_start
        self.stream_end = stream_end

        self.current_active_peak: PeakEvent | None = None
        self.accumulated_keywords: list[str] = []

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

    def _new_peak(self, window: WindowStats) -> PeakEvent:
        padded_start = self._clamp_time(window.window_start - self.padding_before)
        padded_end = self._clamp_time(window.window_end + self.padding_after)
        video_start, video_end, start_sec, end_sec = self._calculate_video_offsets(
            padded_start, padded_end
        )
        return PeakEvent(
            video_id=self.video_id,
            start_time=window.window_start,
            peak_time=window.window_end,
            end_time=window.window_end,
            padded_start_time=padded_start,
            padded_end_time=padded_end,
            video_start_time=video_start,
            video_end_time=video_end,
            start_offset_seconds=start_sec,
            end_offset_seconds=end_sec,
            max_z_score=window.z_score,
            max_chat_velocity=window.chat_velocity,
            total_messages=window.message_count,
            highlight_keywords=window.top_keywords[:]
        )

    def process_window(self, window: WindowStats) -> PeakEvent | None:
        """
        Processes a WindowStats object.
        If a peak is active and window is not a peak or exceeds gap, finalizes and returns the PeakEvent.
        """
        if window.is_peak:
            if self.current_active_peak is None:
                # Start new peak event
                self.current_active_peak = self._new_peak(window)
                self.accumulated_keywords = list(window.top_keywords)
            else:
                # Extend existing peak event if within merge gap
                gap = (window.window_start - self.current_active_peak.end_time).total_seconds()
                if gap <= self.merge_gap_seconds:
                    self.current_active_peak.end_time = window.window_end
                    self.current_active_peak.padded_end_time = self._clamp_time(
                        window.window_end + self.padding_after
                    )
                    v_start, v_end, s_sec, e_sec = self._calculate_video_offsets(
                        self.current_active_peak.padded_start_time,
                        self.current_active_peak.padded_end_time,
                    )
                    self.current_active_peak.video_start_time = v_start
                    self.current_active_peak.video_end_time = v_end
                    self.current_active_peak.start_offset_seconds = s_sec
                    self.current_active_peak.end_offset_seconds = e_sec
                    self.current_active_peak.total_messages += window.message_count

                    if window.z_score > self.current_active_peak.max_z_score:
                        self.current_active_peak.max_z_score = window.z_score
                        self.current_active_peak.peak_time = window.window_end

                    if window.chat_velocity > self.current_active_peak.max_chat_velocity:
                        self.current_active_peak.max_chat_velocity = window.chat_velocity

                    # Merge keywords without duplicates
                    for kw in window.top_keywords:
                        if kw not in self.accumulated_keywords:
                            self.accumulated_keywords.append(kw)
                    self.current_active_peak.highlight_keywords = self.accumulated_keywords[:7]
                else:
                    # Gap too large, finalize previous peak and start new one
                    completed_peak = self.current_active_peak
                    self.current_active_peak = self._new_peak(window)
                    self.accumulated_keywords = list(window.top_keywords)
                    return completed_peak

        else:
            # Window is NOT a peak. Check if an active peak has ended past the merge gap
            if self.current_active_peak is not None:
                gap = (window.window_start - self.current_active_peak.end_time).total_seconds()
                if gap > self.merge_gap_seconds:
                    completed_peak = self.current_active_peak
                    self.current_active_peak = None
                    self.accumulated_keywords = []
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
            v_start, v_end, s_sec, e_sec = self._calculate_video_offsets(
                completed_peak.padded_start_time,
                completed_peak.padded_end_time,
            )
            completed_peak.video_start_time = v_start
            completed_peak.video_end_time = v_end
            completed_peak.start_offset_seconds = s_sec
            completed_peak.end_offset_seconds = e_sec
            self.current_active_peak = None
            self.accumulated_keywords = []
            return completed_peak
        return None
