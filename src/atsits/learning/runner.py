"""Deterministic Experiment Runner executing baseline vs candidate comparisons under chronological IS/OOS splits."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.learning.metrics import calculate_performance_metrics
from atsits.learning.models import (
    ExperimentResult,
    ExperimentSpec,
    ExperimentStatus,
    MetricDifference,
    PerformanceMetrics,
)
from atsits.models.backtest import BacktestConfig
from atsits.models.market_data import Candle
from atsits.strategies.ema_pullback import EMAPullbackStrategy

logger = logging.getLogger(__name__)

# Locked baseline parameters for EMA_Pullback_v1.0
BASELINE_PARAMS: Dict[str, Any] = {
    "fast_period": 20,
    "slow_period": 50,
}


def validate_one_variable_change(candidate_params: Dict[str, Any]) -> Tuple[str, Any, Any]:
    """Ensure candidate configuration modifies exactly one controlled parameter relative to baseline.

    Returns:
        Tuple of (param_name, baseline_val, candidate_val).

    Raises:
        ValueError: If 0 or >1 parameters differ from baseline.
    """
    diffs = []
    for k, v in candidate_params.items():
        if k not in BASELINE_PARAMS:
            raise ValueError(f"Unknown parameter '{k}' in candidate configuration. Allowed: {list(BASELINE_PARAMS.keys())}")
        if BASELINE_PARAMS[k] != v:
            diffs.append((k, BASELINE_PARAMS[k], v))

    if len(diffs) == 0:
        raise ValueError("Candidate configuration has 0 differences from baseline. Must propose exactly one variable change.")
    if len(diffs) > 1:
        param_list = [f"{k}: {b}->{c}" for k, b, c in diffs]
        raise ValueError(f"One-variable rule violation: multiple parameter changes detected: {param_list}")

    return diffs[0]


class ExperimentRunner:
    """Runs controlled, deterministic experiments comparing baseline vs candidate strategy."""

    def __init__(self, initial_equity: float = 10000.0):
        self.initial_equity: float = float(initial_equity)

    def run_experiment(
        self,
        spec: ExperimentSpec,
        candles: Optional[List[Candle]] = None,
    ) -> ExperimentResult:
        """Execute experiment spec against dataset.

        Args:
            spec: Experiment specification.
            candles: Optional pre-loaded candles sequence. If None, loaded from spec.data_path.

        Returns:
            ExperimentResult detailing baseline, candidate, IS, OOS metrics, and diffs.
        """
        # 1. Enforce single variable change
        validate_one_variable_change(spec.candidate_params)

        # 2. Load and validate chronological dataset
        if candles is None:
            candles = load_candles_from_csv(spec.data_path)

        total_candles = len(candles)
        if total_candles < 110:
            raise ValueError(f"Dataset has {total_candles} candles; minimum 110 required for 2x55 indicator warmup.")

        # 3. Chronological In-Sample / Out-of-Sample split (NEVER SHUFFLE)
        split_idx = int(total_candles * spec.is_ratio)
        if split_idx < 55 or (total_candles - split_idx) < 55:
            raise ValueError(
                f"Split ratio {spec.is_ratio} yields IS={split_idx}, OOS={total_candles - split_idx}; "
                f"both segments require at least 55 bars for indicator warmup."
            )

        is_candles = candles[:split_idx]
        oos_candles = candles[split_idx:]

        # Verify strict temporal ordering
        if is_candles[-1].timestamp >= oos_candles[0].timestamp:
            raise ValueError(
                f"Temporal boundary error: IS end {is_candles[-1].timestamp.isoformat()} >= "
                f"OOS start {oos_candles[0].timestamp.isoformat()}"
            )

        is_start = is_candles[0].timestamp
        is_end = is_candles[-1].timestamp
        oos_start = oos_candles[0].timestamp
        oos_end = oos_candles[-1].timestamp

        # 4. Configure engines
        config = BacktestConfig(
            initial_equity=spec.initial_equity,
            cost_model=spec.cost_model,
        )

        base_strategy_is = EMAPullbackStrategy(fast_period=20, slow_period=50)
        base_strategy_oos = EMAPullbackStrategy(fast_period=20, slow_period=50)
        base_strategy_full = EMAPullbackStrategy(fast_period=20, slow_period=50)

        cand_strategy_is = EMAPullbackStrategy(**spec.candidate_params)
        cand_strategy_oos = EMAPullbackStrategy(**spec.candidate_params)
        cand_strategy_full = EMAPullbackStrategy(**spec.candidate_params)

        # 5. Execute backtests under identical conditions
        engine_base_is = BacktestEngine(strategy=base_strategy_is, config=config)
        engine_base_oos = BacktestEngine(strategy=base_strategy_oos, config=config)
        engine_base_full = BacktestEngine(strategy=base_strategy_full, config=config)

        engine_cand_is = BacktestEngine(strategy=cand_strategy_is, config=config)
        engine_cand_oos = BacktestEngine(strategy=cand_strategy_oos, config=config)
        engine_cand_full = BacktestEngine(strategy=cand_strategy_full, config=config)

        is_base_res = engine_base_is.run(is_candles, run_id=f"{spec.experiment_id}_is_base")
        is_cand_res = engine_cand_is.run(is_candles, run_id=f"{spec.experiment_id}_is_cand")

        oos_base_res = engine_base_oos.run(oos_candles, run_id=f"{spec.experiment_id}_oos_base")
        oos_cand_res = engine_cand_oos.run(oos_candles, run_id=f"{spec.experiment_id}_oos_cand")

        full_base_res = engine_base_full.run(candles, run_id=f"{spec.experiment_id}_full_base")
        full_cand_res = engine_cand_full.run(candles, run_id=f"{spec.experiment_id}_full_cand")

        # 6. Calculate performance metrics
        is_base_metrics = calculate_performance_metrics(is_base_res.trades, initial_equity=spec.initial_equity)
        is_cand_metrics = calculate_performance_metrics(is_cand_res.trades, initial_equity=spec.initial_equity)

        oos_base_metrics = calculate_performance_metrics(oos_base_res.trades, initial_equity=spec.initial_equity)
        oos_cand_metrics = calculate_performance_metrics(oos_cand_res.trades, initial_equity=spec.initial_equity)

        full_base_metrics = calculate_performance_metrics(full_base_res.trades, initial_equity=spec.initial_equity)
        full_cand_metrics = calculate_performance_metrics(full_cand_res.trades, initial_equity=spec.initial_equity)

        # 7. Compute Metric Differences on Out-of-Sample evaluation
        differences = self._compute_differences(oos_base_metrics, oos_cand_metrics)

        # 8. Evaluate neutral validation
        validation_passed, validation_summary = self._evaluate_validation(
            is_base_metrics, is_cand_metrics, oos_base_metrics, oos_cand_metrics
        )

        return ExperimentResult(
            experiment_id=spec.experiment_id,
            hypothesis_id=spec.hypothesis_id,
            baseline_strategy_version=spec.baseline_strategy_version,
            candidate_strategy_version=spec.candidate_strategy_version,
            candidate_params=spec.candidate_params,
            dataset_id=spec.dataset_id,
            total_candles=total_candles,
            is_candle_count=len(is_candles),
            oos_candle_count=len(oos_candles),
            is_start=is_start,
            is_end=is_end,
            oos_start=oos_start,
            oos_end=oos_end,
            is_baseline_metrics=is_base_metrics,
            is_candidate_metrics=is_cand_metrics,
            oos_baseline_metrics=oos_base_metrics,
            oos_candidate_metrics=oos_cand_metrics,
            full_baseline_metrics=full_base_metrics,
            full_candidate_metrics=full_cand_metrics,
            differences=differences,
            validation_passed=validation_passed,
            validation_summary=validation_summary,
            created_at=datetime.now(timezone.utc),
            status=ExperimentStatus.COMPLETED,
        )

    def _compute_differences(
        self,
        base: PerformanceMetrics,
        cand: PerformanceMetrics,
    ) -> Dict[str, MetricDifference]:
        """Compute absolute and relative differences for key metrics."""
        diffs: Dict[str, MetricDifference] = {}
        tracked_attrs = [
            ("total_trades", False),
            ("win_rate", False),
            ("net_pnl", True),
            ("profit_factor", True),
            ("expectancy_r", False),
            ("max_drawdown", True),
            ("max_drawdown_pct", False),
            ("average_trade_pnl", True),
        ]

        for attr, allow_rel in tracked_attrs:
            b_val = float(getattr(base, attr))
            c_val = float(getattr(cand, attr))
            abs_diff = c_val - b_val

            rel_diff = None
            if allow_rel and b_val != 0.0:
                rel_diff = (abs_diff / abs(b_val)) * 100.0

            diffs[attr] = MetricDifference(
                metric_name=attr,
                baseline_value=b_val,
                candidate_value=c_val,
                absolute_diff=abs_diff,
                relative_diff_pct=rel_diff,
            )

        return diffs

    def _evaluate_validation(
        self,
        is_base: PerformanceMetrics,
        is_cand: PerformanceMetrics,
        oos_base: PerformanceMetrics,
        oos_cand: PerformanceMetrics,
    ) -> Tuple[bool, str]:
        """Neutral factual validation checks without autonomous promotion."""
        conditions = []
        # Check sample sizes
        if oos_cand.sample_size < 5:
            return False, f"Validation not met: Out-of-sample sample size ({oos_cand.sample_size}) too small (< 5 trades)."

        # Check whether candidate outperformed baseline in OOS on net PnL and Expectancy
        oos_pnl_gain = oos_cand.net_pnl > oos_base.net_pnl
        oos_exp_gain = oos_cand.expectancy_r > oos_base.expectancy_r
        is_pnl_gain = is_cand.net_pnl > is_base.net_pnl

        summary_parts = [
            f"IS Net PnL: Candidate={is_cand.net_pnl:.2f} vs Baseline={is_base.net_pnl:.2f}",
            f"OOS Net PnL: Candidate={oos_cand.net_pnl:.2f} vs Baseline={oos_base.net_pnl:.2f}",
            f"OOS Expectancy R: Candidate={oos_cand.expectancy_r:.3f}R vs Baseline={oos_base.expectancy_r:.3f}R",
            f"OOS Sample Size: {oos_cand.sample_size} trades",
        ]

        passed = oos_pnl_gain and oos_exp_gain
        summary = " | ".join(summary_parts)
        return passed, summary
