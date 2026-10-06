"""Position models representing active or closed market exposure."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PositionSide(str, Enum):
    """Direction of open position."""

    LONG = "LONG"
    SHORT = "SHORT"


class Position(BaseModel):
    """Represents an asset position and its factual P&L state."""

    model_config = ConfigDict(frozen=True)

    position_id: str = Field(..., min_length=1, description="Unique identifier for the position")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol (e.g. BTCUSDT)")
    side: PositionSide = Field(..., description="Position direction: LONG or SHORT")
    quantity: float = Field(..., gt=0.0, description="Position size quantity")
    entry_price: float = Field(..., gt=0.0, description="Average entry price")
    current_price: Optional[float] = Field(None, gt=0.0, description="Latest market price")
    unrealized_pnl: float = Field(default=0.0, description="Unrealized profit and loss")
    realized_pnl: float = Field(default=0.0, description="Realized profit and loss")
    is_open: bool = Field(default=True, description="Whether the position is currently active")
