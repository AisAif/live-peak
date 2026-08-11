from collections import deque
from datetime import datetime, timezone
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import ChatMessage, WindowStats
from app.utils.stats_helpers import calculate_z_score, calculate_rolling_stats
from app.utils.text_helpers import extract_top_keywords, extract_emojis


class SlidingWindowAnalytics:
    """
    Service responsible for aggregating real-time chat messages into 10-second windows,
    computing chat velocity, baseline rolling stats, and detecting peak events via Z-Score algorithm.
    """

    def __init__(
        self,
        video_id: str,
        window_duration_seconds: int = settings.WINDOW_DURATION_SECONDS,
        sliding_window_size: int = settings.SLIDING_WINDOW_SIZE,
        z_score_threshold: float = settings.Z_SCORE_THRESHOLD,
        min_baseline_windows: int = 5
    ):
        self.video_id = video_id
        self.window_duration = window_duration_seconds
        self.sliding_window_size = sliding_window_size
        self.z_score_threshold = z_score_threshold
        self.min_baseline_windows = min_baseline_windows

        # Current window buffers
        self.current_window_start: datetime = datetime.now(timezone.utc)
        self.current_messages: list[ChatMessage] = []

        # Historical window stats queue (sliding window memory)
        self.history: deque[WindowStats] = deque(maxlen=self.sliding_window_size)

    def process_message(self, message: ChatMessage) -> WindowStats | None:
        """
        Buffer incoming chat message. Returns WindowStats if a 10-second window completes,
        otherwise returns None.
        """
        now = datetime.now(timezone.utc)
        elapsed = (now - self.current_window_start).total_seconds()

        # If current window duration has elapsed, finalize the window
        if elapsed >= self.window_duration:
            stats = self.finalize_window(now)
            # Start new window with the new message
            self.current_messages = [message]
            self.current_window_start = now
            return stats
        else:
            self.current_messages.append(message)
            return None

    def finalize_window(self, end_time: datetime | None = None) -> WindowStats:
        """Finalizes current aggregation window and computes Z-Score peak detection."""
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        msg_count = len(self.current_messages)
        chat_velocity = msg_count / self.window_duration if self.window_duration > 0 else 0.0

        # Calculate baseline mean & std_dev from history
        historical_velocities = [w.chat_velocity for w in self.history]
        baseline_mean, baseline_std = calculate_rolling_stats(historical_velocities)

        # Calculate Z-score
        z_score = calculate_z_score(chat_velocity, baseline_mean, baseline_std)
        
        # Peak detection requires minimum baseline history size for statistical confidence
        is_peak = (
            len(self.history) >= self.min_baseline_windows and
            z_score >= self.z_score_threshold and
            msg_count >= 3
        )

        # Extract top keywords and emojis
        raw_texts = [m.message for m in self.current_messages]
        top_kw = extract_top_keywords(raw_texts, top_n=5)
        
        emoji_count = sum(len(extract_emojis(m.message)) for m in self.current_messages)

        stats = WindowStats(
            video_id=self.video_id,
            window_start=self.current_window_start,
            window_end=end_time,
            message_count=msg_count,
            chat_velocity=chat_velocity,
            emoji_count=emoji_count,
            top_keywords=top_kw,
            z_score=z_score,
            is_peak=is_peak
        )

        # Append to historical sliding queue
        self.history.append(stats)

        if is_peak:
            logger.info(
                f"[PEAK DETECTED] Video: {self.video_id} | Z-Score: {z_score:.2f} | "
                f"Velocity: {chat_velocity:.2f} msg/s | Keywords: {top_kw}"
            )

        return stats
