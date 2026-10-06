"""Domain models for paper trading positions and account states."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PaperPosition(BaseModel):
    """Immutable representation of an active or closed paper trading position."""

    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., min_length=1, description="Unique trade identifier")
    strategy_version: str = Field(..., min_length=1, description="Strategy version")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol")
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    direction: str = Field(..., description="Position direction: LONG or SHORT")
    pullback_timestamp: datetime = Field(..., description="Timestamp of qualifying pullback candle")
    confirmation_timestamp: datetime = Field(..., description="Timestamp of confirmation candle")
    entry_timestamp: datetime = Field(..., description="Timestamp of entry execution")
    raw_entry_price: float = Field(..., gt=0.0, description="Raw open price at entry")
    entry_price: float = Field(..., gt=0.0, description="Effective entry price after slippage")
    stop_price: float = Field(..., gt=0.0, description="Stop loss price")
    target_price: float = Field(..., gt=0.0, description="Take profit target price")
    quantity: float = Field(..., gt=0.0, description="Position size in asset units")
    risk_amount: float = Field(..., gt=0.0, description="Planned risk amount in quote currency")
    equity_before: float = Field(..., gt=0.0, description="Account equity before entry")
    entry_fee: float = Field(default=0.0, ge=0.0, description="Entry commission fee")
    entry_slippage: float = Field(default=0.0, ge=0.0, description="Entry slippage cost")


class PaperAccountState(BaseModel):
    """Snapshot of paper account state for persistence and inspection."""

    model_config = ConfigDict(frozen=True)

    initial_equity: float = Field(..., gt=0.0, description="Initial account starting capital")
    cash_balance: float = Field(..., description="Current cash balance excluding active position margin")
    equity: float = Field(..., description="Total equity at snapshot time")
    realized_pnl: float = Field(default=0.0, description="Cumulative realized net PnL")
    total_fees: float = Field(default=0.0, ge=0.0, description="Cumulative fees paid")
    total_slippage: float = Field(default=0.0, ge=0.0, description="Cumulative slippage cost")
    trade_count: int = Field(default=0, ge=0, description="Total completed trades")
    active_position: Optional[PaperPosition] = Field(default=None, description="Currently open position if any")
