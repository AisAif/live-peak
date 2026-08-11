"""
Pure statistical helper functions for Z-Score calculation and sliding window baseline math.
"""
import numpy as np


def calculate_z_score(current_val: float, baseline_mean: float, baseline_std: float) -> float:
    """
    Calculates the Z-score for a given value relative to baseline mean and standard deviation.
    
    Z = (x - mean) / std
    Returns 0.0 if standard deviation is 0 (to avoid division by zero).
    """
    if baseline_std <= 0.0:
        return 0.0
    return float((current_val - baseline_mean) / baseline_std)


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
