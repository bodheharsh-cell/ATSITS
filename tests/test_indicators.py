"""Tests for Technical Indicators (EMA)."""

import pytest
from atsits.indicators.ema import EMAIndicator, calculate_ema_series


def test_ema_indicator_warmup():
    """Verify EMA remains None during the warmup period and begins at index period - 1."""
    ema20 = EMAIndicator(period=20)
    prices = [100.0 + i for i in range(30)]

    for i in range(19):
        val = ema20.update(prices[i])
        assert val is None
        assert not ema20.is_ready

    # 20th price (index 19) should yield SMA of first 20 prices
    val_20 = ema20.update(prices[19])
    assert val_20 is not None
    assert ema20.is_ready
    expected_sma = sum(prices[:20]) / 20.0
    assert pytest.approx(val_20, 1e-6) == expected_sma

    # 21st price should follow EMA recursive formula
    val_21 = ema20.update(prices[20])
    alpha = 2.0 / 21.0
    expected_ema_21 = (alpha * prices[20]) + ((1.0 - alpha) * val_20)
    assert pytest.approx(val_21, 1e-6) == expected_ema_21


def test_ema_series_matches_incremental():
    """Verify calculate_ema_series matches incremental bar-by-bar EMAIndicator updates."""
    prices = [50.0 + (i * 0.5) for i in range(60)]
    series_res = calculate_ema_series(prices, period=50)

    indicator = EMAIndicator(period=50)
    incremental_res = [indicator.update(p) for p in prices]

    assert series_res == incremental_res
    assert series_res[48] is None
    assert series_res[49] is not None


def test_invalid_ema_period():
    """Verify invalid EMA period (< 1) raises ValueError."""
    with pytest.raises(ValueError, match="period must be >= 1"):
        EMAIndicator(period=0)
