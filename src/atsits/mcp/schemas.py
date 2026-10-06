"""Pydantic schemas and error models for ATSITS MCP integration."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, Enum):
    """Structured error codes for MCP tool and service invocations."""

    STRATEGY_NOT_FOUND = "STRATEGY_NOT_FOUND"
    TRADE_NOT_FOUND = "TRADE_NOT_FOUND"
    EXPERIMENT_NOT_FOUND = "EXPERIMENT_NOT_FOUND"
    HYPOTHESIS_NOT_FOUND = "HYPOTHESIS_NOT_FOUND"
    MATERIAL_NOT_FOUND = "MATERIAL_NOT_FOUND"
    DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
    VERIFICATION_GATE_REJECTED = "VERIFICATION_GATE_REJECTED"
    CONFLICT_NOT_FOUND = "CONFLICT_NOT_FOUND"
    MISSING_INFO_NOT_FOUND = "MISSING_INFO_NOT_FOUND"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
    SERVICE_ERROR = "SERVICE_ERROR"


class ToolCategory(str, Enum):
    """Classification of tool operation type."""

    READ = "READ"
    ACTION = "ACTION"


class ToolErrorResponse(BaseModel):
    """Structured error payload returned to MCP clients."""

    model_config = ConfigDict(frozen=True)

    is_error: bool = True
    error_code: ErrorCode = Field(..., description="Canonical error code")
    message: str = Field(..., description="Human-readable safe error message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Factual error context")


class ToolSuccessResponse(BaseModel):
    """Structured success response payload."""

    model_config = ConfigDict(frozen=True)

    is_error: bool = False
    data: Any = Field(..., description="Factual result payload")


class MCPToolDefinition(BaseModel):
    """Metadata and JSON schema for an exposed MCP tool."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1, description="Tool identifier")
    description: str = Field(..., min_length=1, description="Tool functional description")
    category: ToolCategory = Field(..., description="READ or ACTION classification")
    input_schema: Dict[str, Any] = Field(..., description="JSON Schema for arguments")


# ---------------------------------------------------------------------
# Phase 6 Tool Input Argument Schemas
# ---------------------------------------------------------------------


class GetStrategyInput(BaseModel):
    """Arguments for get_strategy."""

    model_config = ConfigDict(frozen=True)
    strategy_version: Optional[str] = Field(default=None, description="Optional version to query, defaults to current")


class GetStrategyVersionInput(BaseModel):
    """Arguments for get_strategy_version."""

    model_config = ConfigDict(frozen=True)
    strategy_version: str = Field(..., min_length=1, description="Exact strategy version identifier")


class GetMarketStateInput(BaseModel):
    """Arguments for get_market_state."""

    model_config = ConfigDict(frozen=True)
    symbol: str = Field(default="BTCUSDT", description="Market symbol")


class GetTradeInput(BaseModel):
    """Arguments for get_trade."""

    model_config = ConfigDict(frozen=True)
    trade_id: str = Field(..., min_length=1, description="Unique trade identifier (e.g. trd-0001)")


class GetRecentTradesInput(BaseModel):
    """Arguments for get_recent_trades."""

    model_config = ConfigDict(frozen=True)
    symbol: Optional[str] = Field(default=None, description="Filter by trading symbol")
    strategy_version: Optional[str] = Field(default=None, description="Filter by strategy version")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of trades to return (max 100)")


class GetTradeJournalInput(BaseModel):
    """Arguments for get_trade_journal."""

    model_config = ConfigDict(frozen=True)
    run_id: Optional[str] = Field(default=None, description="Filter by execution run ID")
    symbol: Optional[str] = Field(default=None, description="Filter by symbol")
    strategy_version: Optional[str] = Field(default=None, description="Filter by strategy version")
    record_type: Optional[str] = Field(default=None, description="Filter by JournalRecordType")
    start_time: Optional[datetime] = Field(default=None, description="Filter records starting from timestamp")
    end_time: Optional[datetime] = Field(default=None, description="Filter records up to timestamp")
    limit: int = Field(default=50, ge=1, le=200, description="Maximum records to return (max 200)")


class GetPerformanceMetricsInput(BaseModel):
    """Arguments for get_performance_metrics."""

    model_config = ConfigDict(frozen=True)
    strategy_version: str = Field(default="1.0.0", description="Strategy version")
    data_path: str = Field(default="data/btcusdt_1h.csv", description="Path to historical OHLCV data")
    initial_equity: float = Field(default=10000.0, gt=0.0, description="Account starting capital")


class RunBacktestInput(BaseModel):
    """Arguments for run_backtest."""

    model_config = ConfigDict(frozen=True)
    strategy_version: str = Field(default="1.0.0", description="Strategy version to execute")
    data_path: str = Field(default="data/btcusdt_1h.csv", description="Path to historical OHLCV data")
    initial_equity: float = Field(default=10000.0, gt=0.0, description="Starting capital")
    commission_rate: float = Field(default=0.0, ge=0.0, description="Commission fee rate")
    slippage_pct: float = Field(default=0.0, ge=0.0, description="Slippage percentage")


class RunExperimentInput(BaseModel):
    """Arguments for run_experiment."""

    model_config = ConfigDict(frozen=True)
    hypothesis_id: str = Field(..., min_length=1, description="Associated hypothesis identifier")
    candidate_version: str = Field(..., min_length=1, description="Candidate strategy version identifier")
    candidate_params: Dict[str, Any] = Field(..., description="Parameter change dictionary (must satisfy one-variable rule)")
    data_path: str = Field(default="data/btcusdt_1h.csv", description="Path to historical OHLCV data")
    is_ratio: float = Field(default=0.7, gt=0.0, lt=1.0, description="In-sample ratio (default: 0.7)")
    initial_equity: float = Field(default=10000.0, gt=0.0, description="Starting equity")


class GetExperimentResultsInput(BaseModel):
    """Arguments for get_experiment_results."""

    model_config = ConfigDict(frozen=True)
    experiment_id: str = Field(..., min_length=1, description="Unique experiment identifier")


class ProposeStrategyChangeInput(BaseModel):
    """Arguments for propose_strategy_change."""

    model_config = ConfigDict(frozen=True)
    baseline_strategy_version: str = Field(default="1.0.0", min_length=1, description="Baseline strategy version")
    proposed_change: str = Field(..., min_length=1, description="Explicit proposed parameter change (e.g. fast_period: 20 -> 22)")
    rationale: str = Field(..., min_length=1, description="Observation or rationale behind proposal")
    expected_effect: str = Field(..., min_length=1, description="Anticipated effect on performance metrics")
    source: str = Field(default="gemini_research", description="Source of hypothesis")


# ---------------------------------------------------------------------
# Phase 7 Teaching & Extraction Tool Input Argument Schemas
# ---------------------------------------------------------------------


class CreateTeachingMaterialInput(BaseModel):
    """Arguments for create_teaching_material."""

    model_config = ConfigDict(frozen=True)
    title: str = Field(..., min_length=1, description="Descriptive title of teaching material")
    content: str = Field(..., min_length=1, description="Raw teaching content (text, transcript, notes)")
    source_type: str = Field(default="TEXT", description="Classification (TEXT, TRANSCRIPT, NOTES, DOCUMENT, etc.)")
    source_reference: Optional[str] = Field(default=None, description="Attribution or reference source")


class ExtractStrategyDraftInput(BaseModel):
    """Arguments for extract_strategy_draft."""

    model_config = ConfigDict(frozen=True)
    material_ids: List[str] = Field(..., min_length=1, description="List of material IDs to extract from")
    strategy_name: Optional[str] = Field(default=None, description="Optional target strategy name")
    proposed_version: str = Field(default="1.0.0", description="Proposed strategy version string")


class GetStrategyDraftInput(BaseModel):
    """Arguments for get_strategy_draft."""

    model_config = ConfigDict(frozen=True)
    draft_id: str = Field(..., min_length=1, description="Draft identifier")
    revision: Optional[int] = Field(default=None, description="Optional revision number (defaults to latest)")


class GetExtractionAmbiguitiesInput(BaseModel):
    """Arguments for get_extraction_ambiguities."""

    model_config = ConfigDict(frozen=True)
    draft_id: str = Field(..., min_length=1, description="Draft identifier")


class GetExtractionConflictsInput(BaseModel):
    """Arguments for get_extraction_conflicts."""

    model_config = ConfigDict(frozen=True)
    draft_id: str = Field(..., min_length=1, description="Draft identifier")


class GetReviewStatusInput(BaseModel):
    """Arguments for get_review_status."""

    model_config = ConfigDict(frozen=True)
    draft_id: str = Field(..., min_length=1, description="Draft identifier")


class SubmitHumanReviewInput(BaseModel):
    """Arguments for submit_human_review."""

    model_config = ConfigDict(frozen=True)
    draft_id: str = Field(..., min_length=1, description="Target draft identifier")
    reviewer: str = Field(..., min_length=1, description="Human reviewer identifier (must be human authority)")
    action: str = Field(..., min_length=1, description="ReviewAction (APPROVE_RULE, CORRECT_RULE, RESOLVE_CONFLICT, PROVIDE_CLARIFICATION, APPROVE_DRAFT, REJECT_DRAFT)")
    target: str = Field(..., min_length=1, description="Target entity ID or field being reviewed")
    value: Optional[str] = Field(default=None, description="New value, resolution, or correction")
    reason: Optional[str] = Field(default=None, description="Rationale for the review action")


class GetVerifiedStrategyInput(BaseModel):
    """Arguments for get_verified_strategy."""

    model_config = ConfigDict(frozen=True)
    strategy_id: str = Field(..., min_length=1, description="Strategy identifier")
    version: Optional[str] = Field(default=None, description="Strategy version")


# ---------------------------------------------------------------------
# Phase 9 Binance Market Data + Paper Trading Input Schemas
# ---------------------------------------------------------------------


class GetBinanceMarketStatusInput(BaseModel):
    """Arguments for get_binance_market_status."""

    model_config = ConfigDict(frozen=True)
    symbol: str = Field(default="BTCUSDT", description="Market symbol to check status for")


class GetBinanceCandlesInput(BaseModel):
    """Arguments for get_binance_candles."""

    model_config = ConfigDict(frozen=True)
    symbol: str = Field(default="BTCUSDT", description="Market symbol")
    interval: str = Field(default="1h", description="Kline interval (e.g. 1h, 15m)")
    limit: int = Field(default=10, ge=1, le=100, description="Number of completed candles to return (max 100)")


class GetBinancePriceInput(BaseModel):
    """Arguments for get_binance_price."""

    model_config = ConfigDict(frozen=True)
    symbol: str = Field(default="BTCUSDT", description="Market symbol to fetch price for")


class GetBinanceAccountStatusInput(BaseModel):
    """Arguments for get_binance_account_status."""

    model_config = ConfigDict(frozen=True)


class GetBinanceBalancesInput(BaseModel):
    """Arguments for get_binance_balances."""

    model_config = ConfigDict(frozen=True)
    assets: Optional[List[str]] = Field(default=None, description="Optional asset filter list (e.g. ['BTC', 'USDT'])")
    hide_zero: bool = Field(default=True, description="Exclude zero-balance assets")


class GetPaperSessionInput(BaseModel):
    """Arguments for get_paper_session."""

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")


class GetPaperAccountInput(BaseModel):
    """Arguments for get_paper_account."""

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")


class GetPaperPositionsInput(BaseModel):
    """Arguments for get_paper_positions."""

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")


class GetPaperOrdersInput(BaseModel):
    """Arguments for get_paper_orders."""

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")


class GetPaperTradesInput(BaseModel):
    """Arguments for get_paper_trades."""

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum trades to return")


class PlacePaperOrderInput(BaseModel):
    """Arguments for place_paper_order.

    NOTE: This places a simulated paper order ONLY.
    No real Binance execution ever occurs.
    """

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")
    side: str = Field(..., description="Order side: BUY (LONG entry) or SELL (SHORT entry)")
    quantity: float = Field(..., gt=0.0, description="Position size in base asset units")
    stop_price: float = Field(..., gt=0.0, description="Stop loss price level")
    target_price: float = Field(..., gt=0.0, description="Take profit price level")


class ClosePaperPositionInput(BaseModel):
    """Arguments for close_paper_position.

    NOTE: This closes a simulated paper position ONLY.
    No real Binance execution ever occurs.
    """

    model_config = ConfigDict(frozen=True)
    session_id: Optional[str] = Field(default=None, description="Paper session ID (defaults to active session)")
