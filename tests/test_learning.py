"""Comprehensive test suite for Phase 5 Learning + Experiment Engine."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from atsits.learning.analyzer import PerformanceAnalyzer
from atsits.learning.hypotheses import HypothesisRegistry
from atsits.learning.metrics import calculate_performance_metrics
from atsits.learning.models import (
    ConditionSlice,
    ExperimentResult,
    ExperimentSpec,
    ExperimentStatus,
    Hypothesis,
    HypothesisStatus,
    PerformanceMetrics,
)
from atsits.learning.registry import ExperimentRegistry
from atsits.learning.reports import (
    format_metrics_table,
    generate_condition_analysis_report,
    generate_experiment_markdown_report,
)
from atsits.learning.runner import (
    BASELINE_PARAMS,
    ExperimentRunner,
    validate_one_variable_change,
)
from atsits.models.backtest import BacktestConfig, SimulatedTrade
from atsits.models.market_data import Candle
from atsits.strategies.ema_pullback import EMAPullbackStrategy


def _make_sim_trade(
    trade_id: str,
    direction: str,
    entry_ts: datetime,
    exit_ts: datetime,
    entry_price: float,
    exit_price: float,
    stop_price: float,
    target_price: float,
    net_pnl: float,
    r_multiple: float,
    exit_reason: str = "TP_HIT",
    quantity: float = 0.1,
    risk_amount: float = 100.0,
) -> SimulatedTrade:
    return SimulatedTrade(
        trade_id=trade_id,
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction=direction,
        pullback_timestamp=entry_ts - timedelta(hours=2),
        confirmation_timestamp=entry_ts - timedelta(hours=1),
        entry_timestamp=entry_ts,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        quantity=quantity,
        risk_amount=risk_amount,
        exit_timestamp=exit_ts,
        exit_price=exit_price,
        exit_reason=exit_reason,
        gross_pnl=net_pnl,
        fees=0.0,
        slippage=0.0,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
    )


def _make_candle_series(n_bars: int = 150, start_price: float = 40000.0) -> list:
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = []
    p = start_price
    for i in range(n_bars):
        # gentle oscillation
        delta = 20.0 if (i % 4 < 2) else -15.0
        p += delta
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe="1h",
                timestamp=t0 + timedelta(hours=i),
                open=p - 5.0,
                high=p + 15.0,
                low=p - 10.0,
                close=p,
                volume=50.0,
            )
        )
    return candles


# =====================================================================
# Test A: Metric Calculations & Formulas
# =====================================================================
def test_a_metric_calculations_basic():
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        _make_sim_trade("t1", "LONG", t0, t0 + timedelta(hours=2), 50000, 52000, 49000, 52000, 200.0, 2.0, "TP_HIT"),
        _make_sim_trade("t2", "SHORT", t0 + timedelta(hours=3), t0 + timedelta(hours=5), 52000, 50000, 53000, 50000, 200.0, 2.0, "TP_HIT"),
        _make_sim_trade("t3", "LONG", t0 + timedelta(hours=6), t0 + timedelta(hours=8), 51000, 50000, 50000, 53000, -100.0, -1.0, "SL_HIT"),
    ]

    metrics = calculate_performance_metrics(trades, initial_equity=10000.0)
    assert metrics.total_trades == 3
    assert metrics.sample_size == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert pytest.approx(metrics.win_rate, 0.001) == 2 / 3
    assert metrics.gross_profit == 400.0
    assert metrics.gross_loss == 100.0
    assert metrics.net_pnl == 300.0
    assert metrics.profit_factor == 4.0
    assert pytest.approx(metrics.average_trade_pnl, 0.001) == 100.0
    assert metrics.average_winner == 200.0
    assert metrics.average_loser == -100.0
    assert metrics.sl_exits == 1
    assert metrics.tp_exits == 2
    assert metrics.eod_exits == 0
    assert metrics.total_r == 3.0
    assert metrics.average_r == 1.0


# =====================================================================
# Test B & C: Long / Short & Win / Loss Breakdown
# =====================================================================
def test_b_c_long_short_grouping():
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        _make_sim_trade("t1", "LONG", t0, t0 + timedelta(hours=1), 50000, 52000, 49000, 52000, 200.0, 2.0),
        _make_sim_trade("t2", "LONG", t0 + timedelta(hours=2), t0 + timedelta(hours=3), 50000, 49000, 49000, 52000, -100.0, -1.0),
        _make_sim_trade("t3", "SHORT", t0 + timedelta(hours=4), t0 + timedelta(hours=5), 50000, 51000, 51000, 48000, -100.0, -1.0),
    ]

    metrics = calculate_performance_metrics(trades)
    assert metrics.long_trades == 2
    assert metrics.short_trades == 1
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 2


# =====================================================================
# Test D: Profit Factor Edge Cases
# =====================================================================
def test_d_profit_factor_edge_cases():
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    # All winners -> inf
    win_trades = [
        _make_sim_trade("t1", "LONG", t0, t0 + timedelta(hours=1), 50000, 52000, 49000, 52000, 200.0, 2.0),
    ]
    m_win = calculate_performance_metrics(win_trades)
    assert m_win.profit_factor == float("inf")

    # All losers -> 0.0
    loss_trades = [
        _make_sim_trade("t2", "LONG", t0, t0 + timedelta(hours=1), 50000, 49000, 49000, 52000, -100.0, -1.0),
    ]
    m_loss = calculate_performance_metrics(loss_trades)
    assert m_loss.profit_factor == 0.0


# =====================================================================
# Test E & F: Drawdown & R Metrics
# =====================================================================
def test_e_f_drawdown_and_r_metrics():
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        _make_sim_trade("t1", "LONG", t0, t0 + timedelta(hours=1), 50000, 52000, 49000, 52000, 200.0, 2.0),   # eq: 10200
        _make_sim_trade("t2", "LONG", t0 + timedelta(hours=2), t0 + timedelta(hours=3), 50000, 49000, 49000, 52000, -100.0, -1.0), # eq: 10100 (dd: 100)
        _make_sim_trade("t3", "LONG", t0 + timedelta(hours=4), t0 + timedelta(hours=5), 50000, 49000, 49000, 52000, -100.0, -1.0), # eq: 10000 (dd: 200)
        _make_sim_trade("t4", "LONG", t0 + timedelta(hours=6), t0 + timedelta(hours=7), 50000, 52000, 49000, 52000, 200.0, 2.0),   # eq: 10200 (dd: 0)
    ]

    metrics = calculate_performance_metrics(trades, initial_equity=10000.0)
    assert metrics.max_drawdown == 200.0
    assert pytest.approx(metrics.max_drawdown_pct, 0.0001) == 200.0 / 10200.0

    # Expectancy in R: WinRate(0.5)*2.0 - LossRate(0.5)*1.0 = 1.0 - 0.5 = 0.5R
    assert pytest.approx(metrics.expectancy_r, 0.001) == 0.5


# =====================================================================
# Test G: Condition Analysis Slices
# =====================================================================
def test_g_condition_analysis():
    t0 = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)  # Monday
    trades = [
        _make_sim_trade("t1", "LONG", t0, t0 + timedelta(hours=5), 50000, 52000, 49000, 52000, 200.0, 2.0, "TP_HIT"),
        _make_sim_trade("t2", "SHORT", t0 + timedelta(days=1), t0 + timedelta(days=1, hours=30), 52000, 53000, 53000, 50000, -100.0, -1.0, "SL_HIT"),
    ]

    analyzer = PerformanceAnalyzer()
    slices = analyzer.analyze_conditions(trades)

    assert "direction" in slices
    assert "exit_reason" in slices
    assert "day_of_week" in slices
    assert "holding_duration" in slices
    assert "stop_distance" in slices

    long_slice = [s for s in slices["direction"] if s.condition_value == "LONG"][0]
    assert long_slice.sample_size == 1
    assert long_slice.metrics.net_pnl == 200.0


# =====================================================================
# Test H: Hypothesis Registry Persistence & Validation
# =====================================================================
def test_h_hypothesis_registry(tmp_path: Path):
    hypo_file = tmp_path / "hypotheses.jsonl"
    reg = HypothesisRegistry(file_path=hypo_file)

    h1 = Hypothesis(
        hypothesis_id="HYP-001",
        created_at=datetime.now(timezone.utc),
        source="human",
        description="Test fast EMA 21",
        baseline_strategy_version="1.0.0",
        proposed_change="fast_period: 20 -> 21",
        rationale="Slightly smoother trend tracking",
        expected_effect="Reduced whipsaw on 1H",
        status=HypothesisStatus.PROPOSED,
        created_by="analyst",
    )

    reg.register(h1)
    assert reg.get("HYP-001") is not None

    # Cannot re-register same ID
    with pytest.raises(ValueError):
        reg.register(h1)

    # Update status
    updated = reg.update_status("HYP-001", HypothesisStatus.TESTING)
    assert updated.status == HypothesisStatus.TESTING

    # Re-instantiate from disk and verify persistence
    reg2 = HypothesisRegistry(file_path=hypo_file)
    assert reg2.get("HYP-001").status == HypothesisStatus.TESTING


# =====================================================================
# Test I, J, K: Single Variable Enforcement & Baseline Comparison
# =====================================================================
def test_i_j_k_single_variable_and_baseline_comparison(tmp_path: Path):
    # 1. Valid single variable change
    diff = validate_one_variable_change({"fast_period": 21, "slow_period": 50})
    assert diff == ("fast_period", 20, 21)

    # 2. Reject zero changes
    with pytest.raises(ValueError):
        validate_one_variable_change({"fast_period": 20, "slow_period": 50})

    # 3. Reject multiple changes
    with pytest.raises(ValueError, match="One-variable rule violation"):
        validate_one_variable_change({"fast_period": 21, "slow_period": 55})

    # 4. Reject unknown parameter
    with pytest.raises(ValueError, match="Unknown parameter"):
        validate_one_variable_change({"unknown_param": 10})


# =====================================================================
# Test L, M, N: Chronological IS/OOS Split & Leakage Prevention
# =====================================================================
def test_l_m_n_is_oos_chronological_splitting(tmp_path: Path):
    candles = _make_candle_series(n_bars=200)

    spec = ExperimentSpec(
        experiment_id="EXP-001",
        hypothesis_id="HYP-001",
        baseline_strategy_version="1.0.0",
        candidate_strategy_version="1.0.1-cand",
        candidate_params={"fast_period": 21, "slow_period": 50},
        dataset_id="test_btcusdt",
        data_path="dummy.csv",
        is_ratio=0.7,
        created_at=datetime.now(timezone.utc),
    )

    runner = ExperimentRunner()
    res = runner.run_experiment(spec, candles=candles)

    assert res.total_candles == 200
    assert res.is_candle_count == 140
    assert res.oos_candle_count == 60
    assert res.is_end < res.oos_start
    assert res.status == ExperimentStatus.COMPLETED


# =====================================================================
# Test O, P: Experiment Reproducibility & Registry Persistence
# =====================================================================
def test_o_p_experiment_reproducibility_and_registry(tmp_path: Path):
    candles = _make_candle_series(n_bars=200)

    spec1 = ExperimentSpec(
        experiment_id="EXP-REP-1",
        hypothesis_id="HYP-001",
        baseline_strategy_version="1.0.0",
        candidate_strategy_version="1.0.1-cand",
        candidate_params={"fast_period": 21, "slow_period": 50},
        dataset_id="test_btcusdt",
        data_path="dummy.csv",
        is_ratio=0.7,
        created_at=datetime.now(timezone.utc),
    )

    runner = ExperimentRunner()
    res1 = runner.run_experiment(spec1, candles=candles)
    res2 = runner.run_experiment(spec1, candles=candles)

    # Bit-for-bit identical metrics
    assert res1.is_baseline_metrics == res2.is_baseline_metrics
    assert res1.oos_candidate_metrics == res2.oos_candidate_metrics
    assert res1.differences == res2.differences

    # Registry persistence
    reg_dir = tmp_path / "experiments"
    registry = ExperimentRegistry(base_dir=reg_dir)
    registry.record(res1)

    assert registry.get("EXP-REP-1") is not None
    # Duplicate ID rejected
    with pytest.raises(ValueError):
        registry.record(res1)

    # Re-load registry from disk
    registry2 = ExperimentRegistry(base_dir=reg_dir)
    loaded = registry2.get("EXP-REP-1")
    assert loaded is not None
    assert loaded.experiment_id == "EXP-REP-1"


# =====================================================================
# Test Q, R, S: Version Immutability, No Auto-Promotion, No Code Mutation
# =====================================================================
def test_q_r_s_immutability_and_promotion_boundary():
    baseline = EMAPullbackStrategy()
    assert baseline.VERSION == "1.0.0"
    assert baseline.NAME == "EMA_Pullback_v1.0"
    assert BASELINE_PARAMS == {"fast_period": 20, "slow_period": 50}

    # Verify no auto-promote method exists in package
    import atsits.learning as learning
    assert not hasattr(learning, "promote_best")
    assert not hasattr(learning, "auto_select_winner")
    assert not hasattr(learning, "deploy_best_strategy")


# =====================================================================
# Test T & U: Empty/Small Datasets & Invalid Configs
# =====================================================================
def test_t_u_empty_small_datasets_and_invalid_configs():
    # Empty trade metrics
    empty_metrics = calculate_performance_metrics([])
    assert empty_metrics.total_trades == 0
    assert empty_metrics.net_pnl == 0.0

    # Dataset too small for warmup
    small_candles = _make_candle_series(n_bars=60)
    spec = ExperimentSpec(
        experiment_id="EXP-SMALL",
        hypothesis_id="HYP-001",
        baseline_strategy_version="1.0.0",
        candidate_strategy_version="1.0.1-cand",
        candidate_params={"fast_period": 21, "slow_period": 50},
        dataset_id="test_small",
        data_path="dummy.csv",
        is_ratio=0.7,
        created_at=datetime.now(timezone.utc),
    )

    runner = ExperimentRunner()
    with pytest.raises(ValueError, match="minimum 110 required"):
        runner.run_experiment(spec, candles=small_candles)
