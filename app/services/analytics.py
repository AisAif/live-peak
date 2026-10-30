import math
from collections import deque
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import ChatMessage, WindowStats
from app.utils.stats_helpers import (
    calculate_baseline_center_scale,
    calculate_ewma_z_score,
    calculate_rolling_stats,
    calculate_z_from_center_scale,
    update_cusum,
    update_ewma_mean,
    update_ewma_variance,
)
from app.utils.text_helpers import extract_keywords_and_emojis


class SlidingWindowAnalytics:
    """
    Service responsible for aggregating real-time chat messages into fixed-size,
    event-time aligned windows, computing chat velocity, baseline rolling stats,
    and detecting peak events via Z-Score algorithm.

    Windows are aligned to a fixed grid and are finalized by either incoming
    messages or an external tick() timer, so quiet periods still produce
    zero-message windows (important for an unbiased baseline).
    """

    def __init__(
        self,
        video_id: str,
        window_duration_seconds: int = settings.WINDOW_DURATION_SECONDS,
        sliding_window_size: int = settings.SLIDING_WINDOW_SIZE,
        z_score_threshold: float = settings.Z_SCORE_THRESHOLD,
        z_score_method: str = settings.Z_SCORE_METHOD,
        min_baseline_windows: int = 5,
        enable_ewma_detection: bool = settings.ENABLE_EWMA_DETECTION,
        ewma_alpha: float = settings.EWMA_ALPHA,
        ewma_z_threshold: float = settings.EWMA_Z_THRESHOLD,
        enable_cusum_detection: bool = settings.ENABLE_CUSUM_DETECTION,
        cusum_drift_sigma: float = settings.CUSUM_DRIFT_SIGMA,
        cusum_threshold_sigma: float = settings.CUSUM_THRESHOLD_SIGMA
    ):
        self.video_id = video_id
        self.window_duration = max(1, window_duration_seconds)
        self.sliding_window_size = sliding_window_size
        self.z_score_threshold = z_score_threshold
        self.min_baseline_windows = min_baseline_windows

        z_score_method = z_score_method.lower()
        if z_score_method not in {"mad", "std"}:
            raise ValueError("z_score_method must be either 'mad' or 'std'")
        self.z_score_method = z_score_method

        if not 0.0 < ewma_alpha <= 1.0:
            raise ValueError("ewma_alpha must be in the range (0, 1]")
        if ewma_z_threshold <= 0.0:
            raise ValueError("ewma_z_threshold must be positive")
        if cusum_drift_sigma < 0.0:
            raise ValueError("cusum_drift_sigma must be non-negative")
        if cusum_threshold_sigma <= 0.0:
            raise ValueError("cusum_threshold_sigma must be positive")

        self.enable_ewma_detection = enable_ewma_detection
        self.ewma_alpha = ewma_alpha
        self.ewma_z_threshold = ewma_z_threshold
        self.enable_cusum_detection = enable_cusum_detection
        self.cusum_drift_sigma = cusum_drift_sigma
        self.cusum_threshold_sigma = cusum_threshold_sigma

        # Current window buffers, aligned to a fixed event-time grid
        self.current_window_start: datetime = self._floor_to_window(datetime.now(timezone.utc))
        self.current_messages: list[ChatMessage] = []

        # Historical window stats queue (sliding window memory)
        self.history: deque[WindowStats] = deque(maxlen=self.sliding_window_size)

        # Online detector state
        self.ewma_mean: float | None = None
        self.ewma_variance: float = 0.0
        self.cusum_positive: float = 0.0

    def _floor_to_window(self, ts: datetime) -> datetime:
        """Aligns a timestamp down to the nearest window boundary."""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        epoch = ts.timestamp()
        floored = math.floor(epoch / self.window_duration) * self.window_duration
        return datetime.fromtimestamp(floored, tz=timezone.utc)

    def _event_time(self, message: ChatMessage) -> datetime:
        """Returns a timezone-aware event timestamp for a chat message."""
        ts = message.timestamp
        if ts is None:
            return datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def process_message(self, message: ChatMessage) -> list[WindowStats]:
        """
        Buffers an incoming chat message and returns any window(s) completed by it.
        A message that lands in a future window is assigned to that window instead of
        being dropped from the previous one.
        """
        event_ts = self._event_time(message)
        # Never place a message before the current window; late messages are
        # attributed to the current (open) window instead of being discarded.
        if event_ts < self.current_window_start:
            event_ts = self.current_window_start

        completed: list[WindowStats] = []
        window_end = self.current_window_start + timedelta(seconds=self.window_duration)

        while event_ts >= window_end:
            completed.append(self._build_stats(self.current_window_start, window_end))
            self.current_messages = []
            self.current_window_start = window_end
            window_end = self.current_window_start + timedelta(seconds=self.window_duration)

            # Safety valve for pathological timestamp jumps
            if len(completed) >= 100:
                logger.warning(
                    f"Detected large timestamp jump for {self.video_id}; "
                    f"resetting window boundary to {self._floor_to_window(event_ts).isoformat()}"
                )
                self.current_window_start = self._floor_to_window(event_ts)
                break

        self.current_messages.append(message)
        return completed

    def tick(self, now: datetime | None = None) -> list[WindowStats]:
        """
        Finalizes every window whose end boundary has passed, including silent
        zero-message windows. Should be called periodically by a background timer.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        completed: list[WindowStats] = []
        window_end = self.current_window_start + timedelta(seconds=self.window_duration)

        while now >= window_end:
            completed.append(self._build_stats(self.current_window_start, window_end))
            self.current_messages = []
            self.current_window_start = window_end
            window_end = self.current_window_start + timedelta(seconds=self.window_duration)

            if len(completed) >= 100:
                logger.warning(
                    f"Detected large tick gap for {self.video_id}; "
                    f"skipping to boundary {self._floor_to_window(now).isoformat()}"
                )
                self.current_window_start = self._floor_to_window(now)
                break

        return completed

    def finalize_window(
        self,
        end_time: datetime | None = None,
        use_actual_duration: bool = False
    ) -> WindowStats:
        """
        Finalizes the current aggregation window immediately.

        By default the configured window duration is used as the velocity
        denominator for backwards compatibility. Set use_actual_duration=True
        to use the real elapsed time (e.g. when flushing a partial window on stop).
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        if end_time < self.current_window_start:
            end_time = self.current_window_start + timedelta(seconds=self.window_duration)

        stats = self._build_stats(
            self.current_window_start,
            end_time,
            use_actual_duration=use_actual_duration
        )
        self.current_messages = []
        self.current_window_start = end_time
        return stats

    def _build_stats(
        self,
        start: datetime,
        end: datetime,
        use_actual_duration: bool = True
    ) -> WindowStats:
        """Builds a WindowStats object for [start, end) and updates history."""
        msg_count = len(self.current_messages)

        elapsed_seconds = max((end - start).total_seconds(), 0.0)
        if use_actual_duration:
            denominator = max(elapsed_seconds, 1e-9)
        else:
            denominator = float(self.window_duration)
        chat_velocity = msg_count / denominator if denominator > 0 else 0.0

        # Calculate baseline from history (excluding current window)
        historical_velocities = [w.chat_velocity for w in self.history]
        baseline_center, baseline_scale = calculate_baseline_center_scale(
            historical_velocities
        )
        flat_anomaly_score = self.z_score_threshold + 1.0
        if self.z_score_method == "mad":
            z_center, z_scale = baseline_center, baseline_scale
        else:
            z_center, z_scale = calculate_rolling_stats(historical_velocities)
        z_score = calculate_z_from_center_scale(
            chat_velocity, z_center, z_scale, flat_anomaly_score
        )

        # EWMA detector: compares the current value against the prior EWMA
        # baseline, then updates the online mean/variance for the next window.
        if self.ewma_mean is None:
            ewma_z_score = 0.0
        else:
            ewma_z_score = calculate_ewma_z_score(
                chat_velocity,
                self.ewma_mean,
                math.sqrt(max(self.ewma_variance, 0.0)),
                flat_anomaly_score=self.ewma_z_threshold + 1.0
            )

        ewma_velocity = update_ewma_mean(
            self.ewma_mean, chat_velocity, self.ewma_alpha
        )
        self.ewma_variance = update_ewma_variance(
            self.ewma_variance, self.ewma_mean, chat_velocity, self.ewma_alpha
        )
        self.ewma_mean = ewma_velocity

        # CUSUM detector: accumulates persistent positive deviations from the
        # robust baseline and resets after an alarm.
        cusum_score, cusum_alarm = update_cusum(
            self.cusum_positive,
            chat_velocity,
            baseline_center,
            baseline_scale,
            drift_sigma=self.cusum_drift_sigma,
            threshold_sigma=self.cusum_threshold_sigma
        )
        self.cusum_positive = 0.0 if cusum_alarm else cusum_score

        # Peak detection requires minimum baseline history size for confidence
        has_baseline = len(self.history) >= self.min_baseline_windows
        peak_sources: list[str] = []
        if has_baseline and z_score >= self.z_score_threshold:
            peak_sources.append("z")
        if has_baseline and self.enable_ewma_detection and ewma_z_score >= self.ewma_z_threshold:
            peak_sources.append("ewma")
        if has_baseline and self.enable_cusum_detection and cusum_alarm:
            peak_sources.append("cusum")

        is_peak = msg_count >= 3 and bool(peak_sources)
        peak_source = "+".join(peak_sources) if is_peak else None

        # Extract top keywords and emojis in a single pass
        raw_texts = [m.message for m in self.current_messages]
        top_kw, emoji_count = extract_keywords_and_emojis(raw_texts, top_n=5)

        stats = WindowStats(
            video_id=self.video_id,
            window_start=start,
            window_end=end,
            message_count=msg_count,
            chat_velocity=chat_velocity,
            emoji_count=emoji_count,
            top_keywords=top_kw,
            z_score=z_score,
            ewma_velocity=ewma_velocity,
            ewma_z_score=ewma_z_score,
            cusum_score=cusum_score,
            peak_source=peak_source,
            is_peak=is_peak
        )

        # Append to historical sliding queue
        self.history.append(stats)

        if is_peak:
            logger.info(
                f"[PEAK DETECTED] Video: {self.video_id} | Source: {peak_source} | "
                f"Z-Score: {z_score:.2f} | EWMA Z: {ewma_z_score:.2f} | "
                f"CUSUM: {cusum_score:.2f} | Velocity: {chat_velocity:.2f} msg/s | "
                f"Keywords: {top_kw}"
            )

        return stats
