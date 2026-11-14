from datetime import datetime, timezone
import numpy as np

from app.core.logger import logger
from app.models.domain import (
    RegimeShiftPoint,
    RetrospectiveAuditResponse,
    ShapeDiscordWindow,
)
from app.utils.stats_helpers import format_seconds_to_timestamp

try:
    import ruptures as rpt
except ImportError:  # pragma: no cover - optional fallback in minimal envs
    rpt = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def detect_regime_shifts(
    velocities: list[float],
    pen: float = 5.0,
    min_size: int = 6,
) -> list[int]:
    """
    Detects structural regime-shift indices (e.g. Just Chatting -> Match)
    using Ruptures PELT when available, with a lightweight variance fallback.
    """
    n = len(velocities)
    if n < min_size * 2:
        return []

    signal = np.asarray(velocities, dtype=np.float64)
    std = float(np.std(signal))
    if std <= 1e-6:
        return []

    if rpt is not None:
        try:
            # Standardize so `pen` behaves consistently across low/high-viewer streams
            norm_signal = (signal - float(np.mean(signal))) / std
            bkps = rpt.Pelt(model="rbf", min_size=min_size).fit(norm_signal).predict(pen=pen)
            return [int(idx) for idx in bkps if 0 < idx < n]
        except Exception as e:
            logger.warning(f"Ruptures PELT failed ({e}); using fallback change-point detector.")

    # Lightweight fallback: sliding two-window mean-shift z-test
    shifts: list[int] = []
    last_shift = -min_size
    for i in range(min_size, n - min_size + 1):
        if i - last_shift < min_size:
            continue
        left = signal[i - min_size : i]
        right = signal[i : i + min_size]
        pooled_std = float(np.sqrt(0.5 * (np.var(left) + np.var(right)))) + 1e-6
        if abs(float(np.mean(right)) - float(np.mean(left))) / pooled_std >= 2.5:
            shifts.append(i)
            last_shift = i
    return shifts


def find_shape_discords(
    velocities: list[float],
    subsequence_len: int = 6,
    top_k: int = 3,
) -> list[tuple[int, float]]:
    """
    Finds the top-K non-overlapping shape discords (most unusual chat waveforms)
    using a vectorized NumPy z-normalized Euclidean Matrix Profile.
    """
    n = len(velocities)
    m = max(3, subsequence_len)
    if n < m * 3:
        return []

    ts = np.asarray(velocities, dtype=np.float64)
    if float(np.std(ts)) <= 1e-6:
        return []

    # Vectorized NumPy z-normalized Euclidean matrix profile (O(N) memory)
    num_subs = n - m + 1
    subs = np.lib.stride_tricks.sliding_window_view(ts, m)
    means = subs.mean(axis=1, keepdims=True)
    raw_stds = subs.std(axis=1, keepdims=True)
    stds = np.where(raw_stds < 1e-6, 1.0, raw_stds)
    norm_subs = (subs - means) / stds
    distances = np.full(num_subs, np.inf, dtype=np.float64)
    excl = max(1, m // 2)
    for i in range(num_subs):
        diffs = norm_subs - norm_subs[i]
        dists = np.sqrt(np.sum(diffs * diffs, axis=1))
        lo = max(0, i - excl)
        hi = min(num_subs, i + excl + 1)
        dists[lo:hi] = np.inf
        distances[i] = float(np.min(dists))

    # Greedily pick top_k non-overlapping finite discords
    selected: list[tuple[int, float]] = []
    masked = distances.copy()
    masked[~np.isfinite(masked)] = -1.0
    for _ in range(top_k):
        best_idx = int(np.argmax(masked))
        best_dist = float(masked[best_idx])
        if best_dist <= 0.0:
            break
        selected.append((best_idx, round(best_dist, 4)))
        lo = max(0, best_idx - m + 1)
        hi = min(len(masked), best_idx + m)
        masked[lo:hi] = -1.0
    return selected


def run_retrospective_audit(
    video_id: str,
    window_rows: list,
    peak_rows: list,
    stream_start: datetime | None = None,
) -> RetrospectiveAuditResponse:
    """Computes PELT regime shifts and Matrix Profile discords for a stream's windows."""
    if not window_rows:
        return RetrospectiveAuditResponse(
            video_id=video_id,
            total_windows=0,
            ruptures_active=rpt is not None,
            stumpy_active=False,
        )

    origin = _as_utc(stream_start or window_rows[0].window_start)
    velocities = [float(w.chat_velocity) for w in window_rows]

    shift_indices = detect_regime_shifts(velocities)
    regime_shifts: list[RegimeShiftPoint] = []
    for idx in shift_indices:
        w = window_rows[idx]
        ts = _as_utc(w.window_start)
        offset = max(0.0, (ts - origin).total_seconds())
        regime_shifts.append(
            RegimeShiftPoint(
                window_index=idx,
                timestamp=ts,
                offset_seconds=round(offset, 2),
                time_label=format_seconds_to_timestamp(offset),
            )
        )

    discord_hits = find_shape_discords(velocities)
    shape_discords: list[ShapeDiscordWindow] = []
    m = 6
    for start_idx, dist in discord_hits:
        end_idx = min(len(window_rows) - 1, start_idx + m - 1)
        w_start = _as_utc(window_rows[start_idx].window_start)
        w_end = _as_utc(window_rows[end_idx].window_end)
        s_off = max(0.0, (w_start - origin).total_seconds())
        e_off = max(s_off, (w_end - origin).total_seconds())

        matched_peak_id = None
        for p in peak_rows:
            p_start = _as_utc(p.start_time)
            p_end = _as_utc(p.end_time)
            if p_start <= w_end and p_end >= w_start:
                matched_peak_id = p.id
                break

        shape_discords.append(
            ShapeDiscordWindow(
                start_index=start_idx,
                end_index=end_idx,
                start_offset_seconds=round(s_off, 2),
                end_offset_seconds=round(e_off, 2),
                time_label=f"{format_seconds_to_timestamp(s_off)} - {format_seconds_to_timestamp(e_off)}",
                discord_distance=dist,
                matched_peak_id=matched_peak_id,
            )
        )

    return RetrospectiveAuditResponse(
        video_id=video_id,
        total_windows=len(window_rows),
        ruptures_active=rpt is not None,
        stumpy_active=False,
        regime_shifts=regime_shifts,
        shape_discords=shape_discords,
    )
