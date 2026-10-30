"""
Pure statistical helper functions for Z-Score calculation and sliding window baseline math.
"""
import numpy as np

# Scale factor that makes the MAD a consistent estimator of the standard
# deviation for normally distributed data.
MAD_TO_STD_SCALE = 1.4826


def calculate_z_score(current_val: float, baseline_mean: float, baseline_std: float) -> float:
    """
    Calculates the Z-score for a given value relative to baseline mean and standard deviation.
    
    Z = (x - mean) / std
    Returns 0.0 if standard deviation is 0 (to avoid division by zero).
    """
    if baseline_std <= 0.0:
        return 0.0
    return float((current_val - baseline_mean) / baseline_std)


def format_seconds_to_timestamp(seconds: float | int) -> str:
    """
    Formats seconds offset into 'HH:MM:SS' or 'MM:SS' timestamp string.
    
    Examples:
        75 -> "01:15"
        3665 -> "01:01:05"
    """
    total_seconds = int(max(0, round(seconds)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"



def calculate_rolling_stats(values: list[float]) -> tuple[float, float]:
    """
    Calculates the mean and standard deviation of a list of float values.
    
    Returns:
        tuple[mean, std_dev]
    """
    if not values:
        return 0.0, 0.0
    arr = np.array(values, dtype=np.float64)
    mean = float(np.mean(arr))
    std = float(np.std(arr))
    return mean, std


def calculate_robust_stats(values: list[float]) -> tuple[float, float]:
    """
    Calculates median and Median Absolute Deviation (MAD) of a list of values.

    MAD is far less sensitive to a few extreme windows than mean/std, which
    makes peak detection more stable on naturally bursty chat traffic.

    Returns:
        tuple[median, mad]
    """
    if not values:
        return 0.0, 0.0
    arr = np.array(values, dtype=np.float64)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    return median, mad


def calculate_z_from_center_scale(
    current_val: float,
    center: float,
    scale: float,
    flat_anomaly_score: float = 3.0
) -> float:
    """Calculates a Z-score directly from a precomputed baseline center/scale."""
    if scale > 0.0:
        return float((current_val - center) / scale)
    return 0.0 if current_val <= center else flat_anomaly_score


def calculate_robust_z_score(
    current_val: float,
    baseline_median: float,
    baseline_mad: float
) -> float:
    """
    Calculates a robust Z-score using median and MAD.

    The MAD is scaled by 1.4826 so the result is comparable to a standard
    Z-score for normally distributed baselines. Returns 0.0 when the baseline
    MAD is 0 (callers should fall back to another estimator in that case).
    """
    if baseline_mad <= 0.0:
        return 0.0
    return float(
        (current_val - baseline_median) / (MAD_TO_STD_SCALE * baseline_mad)
    )


def calculate_window_z_score(
    current_val: float,
    baseline_values: list[float],
    method: str = "mad",
    flat_anomaly_score: float = 3.0
) -> float:
    """
    Calculates a window Z-score from historical baseline values.

    Methods:
        - "mad": median/MAD, falling back to mean/std when MAD is 0.
        - "std": mean/standard deviation.

    When the chosen baseline is completely flat, any increase is treated as an
    anomaly and ``flat_anomaly_score`` is returned.
    """
    method = method.lower()
    if method not in {"mad", "std"}:
        raise ValueError("method must be either 'mad' or 'std'")

    if method == "mad":
        center, scale = calculate_robust_stats(baseline_values)
        if scale > 0.0:
            return calculate_robust_z_score(current_val, center, scale)

        # MAD is 0 (e.g. mostly identical windows): fall back to mean/std.
        mean, std = calculate_rolling_stats(baseline_values)
        if std > 0.0:
            return calculate_z_score(current_val, mean, std)
        return 0.0 if current_val <= center else flat_anomaly_score

    mean, std = calculate_rolling_stats(baseline_values)
    if std > 0.0:
        return calculate_z_score(current_val, mean, std)
    return 0.0 if current_val <= mean else flat_anomaly_score


def calculate_baseline_center_scale(baseline_values: list[float]) -> tuple[float, float]:
    """
    Returns a robust (center, scale) pair for baseline values.

    Preference order is median/MAD (scaled to standard-deviation units), then
    mean/std, then a flat (0.0, 0.0) baseline.
    """
    center, mad = calculate_robust_stats(baseline_values)
    scale = mad * MAD_TO_STD_SCALE
    if scale > 0.0:
        return center, scale
    return calculate_rolling_stats(baseline_values)


def update_ewma_mean(
    previous_mean: float | None,
    value: float,
    alpha: float
) -> float:
    """Updates an exponentially weighted moving average."""
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be in the range (0, 1]")
    if previous_mean is None:
        return value
    return (alpha * value) + ((1.0 - alpha) * previous_mean)


def update_ewma_variance(
    previous_variance: float,
    previous_mean: float | None,
    value: float,
    alpha: float
) -> float:
    """Updates an exponentially weighted variance using the standard recursive form."""
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be in the range (0, 1]")
    if previous_mean is None:
        return 0.0
    delta = value - previous_mean
    return (1.0 - alpha) * (previous_variance + (alpha * delta * delta))


def calculate_ewma_z_score(
    current_val: float,
    ewma_mean: float,
    ewma_std: float,
    flat_anomaly_score: float = 4.0
) -> float:
    """Calculates a Z-score of a value against the current EWMA baseline."""
    if ewma_std <= 0.0:
        return 0.0 if current_val <= ewma_mean else flat_anomaly_score
    return (current_val - ewma_mean) / ewma_std


def update_cusum(
    previous_cusum: float,
    value: float,
    baseline_center: float,
    baseline_scale: float,
    drift_sigma: float = 0.5,
    threshold_sigma: float = 5.0
) -> tuple[float, bool]:
    """
    Updates a one-sided positive CUSUM detector.

    Args:
        previous_cusum: Accumulated positive deviation from the baseline.
        value: Current observation (e.g. chat velocity).
        baseline_center: Expected baseline value.
        baseline_scale: Baseline standard deviation.
        drift_sigma: Allowance (in baseline sigmas) before accumulation.
        threshold_sigma: Alarm threshold (in baseline sigmas).

    Returns:
        tuple[new_cusum, alarm]
    """
    if baseline_scale <= 0.0:
        return 0.0, False

    drift = drift_sigma * baseline_scale
    threshold = threshold_sigma * baseline_scale
    new_cusum = max(0.0, previous_cusum + value - baseline_center - drift)
    return new_cusum, new_cusum > threshold



