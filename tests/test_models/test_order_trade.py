"""Unit tests for Order and Trade models."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from atsits.models.order import Order, OrderSide, OrderStatus, OrderType
from atsits.models.trade import Trade


def test_valid_market_order():
    """Verify market order creation without price."""
    now = datetime.now(timezone.utc)
    order = Order(
        order_id="ord-001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.5,
        timestamp=now,
    )
    assert order.order_id == "ord-001"
    assert order.status == OrderStatus.PENDING
    assert order.price is None


def test_valid_limit_order():
    """Verify limit order creation with price."""
    now = datetime.now(timezone.utc)
    order = Order(
        order_id="ord-002",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=0.25,
        price=65000.0,
        timestamp=now,
        status=OrderStatus.FILLED,
    )
    assert order.order_type == OrderType.LIMIT
    assert order.price == 65000.0
    assert order.status == OrderStatus.FILLED


def test_limit_order_missing_price():
    """Verify that LIMIT orders require a valid price."""
    with pytest.raises(ValidationError, match="Price is required for LIMIT orders"):
        Order(
            order_id="ord-003",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.1,
            price=None,
            timestamp=datetime.now(timezone.utc),
        )


def test_invalid_order_quantity():
    """Verify rejection of non-positive quantity."""
    with pytest.raises(ValidationError):
        Order(
            order_id="ord-004",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.0,
            timestamp=datetime.now(timezone.utc),
        )


def test_valid_trade_execution():
    """Verify Trade model creation with execution facts."""
    now = datetime.now(timezone.utc)
    trade = Trade(
        trade_id="trd-001",
        order_id="ord-001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=62000.0,
        quantity=0.5,
        timestamp=now,
        commission=1.24,
        slippage=0.5,
    )
    assert trade.trade_id == "trd-001"
    assert trade.commission == 1.24
    assert trade.slippage == 0.5


def test_invalid_trade_commission():
    """Verify rejection of negative commission or slippage."""
    with pytest.raises(ValidationError):
        Trade(
            trade_id="trd-002",
            order_id="ord-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            price=62000.0,
            quantity=0.5,
            timestamp=datetime.now(timezone.utc),
            commission=-0.1,
        )
