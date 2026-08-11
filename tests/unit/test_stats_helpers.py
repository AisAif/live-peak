from app.utils.stats_helpers import calculate_z_score, calculate_rolling_stats


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
