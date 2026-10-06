"""Domain models for factual trading journal records."""

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, ConfigDict, Field
from atsits.models.types import FrozenMapping

JOURNAL_SCHEMA_VERSION: str = "1.0.0"


class JournalRecordType(str, Enum):
    """Enumeration of factual journal record types."""

    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    SETUP_DETECTED = "SETUP_DETECTED"
    SETUP_REJECTED = "SETUP_REJECTED"
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    TRADE = "TRADE"


class BaseJournalRecord(BaseModel):
    """Base schema for all immutable factual journal records."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    schema_version: str = Field(
        default=JOURNAL_SCHEMA_VERSION,
        description="Explicit journal schema version",
    )
    record_id: str = Field(..., min_length=1, description="Unique, deterministic record identifier")
    record_type: JournalRecordType = Field(..., description="Factual record classification")
    timestamp: datetime = Field(..., description="Timestamp of the event / observation in UTC")
    run_id: str = Field(..., min_length=1, description="Identifier of the execution/backtest run")
    strategy_version: str = Field(..., min_length=1, description="Version of the executing strategy")
    execution_mode: str = Field(default="BACKTEST", description="Execution mode (e.g. BACKTEST, PAPER, LIVE)")
    symbol: str = Field(..., min_length=1, description="Trading pair symbol (e.g. BTCUSDT)")


class MarketObservationRecord(BaseJournalRecord):
    """Factual market observation snapshot relevant to strategy state."""

    record_type: JournalRecordType = Field(default=JournalRecordType.MARKET_OBSERVATION, frozen=True)
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    open: float = Field(..., gt=0.0, description="Bar open price")
    high: float = Field(..., gt=0.0, description="Bar high price")
    low: float = Field(..., gt=0.0, description="Bar low price")
    close: float = Field(..., gt=0.0, description="Bar close price")
    volume: float = Field(..., ge=0.0, description="Bar volume")
    ema20: Optional[float] = Field(None, description="Calculated EMA20 value if available")
    ema50: Optional[float] = Field(None, description="Calculated EMA50 value if available")
    trend: Optional[str] = Field(None, description="Observed trend alignment (e.g. UPTREND, DOWNTREND, NONE)")


class SetupDetectedRecord(BaseJournalRecord):
    """Factual record of a strategy setup identified and confirmed by rules."""

    record_type: JournalRecordType = Field(default=JournalRecordType.SETUP_DETECTED, frozen=True)
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    direction: str = Field(..., description="Setup direction: LONG or SHORT")
    pullback_timestamp: datetime = Field(..., description="Timestamp of qualifying pullback candle")
    pullback_high: float = Field(..., gt=0.0, description="High price of pullback candle")
    pullback_low: float = Field(..., gt=0.0, description="Low price of pullback candle")
    confirmation_timestamp: datetime = Field(..., description="Timestamp of qualifying confirmation candle")
    ema20: float = Field(..., gt=0.0, description="EMA20 value on confirmation candle")
    ema50: float = Field(..., gt=0.0, description="EMA50 value on confirmation candle")
    facts: FrozenMapping = Field(default_factory=dict, description="Additional deterministic setup facts")


class SetupRejectedRecord(BaseJournalRecord):
    """Factual record of a setup that did not proceed to trade execution."""

    record_type: JournalRecordType = Field(default=JournalRecordType.SETUP_REJECTED, frozen=True)
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    direction: str = Field(..., description="Intended direction: LONG or SHORT")
    reason: str = Field(..., min_length=1, description="Deterministic rejection reason code")
    details: FrozenMapping = Field(default_factory=dict, description="Factual context for rejection")


class EntryRecord(BaseJournalRecord):
    """Factual record of an executed market entry."""

    record_type: JournalRecordType = Field(default=JournalRecordType.ENTRY, frozen=True)
    trade_id: str = Field(..., min_length=1, description="Associated trade identifier")
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    direction: str = Field(..., description="Position direction: LONG or SHORT")
    price: float = Field(..., gt=0.0, description="Effective entry execution price")
    raw_price: float = Field(..., gt=0.0, description="Unadjusted open/market price at entry")
    quantity: float = Field(..., gt=0.0, description="Position quantity in asset units")
    stop_price: float = Field(..., gt=0.0, description="Stop loss price level")
    target_price: float = Field(..., gt=0.0, description="Take profit target price level (2R)")
    risk_amount: float = Field(..., gt=0.0, description="Planned risk amount in quote currency")
    equity_before: float = Field(..., gt=0.0, description="Account equity immediately prior to entry")
    fees: float = Field(default=0.0, ge=0.0, description="Entry transaction fee / commission")
    slippage: float = Field(default=0.0, ge=0.0, description="Entry slippage cost in quote currency")


class ExitRecord(BaseJournalRecord):
    """Factual record of an executed position exit."""

    record_type: JournalRecordType = Field(default=JournalRecordType.EXIT, frozen=True)
    trade_id: str = Field(..., min_length=1, description="Associated trade identifier")
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    direction: str = Field(..., description="Position direction: LONG or SHORT")
    exit_price: float = Field(..., gt=0.0, description="Effective exit execution price")
    raw_exit_price: float = Field(..., gt=0.0, description="Unadjusted trigger / close price at exit")
    exit_reason: str = Field(..., min_length=1, description="Reason for exit: TP_HIT, SL_HIT, or END_OF_DATA")
    quantity: float = Field(..., gt=0.0, description="Closed quantity in asset units")
    gross_pnl: float = Field(..., description="Gross profit/loss before fees and slippage")
    fees: float = Field(default=0.0, ge=0.0, description="Total commission fees (entry + exit)")
    slippage: float = Field(default=0.0, ge=0.0, description="Total slippage cost (entry + exit)")
    net_pnl: float = Field(..., description="Net realized profit/loss after fees and slippage")
    equity_after: float = Field(..., description="Account equity immediately following exit")


class TradeRecord(BaseJournalRecord):
    """Complete lifecycle trade record uniting setup, entry, and exit facts."""

    record_type: JournalRecordType = Field(default=JournalRecordType.TRADE, frozen=True)
    trade_id: str = Field(..., min_length=1, description="Unique trade identifier")
    timeframe: str = Field(..., min_length=1, description="Candle timeframe")
    direction: str = Field(..., description="Position direction: LONG or SHORT")
    pullback_timestamp: datetime = Field(..., description="Timestamp of qualifying pullback candle")
    confirmation_timestamp: datetime = Field(..., description="Timestamp of confirmation candle")
    entry_timestamp: datetime = Field(..., description="Timestamp of entry execution bar")
    entry_price: float = Field(..., gt=0.0, description="Effective entry execution price")
    stop_price: float = Field(..., gt=0.0, description="Stop loss price level")
    target_price: float = Field(..., gt=0.0, description="Take profit target price level (2R)")
    quantity: float = Field(..., gt=0.0, description="Position size in asset units")
    risk_amount: float = Field(..., gt=0.0, description="Planned capital risk for this trade")
    exit_timestamp: datetime = Field(..., description="Timestamp of exit execution bar")
    exit_price: float = Field(..., gt=0.0, description="Effective exit execution price")
    exit_reason: str = Field(..., min_length=1, description="Reason for exit: TP_HIT, SL_HIT, or END_OF_DATA")
    gross_pnl: float = Field(..., description="Gross profit/loss before fees and slippage")
    fees: float = Field(default=0.0, ge=0.0, description="Total commission fees charged")
    slippage: float = Field(default=0.0, ge=0.0, description="Total slippage cost in quote currency")
    net_pnl: float = Field(..., description="Net realized profit/loss")
    r_multiple: float = Field(..., description="Realized R-multiple relative to planned risk")
    equity_before: float = Field(..., gt=0.0, description="Account equity prior to trade entry")
    equity_after: float = Field(..., description="Account equity after trade exit")


# Union of all specific journal record types
JournalRecord = Union[
    MarketObservationRecord,
    SetupDetectedRecord,
    SetupRejectedRecord,
    EntryRecord,
    ExitRecord,
    TradeRecord,
]

_RECORD_TYPE_MAP: Dict[str, type] = {
    JournalRecordType.MARKET_OBSERVATION.value: MarketObservationRecord,
    JournalRecordType.SETUP_DETECTED.value: SetupDetectedRecord,
    JournalRecordType.SETUP_REJECTED.value: SetupRejectedRecord,
    JournalRecordType.ENTRY.value: EntryRecord,
    JournalRecordType.EXIT.value: ExitRecord,
    JournalRecordType.TRADE.value: TradeRecord,
}


def deserialize_journal_record(data: Union[Dict[str, Any], str]) -> JournalRecord:
    """Deserialize a dictionary or JSON string into its specific JournalRecord model."""
    if isinstance(data, str):
        parsed = json.loads(data)
    elif isinstance(data, dict):
        parsed = data
    else:
        raise ValueError(f"Expected dict or JSON string, got {type(data).__name__}")

    rec_type_val = parsed.get("record_type")
    if not rec_type_val or rec_type_val not in _RECORD_TYPE_MAP:
        raise ValueError(f"Unknown or missing journal record_type: '{rec_type_val}'")

    cls = _RECORD_TYPE_MAP[rec_type_val]
    return cls.model_validate(parsed)
