"""Domain models for backtesting, trade tracking, and performance reporting."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from atsits.models.types import FrozenMapping


class CostModel(BaseModel):
    """Transaction cost model representing commission and slippage."""

    model_config = ConfigDict(frozen=True)

    commission_rate: float = Field(
        default=0.0,
        ge=0.0,
        description="Proportional commission rate per trade value (e.g. 0.001 for 0.1%)",
    )
    slippage_points: float = Field(
        default=0.0,
        ge=0.0,
        description="Fixed absolute price slippage per unit executed",
    )
    slippage_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Percentage price slippage applied adversely to execution price",
    )


class SetupRejection(BaseModel):
    """Record of a strategy setup that was rejected before execution."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    timestamp: datetime = Field(..., description="Timestamp when the rejection occurred")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol")
    direction: str = Field(..., description="Intended direction: LONG or SHORT")
    reason: str = Field(..., min_length=1, description="Reason code for rejection")
    details: FrozenMapping = Field(
        default_factory=dict,
        description="Factual context for the rejection",
    )


class SimulatedTrade(BaseModel):
    """Factual record of a completed trade in backtesting."""

    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., min_length=1, description="Unique trade identifier")
    strategy_version: str = Field(..., min_length=1, description="Strategy version string")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol")
    timeframe: str = Field(..., min_length=1, description="Bar timeframe")
    direction: str = Field(..., description="Position direction: LONG or SHORT")
    pullback_timestamp: datetime = Field(..., description="Timestamp of the qualifying pullback candle")
    confirmation_timestamp: datetime = Field(..., description="Timestamp of the qualifying confirmation candle")
    entry_timestamp: datetime = Field(..., description="Timestamp of the bar at which entry was executed")
    entry_price: float = Field(..., gt=0.0, description="Effective entry execution price")
    stop_price: float = Field(..., gt=0.0, description="Stop loss price level")
    target_price: float = Field(..., gt=0.0, description="Take profit target price level (2R)")
    quantity: float = Field(..., gt=0.0, description="Position size in asset units")
    risk_amount: float = Field(..., gt=0.0, description="Planned capital risk for this trade")
    exit_timestamp: datetime = Field(..., description="Timestamp of exit execution bar")
    exit_price: float = Field(..., gt=0.0, description="Effective exit execution price")
    exit_reason: str = Field(..., description="Reason for exit: TP_HIT, SL_HIT, or END_OF_DATA")
    gross_pnl: float = Field(..., description="Gross profit/loss before fees and slippage")
    fees: float = Field(default=0.0, ge=0.0, description="Total commission fees charged")
    slippage: float = Field(default=0.0, ge=0.0, description="Total slippage cost in quote currency")
    net_pnl: float = Field(..., description="Net realized profit/loss after fees and slippage")
    r_multiple: float = Field(..., description="Realized R-multiple relative to planned risk")


class BacktestConfig(BaseModel):
    """Configuration governing backtest parameters."""

    model_config = ConfigDict(frozen=True)

    initial_equity: float = Field(default=10000.0, gt=0.0, description="Starting account equity")
    risk_pct: float = Field(
        default=0.01,
        gt=0.0,
        le=1.0,
        description="Fraction of account equity risked per trade (e.g. 0.01 for 1%)",
    )
    max_open_positions: int = Field(default=1, ge=1, description="Maximum open positions allowed")
    cost_model: CostModel = Field(default_factory=CostModel, description="Transaction cost settings")


class BacktestResult(BaseModel):
    """Summary of backtesting metrics and factual trade records."""

    model_config = ConfigDict(frozen=True)

    strategy_version: str = Field(..., min_length=1, description="Strategy version executed")
    dataset_start: Optional[datetime] = Field(None, description="Start timestamp of tested dataset")
    dataset_end: Optional[datetime] = Field(None, description="End timestamp of tested dataset")
    initial_equity: float = Field(..., gt=0.0, description="Initial account equity")
    final_equity: float = Field(..., description="Final account equity at end of test")
    total_net_pnl: float = Field(..., description="Total net profit/loss")
    total_return_pct: float = Field(..., description="Total percentage return on initial equity")
    number_of_trades: int = Field(..., ge=0, description="Total completed trades")
    winning_trades: int = Field(..., ge=0, description="Number of profitable trades")
    losing_trades: int = Field(..., ge=0, description="Number of losing trades")
    win_rate: float = Field(..., ge=0.0, le=1.0, description="Win rate ratio (0.0 to 1.0)")
    gross_profit: float = Field(..., ge=0.0, description="Sum of positive trade PnLs")
    gross_loss: float = Field(..., ge=0.0, description="Sum of absolute negative trade PnLs")
    profit_factor: float = Field(..., ge=0.0, description="Ratio of gross profit to gross loss")
    max_drawdown: float = Field(..., ge=0.0, description="Maximum absolute peak-to-trough equity drop")
    max_drawdown_pct: float = Field(..., ge=0.0, le=1.0, description="Maximum percentage peak-to-trough drop")
    average_trade_pnl: float = Field(..., description="Average net PnL per trade")
    trades: List[SimulatedTrade] = Field(default_factory=list, description="Factual list of simulated trades")
    rejections: List[SetupRejection] = Field(default_factory=list, description="List of rejected setups")
