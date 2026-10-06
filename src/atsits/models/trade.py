"""Trade fill models representing factual execution results."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from atsits.models.order import OrderSide


class Trade(BaseModel):
    """Represents a factual executed trade fill."""

    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., min_length=1, description="Unique identifier for the trade execution")
    order_id: str = Field(..., min_length=1, description="Associated order identifier")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol (e.g. BTCUSDT)")
    side: OrderSide = Field(..., description="Trade side: BUY or SELL")
    price: float = Field(..., gt=0.0, description="Executed fill price")
    quantity: float = Field(..., gt=0.0, description="Executed fill quantity")
    timestamp: datetime = Field(..., description="Execution timestamp")
    commission: float = Field(default=0.0, ge=0.0, description="Transaction fee / commission")
    slippage: float = Field(default=0.0, ge=0.0, description="Observed slippage relative to expected price")
