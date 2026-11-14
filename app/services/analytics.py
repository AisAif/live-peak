import math
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import ChatMessage, WindowStats
from app.utils.stats_helpers import (
    calculate_baseline_center_scale,
    calculate_diversity_ratio,
    calculate_ewma_z_score,
    calculate_rolling_stats,
    calculate_z_from_center_scale,
    update_cusum,
    update_ewma_mean,
    update_ewma_variance,
)
from app.utils.text_helpers import (
    extract_contrastive_keywords,
    select_sample_messages,
    tokenize_keywords_and_emojis,
)


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
        min_unique_authors: int = settings.MIN_UNIQUE_AUTHORS_FOR_PEAK,
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
        self.min_unique_authors = max(1, min_unique_authors)

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
        # Winsorized velocity baseline (prevents extreme peaks from polluting future baselines)
        self.baseline_velocities: deque[float] = deque(maxlen=self.sliding_window_size)
        # Rolling background word frequencies from non-peak windows for contrastive keyword extraction
        self.background_term_history: deque[Counter[str]] = deque(maxlen=self.sliding_window_size)
        self.background_term_counts: Counter[str] = Counter()

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

        # Calculate baseline from winsorized history (excluding current window)
        historical_velocities = list(self.baseline_velocities)
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

        # EWMA detector: compares the current value against the prior EWMA baseline
        if self.ewma_mean is None:
            ewma_z_score = 0.0
        else:
            ewma_z_score = calculate_ewma_z_score(
                chat_velocity,
                self.ewma_mean,
                math.sqrt(max(self.ewma_variance, 0.0)),
                flat_anomaly_score=self.ewma_z_threshold + 1.0
            )

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

        # Extract contrastive keywords, emojis, unique authors, and SuperChats in a single pass
        raw_texts = [m.message for m in self.current_messages]
        fg_counts, emoji_count = tokenize_keywords_and_emojis(raw_texts)
        top_kw = extract_contrastive_keywords(fg_counts, self.background_term_counts, top_n=5)
        unique_author_set = {m.author_name for m in self.current_messages if m.author_name}
        unique_authors = len(unique_author_set)
        diversity_ratio = calculate_diversity_ratio(unique_authors, msg_count)
        superchat_count = sum(1 for m in self.current_messages if m.amount_str)

        # Peak detection requires minimum baseline history and unique authors (anti-spam gate)
        has_baseline = len(self.history) >= self.min_baseline_windows
        peak_sources: list[str] = []
        if has_baseline and z_score >= self.z_score_threshold:
            peak_sources.append("z")
        if has_baseline and self.enable_ewma_detection and ewma_z_score >= self.ewma_z_threshold:
            peak_sources.append("ewma")
        if has_baseline and self.enable_cusum_detection and cusum_alarm:
            peak_sources.append("cusum")

        is_peak = (
            msg_count >= 3
            and unique_authors >= self.min_unique_authors
            and bool(peak_sources)
        )
        peak_source = "+".join(peak_sources) if is_peak else None

        sample_msgs = (
            select_sample_messages(
                [(m.author_name, m.message, bool(m.amount_str)) for m in self.current_messages],
                top_kw,
                limit=5,
            )
            if is_peak or (has_baseline and z_score >= settings.PEAK_HYSTERESIS_LOW_Z)
            else []
        )
        if not is_peak and fg_counts:
            if (
                self.background_term_history.maxlen is not None
                and len(self.background_term_history) == self.background_term_history.maxlen
            ):
                oldest_counts = self.background_term_history.popleft()
                self.background_term_counts.subtract(oldest_counts)
                self.background_term_counts += Counter()
            self.background_term_history.append(fg_counts)
            self.background_term_counts.update(fg_counts)

        # Winsorize peak spikes before updating rolling/EWMA baselines to prevent self-pollution
        if is_peak and has_baseline:
            if z_scale > 0.0:
                capped_velocity = min(chat_velocity, z_center + (self.z_score_threshold * z_scale))
            else:
                capped_velocity = min(chat_velocity, z_center)
        else:
            capped_velocity = chat_velocity

        ewma_velocity = update_ewma_mean(
            self.ewma_mean, capped_velocity, self.ewma_alpha
        )
        self.ewma_variance = update_ewma_variance(
            self.ewma_variance, self.ewma_mean, capped_velocity, self.ewma_alpha
        )
        self.ewma_mean = ewma_velocity
        self.baseline_velocities.append(capped_velocity)

        stats = WindowStats(
            video_id=self.video_id,
            window_start=start,
            window_end=end,
            message_count=msg_count,
            unique_authors=unique_authors,
            diversity_ratio=diversity_ratio,
            superchat_count=superchat_count,
            author_names=sorted(unique_author_set),
            sample_messages=sample_msgs,
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
