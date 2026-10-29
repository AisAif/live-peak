import pytest

from app.utils.stats_helpers import (
    calculate_baseline_center_scale,
    calculate_ewma_z_score,
    calculate_z_score,
    calculate_rolling_stats,
    calculate_robust_stats,
    calculate_robust_z_score,
    calculate_window_z_score,
    format_seconds_to_timestamp,
    update_cusum,
    update_ewma_mean,
    update_ewma_variance,
)


def test_calculate_z_score_normal():
    # Mean 10, std 2, val 14 -> Z = (14-10)/2 = 2.0
    z = calculate_z_score(14.0, 10.0, 2.0)
    assert z == 2.0


def test_calculate_z_score_zero_std():
    # Std 0 should return 0.0 without division by zero error
    z = calculate_z_score(10.0, 10.0, 0.0)
    assert z == 0.0


def test_calculate_rolling_stats():
    values = [10.0, 20.0, 30.0]
    mean, std = calculate_rolling_stats(values)
    assert mean == 20.0
    assert round(std, 2) == 8.16


def test_calculate_robust_stats_ignores_single_extreme_value():
    median, mad = calculate_robust_stats([0.1, 0.2, 0.1, 0.2, 100.0])
    assert median == 0.2
    assert mad == 0.1


def test_calculate_robust_z_score_normalizes_mad():
    # (2.0 - 0.2) / (1.4826 * 0.1)
    z = calculate_robust_z_score(2.0, 0.2, 0.1)
    assert round(z, 2) == 12.14


def test_calculate_robust_z_score_zero_mad():
    z = calculate_robust_z_score(5.0, 1.0, 0.0)
    assert z == 0.0


def test_calculate_window_z_score_flat_baseline_returns_anomaly_score():
    z = calculate_window_z_score(
        1.0, [0.0, 0.0, 0.0], method="mad", flat_anomaly_score=3.5
    )
    assert z == 3.5


def test_calculate_window_z_score_mad_falls_back_to_std():
    # Median 0.1 and MAD 0, but std > 0
    z = calculate_window_z_score(1.0, [0.1, 0.1, 0.1, 0.3], method="mad")
    assert z > 0.0


def test_calculate_window_z_score_rejects_unknown_method():
    with pytest.raises(ValueError):
        calculate_window_z_score(1.0, [1.0, 2.0], method="unknown")


def test_calculate_baseline_center_scale_prefers_robust_stats():
    center, scale = calculate_baseline_center_scale([0.1, 0.2, 0.1, 0.2, 100.0])
    assert center == 0.2
    assert round(scale, 5) == 0.14826


def test_calculate_baseline_center_scale_falls_back_to_mean_std():
    center, scale = calculate_baseline_center_scale([0.1, 0.1, 0.1, 0.3])
    assert center == pytest.approx(0.15)
    assert scale > 0.0


def test_update_ewma_mean_and_variance():
    mean = update_ewma_mean(None, 2.0, 0.5)
    assert mean == 2.0
    assert update_ewma_mean(1.0, 3.0, 0.5) == 2.0
    assert update_ewma_variance(0.0, 1.0, 3.0, 0.5) == 1.0


def test_calculate_ewma_z_score():
    assert calculate_ewma_z_score(3.0, 1.0, 1.0) == 2.0
    assert calculate_ewma_z_score(3.0, 1.0, 0.0, flat_anomaly_score=4.0) == 4.0
    assert calculate_ewma_z_score(1.0, 1.0, 0.0) == 0.0


def test_update_cusum_accumulates_and_alarms():
    value, alarm = update_cusum(0.0, 2.0, 1.0, 0.5)
    assert value == 0.75
    assert alarm is False

    value, alarm = update_cusum(2.0, 3.0, 1.0, 0.5)
    assert value == 3.75
    assert alarm is True


def test_update_cusum_with_flat_baseline_does_not_alarm():
    assert update_cusum(0.0, 5.0, 0.0, 0.0) == (0.0, False)


def test_update_ewma_rejects_invalid_alpha():
    with pytest.raises(ValueError):
        update_ewma_mean(None, 1.0, 0.0)


def test_format_seconds_to_timestamp():
    assert format_seconds_to_timestamp(0) == "00:00"
    assert format_seconds_to_timestamp(45) == "00:45"
    assert format_seconds_to_timestamp(75) == "01:15"
    assert format_seconds_to_timestamp(3600) == "01:00:00"
    assert format_seconds_to_timestamp(3665) == "01:01:05"



