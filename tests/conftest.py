"""Pytest fixtures and helpers for deterministic synthetic test data."""

from datetime import datetime, timedelta, timezone
from typing import List
import pytest
from atsits.models.market_data import Candle


def make_candle(
    index: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    volume: float = 100.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    base_time: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
) -> Candle:
    """Create a single validated Candle."""
    ts = base_time + timedelta(hours=index)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=volume,
    )


def make_flat_candles(
    count: int,
    price: float = 100.0,
    start_index: int = 0,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> List[Candle]:
    """Create a series of flat price candles."""
    return [
        make_candle(
            index=start_index + i,
            open_p=price,
            high_p=price + 0.1,
            low_p=price - 0.1,
            close_p=price,
            symbol=symbol,
            timeframe=timeframe,
        )
        for i in range(count)
    ]


def make_trending_candles(
    count: int,
    start_price: float = 100.0,
    step: float = 1.0,
    start_index: int = 0,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> List[Candle]:
    """Create a series of steady upward or downward trending candles."""
    candles = []
    for i in range(count):
        p = start_price + (i * step)
        c_open = p
        c_close = p + step
        c_high = max(c_open, c_close) + 0.5
        c_low = min(c_open, c_close) - 0.5
        candles.append(
            make_candle(
                index=start_index + i,
                open_p=c_open,
                high_p=c_high,
                low_p=c_low,
                close_p=c_close,
                symbol=symbol,
                timeframe=timeframe,
            )
        )
    return candles
