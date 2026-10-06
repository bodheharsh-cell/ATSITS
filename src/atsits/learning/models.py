"""Domain models for ATSITS Phase 5 Learning and Experimentation."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from atsits.models.backtest import CostModel
from atsits.models.types import FrozenMapping


class HypothesisStatus(str, Enum):
    """Lifecycle statuses for research hypotheses."""

    PROPOSED = "PROPOSED"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class ExperimentStatus(str, Enum):
    """Lifecycle statuses for controlled experiments."""

    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PerformanceMetrics(BaseModel):
    """Factual, deterministic performance metrics calculated from trade logs."""

    model_config = ConfigDict(frozen=True)

    sample_size: int = Field(..., ge=0, description="Total number of trades analyzed")
    total_trades: int = Field(..., ge=0, description="Total completed trades")
    long_trades: int = Field(..., ge=0, description="Number of long trades")
    short_trades: int = Field(..., ge=0, description="Number of short trades")
    winning_trades: int = Field(..., ge=0, description="Number of trades with net PnL > 0")
    losing_trades: int = Field(..., ge=0, description="Number of trades with net PnL < 0")
    win_rate: float = Field(..., ge=0.0, le=1.0, description="Win rate ratio (winning / total)")
    gross_profit: float = Field(..., ge=0.0, description="Sum of positive trade PnLs")
    gross_loss: float = Field(..., ge=0.0, description="Sum of absolute negative trade PnLs")
    net_pnl: float = Field(..., description="Net realized profit/loss")
    profit_factor: Optional[float] = Field(default=None, description="Gross profit divided by gross loss")
    average_trade_pnl: float = Field(..., description="Mean net PnL across all trades")
    average_winner: float = Field(default=0.0, description="Mean PnL of winning trades")
    average_loser: float = Field(default=0.0, description="Mean PnL of losing trades")
    max_drawdown: float = Field(default=0.0, ge=0.0, description="Maximum peak-to-trough absolute equity drawdown")
    max_drawdown_pct: float = Field(default=0.0, ge=0.0, le=1.0, description="Maximum peak-to-trough percentage drawdown")
    sl_exits: int = Field(default=0, ge=0, description="Trades closed via Stop Loss")
    tp_exits: int = Field(default=0, ge=0, description="Trades closed via Take Profit")
    eod_exits: int = Field(default=0, ge=0, description="Trades closed at End of Data")
    total_r: float = Field(default=0.0, description="Cumulative realized R-multiples")
    average_r: float = Field(default=0.0, description="Average realized R per trade")
    expectancy_r: float = Field(default=0.0, description="Mathematical expectancy in R: (WinRate * AvgWinR) - (LossRate * AvgLossR)")


class ConditionSlice(BaseModel):
    """Factual performance slice conditioned on a specific market or trade attribute."""

    model_config = ConfigDict(frozen=True)

    condition_name: str = Field(..., min_length=1, description="Attribute name (e.g. direction, exit_reason, day_of_week)")
    condition_value: str = Field(..., min_length=1, description="Attribute value (e.g. LONG, TP_HIT, Monday)")
    sample_size: int = Field(..., ge=0, description="Number of trades matching condition")
    metrics: PerformanceMetrics = Field(..., description="Metrics for this conditional slice")
    data_start: Optional[datetime] = Field(None, description="Start timestamp of slice data")
    data_end: Optional[datetime] = Field(None, description="End timestamp of slice data")
    strategy_version: str = Field(..., min_length=1, description="Strategy version evaluated")
    run_id: str = Field(..., min_length=1, description="Execution run identifier")


class Hypothesis(BaseModel):
    """Structured research hypothesis proposing a controlled change to the baseline."""

    model_config = ConfigDict(frozen=True)

    hypothesis_id: str = Field(..., min_length=1, description="Unique hypothesis identifier")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    source: str = Field(..., min_length=1, description="Origin of hypothesis (e.g. human_observation)")
    description: str = Field(..., min_length=1, description="Detailed explanation of the hypothesis")
    baseline_strategy_version: str = Field(..., min_length=1, description="Target baseline strategy version")
    proposed_change: str = Field(..., min_length=1, description="Explicit parameter or condition proposed for change")
    rationale: str = Field(..., min_length=1, description="Underlying market rationale or observation")
    expected_effect: str = Field(..., min_length=1, description="Expected impact on performance metrics")
    status: HypothesisStatus = Field(default=HypothesisStatus.PROPOSED, description="Current hypothesis status")
    created_by: str = Field(default="human", description="Creator identifier")


class ExperimentSpec(BaseModel):
    """Specification for a controlled, reproducible experiment comparing baseline vs candidate."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(..., min_length=1, description="Unique experiment identifier")
    hypothesis_id: str = Field(..., min_length=1, description="Associated hypothesis identifier")
    baseline_strategy_version: str = Field(default="1.0.0", min_length=1, description="Baseline strategy version")
    candidate_strategy_version: str = Field(..., min_length=1, description="Candidate strategy version identifier")
    candidate_params: Dict[str, Any] = Field(..., description="Controlled parameter changes applied to candidate")
    dataset_id: str = Field(..., min_length=1, description="Dataset identifier")
    data_path: str = Field(..., min_length=1, description="Path to historical OHLCV data")
    initial_equity: float = Field(default=10000.0, gt=0.0, description="Starting capital")
    cost_model: CostModel = Field(default_factory=CostModel, description="Cost model applied to both runs")
    is_ratio: float = Field(default=0.7, gt=0.0, lt=1.0, description="In-sample data ratio (e.g. 0.7 for 70% IS, 30% OOS)")
    created_at: datetime = Field(..., description="UTC creation timestamp")


class MetricDifference(BaseModel):
    """Comparison delta for a specific metric between baseline and candidate."""

    model_config = ConfigDict(frozen=True)

    metric_name: str = Field(..., min_length=1, description="Metric identifier")
    baseline_value: float = Field(..., description="Baseline value")
    candidate_value: float = Field(..., description="Candidate value")
    absolute_diff: float = Field(..., description="Candidate value - Baseline value")
    relative_diff_pct: Optional[float] = Field(None, description="Percentage change relative to baseline if defined")


class ExperimentResult(BaseModel):
    """Factual, reproducible output of a controlled experiment."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(..., min_length=1, description="Unique experiment identifier")
    hypothesis_id: str = Field(..., min_length=1, description="Associated hypothesis identifier")
    baseline_strategy_version: str = Field(..., min_length=1, description="Baseline strategy version")
    candidate_strategy_version: str = Field(..., min_length=1, description="Candidate strategy version")
    candidate_params: Dict[str, Any] = Field(..., description="Parameter changes applied")
    dataset_id: str = Field(..., min_length=1, description="Dataset identifier")
    total_candles: int = Field(..., ge=0, description="Total candles in dataset")
    is_candle_count: int = Field(..., ge=0, description="Candles in In-Sample period")
    oos_candle_count: int = Field(..., ge=0, description="Candles in Out-of-Sample period")
    is_start: Optional[datetime] = Field(None, description="In-sample start timestamp")
    is_end: Optional[datetime] = Field(None, description="In-sample end timestamp")
    oos_start: Optional[datetime] = Field(None, description="Out-of-sample start timestamp")
    oos_end: Optional[datetime] = Field(None, description="Out-of-sample end timestamp")
    is_baseline_metrics: PerformanceMetrics = Field(..., description="In-sample baseline metrics")
    is_candidate_metrics: PerformanceMetrics = Field(..., description="In-sample candidate metrics")
    oos_baseline_metrics: PerformanceMetrics = Field(..., description="Out-of-sample baseline metrics")
    oos_candidate_metrics: PerformanceMetrics = Field(..., description="Out-of-sample candidate metrics")
    full_baseline_metrics: PerformanceMetrics = Field(..., description="Full dataset baseline metrics")
    full_candidate_metrics: PerformanceMetrics = Field(..., description="Full dataset candidate metrics")
    differences: Dict[str, MetricDifference] = Field(..., description="Metric differences on Out-of-Sample evaluation")
    validation_passed: bool = Field(..., description="Whether predefined validation rules were satisfied")
    validation_summary: str = Field(..., description="Neutral factual validation description")
    created_at: datetime = Field(..., description="Timestamp of experiment execution")
    status: ExperimentStatus = Field(default=ExperimentStatus.COMPLETED, description="Experiment execution status")
