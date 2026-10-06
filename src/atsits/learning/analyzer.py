"""Performance Analyzer for evaluating overall metrics and multidimensional condition slices."""

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Union
from atsits.journal.models import TradeRecord
from atsits.journal.storage import TradingJournal
from atsits.learning.metrics import calculate_performance_metrics
from atsits.learning.models import ConditionSlice, PerformanceMetrics
from atsits.models.backtest import BacktestResult, SimulatedTrade

TradeType = Union[SimulatedTrade, TradeRecord]


class PerformanceAnalyzer:
    """Deterministic Performance and Condition Analyzer.

    Consumes factual trade records from backtests or trading journals to compute
    top-level performance metrics and condition-level segmented analyses without lookahead.
    """

    def __init__(self, initial_equity: float = 10000.0):
        self.initial_equity: float = float(initial_equity)

    def analyze_trades(
        self,
        trades: Sequence[TradeType],
        strategy_version: str = "1.0.0",
        run_id: str = "analysis_001",
    ) -> PerformanceMetrics:
        """Calculate overall performance metrics for a sequence of trades."""
        return calculate_performance_metrics(trades, initial_equity=self.initial_equity)

    def analyze_backtest(self, result: BacktestResult, run_id: str = "backtest_run") -> PerformanceMetrics:
        """Calculate performance metrics from a BacktestResult."""
        return self.analyze_trades(
            result.trades,
            strategy_version=result.strategy_version,
            run_id=run_id,
        )

    def analyze_journal(
        self,
        journal: TradingJournal,
        run_id: Optional[str] = None,
        strategy_version: str = "1.0.0",
    ) -> PerformanceMetrics:
        """Calculate performance metrics from journal TradeRecord entries."""
        trades = journal.get_trades(run_id=run_id)
        return self.analyze_trades(
            trades,
            strategy_version=strategy_version,
            run_id=run_id or "journal_run",
        )

    def analyze_conditions(
        self,
        trades: Sequence[TradeType],
        strategy_version: str = "1.0.0",
        run_id: str = "analysis_001",
    ) -> Dict[str, List[ConditionSlice]]:
        """Slice trades across available factual dimensions.

        Dimensions analyzed:
        1. Direction: LONG vs SHORT
        2. Exit Reason: TP_HIT, SL_HIT, END_OF_DATA
        3. Day of Week: Monday through Sunday (entry timestamp)
        4. Holding Time Bucket: < 6h, 6-24h, 24-72h, > 72h
        5. Stop Distance: tight (< 500 pts), medium (500-1500 pts), wide (> 1500 pts)

        Returns:
            Dictionary mapping dimension name to list of ConditionSlice results.
        """
        slices: Dict[str, List[ConditionSlice]] = defaultdict(list)
        if not trades:
            return slices

        # 1. Direction Slices
        for direction in ["LONG", "SHORT"]:
            subset = [t for t in trades if t.direction == direction]
            slices["direction"].append(
                self._build_slice(
                    condition_name="direction",
                    condition_value=direction,
                    subset=subset,
                    strategy_version=strategy_version,
                    run_id=run_id,
                )
            )

        # 2. Exit Reason Slices
        reasons = sorted(list({t.exit_reason for t in trades}))
        for reason in reasons:
            subset = [t for t in trades if t.exit_reason == reason]
            slices["exit_reason"].append(
                self._build_slice(
                    condition_name="exit_reason",
                    condition_value=reason,
                    subset=subset,
                    strategy_version=strategy_version,
                    run_id=run_id,
                )
            )

        # 3. Day of Week Slices
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for day_idx, day_name in enumerate(day_names):
            subset = [t for t in trades if t.entry_timestamp.weekday() == day_idx]
            if subset:
                slices["day_of_week"].append(
                    self._build_slice(
                        condition_name="day_of_week",
                        condition_value=day_name,
                        subset=subset,
                        strategy_version=strategy_version,
                        run_id=run_id,
                    )
                )

        # 4. Holding Duration Slices
        duration_buckets = {
            "< 6h": lambda dur_h: dur_h < 6.0,
            "6h - 24h": lambda dur_h: 6.0 <= dur_h < 24.0,
            "24h - 72h": lambda dur_h: 24.0 <= dur_h < 72.0,
            "> 72h": lambda dur_h: dur_h >= 72.0,
        }
        for b_name, b_fn in duration_buckets.items():
            subset = [
                t
                for t in trades
                if b_fn((t.exit_timestamp - t.entry_timestamp).total_seconds() / 3600.0)
            ]
            if subset:
                slices["holding_duration"].append(
                    self._build_slice(
                        condition_name="holding_duration",
                        condition_value=b_name,
                        subset=subset,
                        strategy_version=strategy_version,
                        run_id=run_id,
                    )
                )

        # 5. Stop Distance Slices
        stop_dist_buckets = {
            "tight (< 500)": lambda dist: dist < 500.0,
            "medium (500 - 1500)": lambda dist: 500.0 <= dist < 1500.0,
            "wide (> 1500)": lambda dist: dist >= 1500.0,
        }
        for b_name, b_fn in stop_dist_buckets.items():
            subset = [t for t in trades if b_fn(abs(t.entry_price - t.stop_price))]
            if subset:
                slices["stop_distance"].append(
                    self._build_slice(
                        condition_name="stop_distance",
                        condition_value=b_name,
                        subset=subset,
                        strategy_version=strategy_version,
                        run_id=run_id,
                    )
                )

        return dict(slices)

    def _build_slice(
        self,
        condition_name: str,
        condition_value: str,
        subset: List[TradeType],
        strategy_version: str,
        run_id: str,
    ) -> ConditionSlice:
        metrics = calculate_performance_metrics(subset, initial_equity=self.initial_equity)
        data_start = min((t.entry_timestamp for t in subset), default=None)
        data_end = max((t.exit_timestamp for t in subset), default=None)

        return ConditionSlice(
            condition_name=condition_name,
            condition_value=condition_value,
            sample_size=len(subset),
            metrics=metrics,
            data_start=data_start,
            data_end=data_end,
            strategy_version=strategy_version,
            run_id=run_id,
        )
