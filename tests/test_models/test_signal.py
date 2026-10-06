"""Unit tests for Signal model."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from atsits.models.signal import Signal, SignalDirection


def test_valid_signal_creation():
    """Verify standard valid Signal creation and fields."""
    now = datetime.now(timezone.utc)
    signal = Signal(
        signal_id="sig-001",
        symbol="BTCUSDT",
        timeframe="5m",
        timestamp=now,
        direction=SignalDirection.LONG,
        price=60000.0,
        strategy_name="EMA_Cross",
        strategy_version="1.0.0",
    )
    assert signal.signal_id == "sig-001"
    assert signal.direction == SignalDirection.LONG
    assert signal.direction == "LONG"
    assert signal.price == 60000.0

    dumped = signal.model_dump()
    reconstructed = Signal.model_validate(dumped)
    assert reconstructed == signal


def test_invalid_signal_direction():
    """Verify rejection of unsupported signal directions."""
    with pytest.raises(ValidationError):
        Signal(
            signal_id="sig-002",
            symbol="BTCUSDT",
            timeframe="5m",
            timestamp=datetime.now(timezone.utc),
            direction="SIDEWAYS",  # type: ignore
            price=60000.0,
            strategy_name="EMA_Cross",
            strategy_version="1.0.0",
        )


def test_invalid_signal_price():
    """Verify rejection of non-positive price."""
    with pytest.raises(ValidationError):
        Signal(
            signal_id="sig-003",
            symbol="BTCUSDT",
            timeframe="5m",
            timestamp=datetime.now(timezone.utc),
            direction=SignalDirection.SHORT,
            price=0.0,  # Invalid: must be > 0
            strategy_name="EMA_Cross",
            strategy_version="1.0.0",
        )
