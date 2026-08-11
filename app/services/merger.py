from datetime import datetime, timedelta
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import WindowStats, PeakEvent


class PeakMerger:
    """
    Service responsible for merging consecutive or closely-occurring Peak Windows (<= gap seconds)
    and applying pre/post video time padding (e.g. -15s before, +15s after peak).
    """

    def __init__(
        self,
        video_id: str,
        merge_gap_seconds: int = settings.PEAK_MERGE_GAP_SECONDS,
        padding_before: int = settings.PEAK_PADDING_BEFORE_SECONDS,
        padding_after: int = settings.PEAK_PADDING_AFTER_SECONDS
    ):
        self.video_id = video_id
        self.merge_gap_seconds = merge_gap_seconds
        self.padding_before = timedelta(seconds=padding_before)
        self.padding_after = timedelta(seconds=padding_after)

        self.current_active_peak: PeakEvent | None = None
        self.accumulated_keywords: list[str] = []

    def process_window(self, window: WindowStats) -> PeakEvent | None:
        """
        Processes a WindowStats object.
        If a peak is active and window is not a peak or exceeds gap, finalizes and returns the PeakEvent.
        """
        if window.is_peak:
            if self.current_active_peak is None:
                # Start new peak event
                self.current_active_peak = PeakEvent(
                    video_id=self.video_id,
                    start_time=window.window_start,
                    peak_time=window.window_end,
                    end_time=window.window_end,
                    padded_start_time=window.window_start - self.padding_before,
                    padded_end_time=window.window_end + self.padding_after,
                    max_z_score=window.z_score,
                    max_chat_velocity=window.chat_velocity,
                    total_messages=window.message_count,
                    highlight_keywords=window.top_keywords[:]
                )
                self.accumulated_keywords = list(window.top_keywords)
            else:
                # Extend existing peak event if within merge gap
                gap = (window.window_start - self.current_active_peak.end_time).total_seconds()
                if gap <= self.merge_gap_seconds:
                    self.current_active_peak.end_time = window.window_end
                    self.current_active_peak.padded_end_time = window.window_end + self.padding_after
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
                    self.current_active_peak = PeakEvent(
                        video_id=self.video_id,
                        start_time=window.window_start,
                        peak_time=window.window_end,
                        end_time=window.window_end,
                        padded_start_time=window.window_start - self.padding_before,
                        padded_end_time=window.window_end + self.padding_after,
                        max_z_score=window.z_score,
                        max_chat_velocity=window.chat_velocity,
                        total_messages=window.message_count,
                        highlight_keywords=window.top_keywords[:]
                    )
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

    def flush(self) -> PeakEvent | None:
        """Flushes and returns any currently active peak when stream ends."""
        if self.current_active_peak is not None:
            completed_peak = self.current_active_peak
            self.current_active_peak = None
            self.accumulated_keywords = []
            return completed_peak
        return None
