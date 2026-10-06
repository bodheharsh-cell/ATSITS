"""Order models representing trading orders."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrderSide(str, Enum):
    """Side of the order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Type of the order."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    """Lifecycle status of an order."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Order(BaseModel):
    """Represents a trading order sent for execution."""

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., min_length=1, description="Unique identifier for the order")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol (e.g. BTCUSDT)")
    side: OrderSide = Field(..., description="Order side: BUY or SELL")
    order_type: OrderType = Field(..., description="Order type: MARKET or LIMIT")
    quantity: float = Field(..., gt=0.0, description="Order quantity")
    price: Optional[float] = Field(None, gt=0.0, description="Limit price, required for LIMIT orders")
    timestamp: datetime = Field(..., description="Order placement timestamp")
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="Current status of the order")

    @model_validator(mode="after")
    def validate_limit_price(self) -> "Order":
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Price is required for LIMIT orders")
        return self
