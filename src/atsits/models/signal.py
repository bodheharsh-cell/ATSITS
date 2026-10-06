"""Trading signal models."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class SignalDirection(str, Enum):
    """Direction of a generated trade signal."""

    LONG = "LONG"
    SHORT = "SHORT"


class Signal(BaseModel):
    """Represents a trading signal produced by strategy evaluation."""

    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(..., min_length=1, description="Unique identifier for the signal")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol (e.g. BTCUSDT)")
    timeframe: str = Field(..., min_length=1, description="Timeframe on which signal occurred")
    timestamp: datetime = Field(..., description="Timestamp when signal was generated")
    direction: SignalDirection = Field(..., description="Signal direction: LONG or SHORT")
    price: float = Field(..., gt=0.0, description="Reference price at the time of signal")
    strategy_name: str = Field(..., min_length=1, description="Name of strategy generating signal")
    strategy_version: str = Field(..., min_length=1, description="Explicit version of strategy")
