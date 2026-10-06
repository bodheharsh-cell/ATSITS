"""Deterministic tests for Experimental EMA20/EMA30 + 3R Strategy."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.models.backtest import BacktestConfig, CostModel
from atsits.models.market_data import Candle
from atsits.strategies.ema_pullback import EMAPullbackStrategy
from atsits.strategies.experimental_ema import EMAExperimentalStrategy


def _create_mock_candle(
    index: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> Candle:
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    ts = base_time + timedelta(hours=index)
    return Candle(
        timestamp=ts,
        symbol=symbol,
        timeframe=timeframe,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=100.0,
    )


# ----------------------------------------------------------------------
# 1. Indicator Period Tests (EMA20 and EMA30)
# ----------------------------------------------------------------------
def test_experimental_strategy_indicator_periods():
    """Confirm EMA20/30 indicator periods are configured."""
    strat = EMAExperimentalStrategy()
    assert strat.fast_period == 20
    assert strat.slow_period == 30
    assert strat.take_profit_rr == 3.0
    assert strat.fast_ema.period == 20
    assert strat.slow_ema.period == 30
    assert strat.VERSION == "EMA_Pullback_EMA20_30_3R"


# ----------------------------------------------------------------------
# 2. TP is exactly 3R and SL remains unchanged
# ----------------------------------------------------------------------
def test_experimental_tp_is_3r_and_sl_unchanged():
    """Confirm target is entry +/- 3.0 * (entry - stop) and SL is at pullback extreme."""
    strat = EMAExperimentalStrategy()
    cfg = BacktestConfig(initial_equity=10000.0, cost_model=CostModel(slippage_points=0.0, commission_rate=0.0))
    engine = BacktestEngine(strategy=strat, config=cfg)

    # Synthetic candles to generate a warmup and clean LONG setup
    candles = []
    # Warmup 35 bars steadily rising
    price = 100.0
    for i in range(35):
        price += 1.0
        candles.append(_create_mock_candle(i, price - 0.5, price + 0.5, price - 0.5, price))

    # Pullback bar: dips below EMA20
    # Let EMA20 be around 130
    pullback_low = 125.0
    pullback_high = 136.0
    candles.append(_create_mock_candle(35, 134.0, pullback_high, pullback_low, 133.0))

    # Confirmation bar: Close > Pullback High and Close > EMA20
    conf_close = 138.0
    candles.append(_create_mock_candle(36, 133.0, 139.0, 132.0, conf_close))

    # Entry bar: Opens at 138.0
    entry_open = 138.0
    candles.append(_create_mock_candle(37, entry_open, 140.0, 137.0, 139.0))

    # Exit bar: Hits 3R target
    risk_per_unit = entry_open - pullback_low  # 138.0 - 125.0 = 13.0
    expected_target = entry_open + (3.0 * risk_per_unit)  # 138.0 + 39.0 = 177.0
    candles.append(_create_mock_candle(38, 139.0, 180.0, 138.0, 178.0))

    result = engine.run(candles)
    assert len(result.trades) >= 1
    trade = result.trades[0]

    assert trade.direction == "LONG"
    assert trade.entry_price == entry_open
    assert trade.stop_price == pullback_low
    assert pytest.approx(trade.target_price) == expected_target
    assert trade.exit_reason == "TP_HIT"
    assert pytest.approx(trade.r_multiple, rel=1e-3) == 3.0


# ----------------------------------------------------------------------
# 3. Position sizing remains based on configured 1% risk
# ----------------------------------------------------------------------
def test_position_sizing_configured_risk():
    """Confirm position sizing = (equity * risk_pct) / abs(entry - stop)."""
    strat = EMAExperimentalStrategy()
    cfg = BacktestConfig(initial_equity=10000.0, risk_pct=0.01, cost_model=CostModel(slippage_points=0.0, commission_rate=0.0))
    engine = BacktestEngine(strategy=strat, config=cfg)

    candles = []
    price = 100.0
    for i in range(35):
        price += 1.0
        candles.append(_create_mock_candle(i, price - 0.5, price + 0.5, price - 0.5, price))

    pullback_low = 125.0
    candles.append(_create_mock_candle(35, 134.0, 136.0, pullback_low, 133.0))
    candles.append(_create_mock_candle(36, 133.0, 139.0, 132.0, 138.0))
    candles.append(_create_mock_candle(37, 138.0, 140.0, 137.0, 139.0))
    candles.append(_create_mock_candle(38, 139.0, 180.0, 138.0, 178.0))

    result = engine.run(candles)
    trade = result.trades[0]
    expected_risk_amount = 10000.0 * 0.01  # $100
    expected_qty = expected_risk_amount / (138.0 - 125.0)

    assert pytest.approx(trade.risk_amount) == expected_risk_amount
    assert pytest.approx(trade.quantity) == expected_qty


# ----------------------------------------------------------------------
# 4. No Lookahead & Completed Candle Invariant
# ----------------------------------------------------------------------
def test_no_lookahead_execution():
    """Confirm decisions depend strictly on completed candles and execute at next bar open."""
    strat = EMAExperimentalStrategy()
    cfg = BacktestConfig(initial_equity=10000.0, cost_model=CostModel())
    engine = BacktestEngine(strategy=strat, config=cfg)

    data_path = Path("data/btcusdt_1h.csv") if Path("data/btcusdt_1h.csv").exists() else Path("data/raw/BTCUSDT_1h.csv")
    if not data_path.exists():
        pytest.skip("Dataset not available")

    candles = load_candles_from_csv(data_path)
    result = engine.run(candles)

    for trade in result.trades:
        # Chronological strictness: Pullback < Confirmation < Entry <= Exit
        assert trade.pullback_timestamp < trade.confirmation_timestamp
        assert trade.confirmation_timestamp < trade.entry_timestamp
        assert trade.entry_timestamp <= trade.exit_timestamp


# ----------------------------------------------------------------------
# 5. Locked Baseline EMA20/50 + 2R Remains Unchanged
# ----------------------------------------------------------------------
def test_locked_baseline_exact_preservation():
    """Confirm locked EMA20/50 + 2R strategy reproduces exact baseline metrics."""
    locked_strat = EMAPullbackStrategy()
    assert locked_strat.fast_period == 20
    assert locked_strat.slow_period == 50
    assert locked_strat.take_profit_rr == 2.0

    data_path = Path("data/btcusdt_1h.csv") if Path("data/btcusdt_1h.csv").exists() else Path("data/raw/BTCUSDT_1h.csv")
    if not data_path.exists():
        pytest.skip("Dataset not available")

    candles = load_candles_from_csv(data_path)
    cfg = BacktestConfig(initial_equity=10000.0, cost_model=CostModel())
    engine = BacktestEngine(strategy=locked_strat, config=cfg)
    result = engine.run(candles)

    assert result.number_of_trades == 201
    assert result.winning_trades == 67
    assert result.losing_trades == 134
    assert pytest.approx(result.win_rate, abs=1e-4) == 0.3333333333333333
    assert pytest.approx(result.total_net_pnl, abs=0.01) == -306.09
    assert pytest.approx(result.profit_factor, abs=0.01) == 0.98
    assert pytest.approx(result.max_drawdown, abs=0.01) == 1448.11


# ----------------------------------------------------------------------
# 6. Determinism & Idempotency: Run Twice Gives Identical Results
# ----------------------------------------------------------------------
def test_experimental_strategy_deterministic_repeatability():
    """Confirm running experimental strategy twice on historical data gives bit-for-bit identical results."""
    data_path = Path("data/btcusdt_1h.csv") if Path("data/btcusdt_1h.csv").exists() else Path("data/raw/BTCUSDT_1h.csv")
    if not data_path.exists():
        pytest.skip("Dataset not available")

    candles = load_candles_from_csv(data_path)
    cfg = BacktestConfig(initial_equity=10000.0, cost_model=CostModel())

    engine1 = BacktestEngine(strategy=EMAExperimentalStrategy(), config=cfg)
    res1 = engine1.run(candles, run_id="run_1")

    engine2 = BacktestEngine(strategy=EMAExperimentalStrategy(), config=cfg)
    res2 = engine2.run(candles, run_id="run_2")

    assert res1.number_of_trades == res2.number_of_trades == 200
    assert res1.winning_trades == res2.winning_trades == 55
    assert res1.losing_trades == res2.losing_trades == 145
    assert res1.total_net_pnl == res2.total_net_pnl
    assert res1.gross_profit == res2.gross_profit
    assert res1.gross_loss == res2.gross_loss
    assert res1.max_drawdown == res2.max_drawdown

    for t1, t2 in zip(res1.trades, res2.trades):
        assert t1.direction == t2.direction
        assert t1.entry_timestamp == t2.entry_timestamp
        assert t1.exit_timestamp == t2.exit_timestamp
        assert t1.entry_price == t2.entry_price
        assert t1.stop_price == t2.stop_price
        assert t1.target_price == t2.target_price
        assert t1.net_pnl == t2.net_pnl
        assert t1.exit_reason == t2.exit_reason
