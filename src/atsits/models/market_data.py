"""Market data models representing OHLCV price information."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Candle(BaseModel):
    """Represents a single OHLCV price candle.

    Validates price integrity:
    - All prices must be strictly positive (> 0)
    - Volume must be non-negative (>= 0)
    - High must be greater than or equal to Open, Close, and Low
    - Low must be less than or equal to Open, Close, and High
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., min_length=1, description="Trading pair symbol (e.g. BTCUSDT)")
    timeframe: str = Field(..., min_length=1, description="Candle interval (e.g. 1m, 5m, 1h, 1d)")
    timestamp: datetime = Field(..., description="Candle open or close timestamp in UTC")
    open: float = Field(..., gt=0.0, description="Opening price")
    high: float = Field(..., gt=0.0, description="Highest price during interval")
    low: float = Field(..., gt=0.0, description="Lowest price during interval")
    close: float = Field(..., gt=0.0, description="Closing price")
    volume: float = Field(..., ge=0.0, description="Trading volume")

    @model_validator(mode="after")
    def validate_price_bounds(self) -> "Candle":
        if self.high < self.low:
            raise ValueError(f"High price ({self.high}) cannot be lower than Low price ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(f"High price ({self.high}) must be >= open ({self.open}) and close ({self.close})")
        if self.low > self.open or self.low > self.close:
            raise ValueError(f"Low price ({self.low}) must be <= open ({self.open}) and close ({self.close})")
        return self
