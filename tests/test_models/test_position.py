"""Unit tests for Position model."""

import pytest
from pydantic import ValidationError
from atsits.models.position import Position, PositionSide


def test_valid_position():
    """Verify position creation and default fields."""
    pos = Position(
        position_id="pos-001",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=1.5,
        entry_price=60000.0,
        current_price=61000.0,
        unrealized_pnl=1500.0,
    )
    assert pos.is_open is True
    assert pos.realized_pnl == 0.0
    assert pos.unrealized_pnl == 1500.0


def test_invalid_position_quantity():
    """Verify rejection of non-positive quantity."""
    with pytest.raises(ValidationError):
        Position(
            position_id="pos-002",
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            quantity=0.0,
            entry_price=60000.0,
        )


def test_invalid_position_entry_price():
    """Verify rejection of non-positive entry price."""
    with pytest.raises(ValidationError):
        Position(
            position_id="pos-003",
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=-100.0,
        )
