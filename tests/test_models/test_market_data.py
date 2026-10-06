"""Unit tests for Candle / MarketData models."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from atsits.models.market_data import Candle


def test_valid_candle_creation():
    """Verify standard valid Candle construction and serialization."""
    now = datetime.now(timezone.utc)
    candle = Candle(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=now,
        open=50000.0,
        high=51000.0,
        low=49500.0,
        close=50500.0,
        volume=120.5,
    )
    assert candle.symbol == "BTCUSDT"
    assert candle.timeframe == "1h"
    assert candle.open == 50000.0
    assert candle.high == 51000.0
    assert candle.low == 49500.0
    assert candle.close == 50500.0
    assert candle.volume == 120.5

    # Test serialization / deserialization roundtrip
    dumped = candle.model_dump()
    reconstructed = Candle.model_validate(dumped)
    assert reconstructed == candle


def test_candle_immutability():
    """Verify Candle model is frozen."""
    candle = Candle(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=51000.0,
        low=49500.0,
        close=50500.0,
        volume=10.0,
    )
    with pytest.raises(ValidationError):
        candle.close = 52000.0  # type: ignore


@pytest.mark.parametrize(
    "open_p, high_p, low_p, close_p, volume",
    [
        (50000.0, 49000.0, 48000.0, 48500.0, 10.0),  # high < open
        (50000.0, 50500.0, 48000.0, 51000.0, 10.0),  # high < close
        (50000.0, 51000.0, 50200.0, 50500.0, 10.0),  # low > open
        (50000.0, 51000.0, 49800.0, 49500.0, 10.0),  # low > close
        (50000.0, 48000.0, 51000.0, 49000.0, 10.0),  # high < low
        (0.0, 51000.0, 49000.0, 50000.0, 10.0),      # non-positive open
        (50000.0, 51000.0, 49000.0, 50000.0, -1.0),   # negative volume
    ],
)
def test_invalid_candle_rejection(open_p, high_p, low_p, close_p, volume):
    """Verify that candles with broken OHLC relations or invalid values are rejected."""
    with pytest.raises(ValidationError):
        Candle(
            symbol="BTCUSDT",
            timeframe="1h",
            timestamp=datetime.now(timezone.utc),
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=volume,
        )
