"""Unit and integration tests for BacktestEngine (Requirements 7-18, 20-24)."""

import pytest
from atsits.engine.backtester import BacktestEngine
from atsits.models.backtest import BacktestConfig, CostModel
from tests.conftest import make_candle, make_trending_candles


def build_base_uptrend_setup():
    """Helper to build 60 bars uptrend + pullback bar 60 + confirmation bar 61."""
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    engine = BacktestEngine()
    for c in candles:
        engine.strategy.on_candle(c, has_open_position=False)

    ema20_val = engine.strategy.fast_ema.value
    assert ema20_val is not None

    # Bar 60: Pullback (Low = 185.0 <= EMA20)
    pb = make_candle(60, open_p=210.0, high_p=212.0, low_p=185.0, close_p=205.0)
    # Bar 61: Confirmation (Close = 218.0 > High 212 and > EMA20)
    conf = make_candle(61, open_p=206.0, high_p=220.0, low_p=205.0, close_p=218.0)

    return candles + [pb, conf]


def build_base_downtrend_setup():
    """Helper to build 60 bars downtrend + pullback bar 60 + confirmation bar 61."""
    candles = make_trending_candles(60, start_price=500.0, step=-2.0)
    engine = BacktestEngine()
    for c in candles:
        engine.strategy.on_candle(c, has_open_position=False)

    ema20_val = engine.strategy.fast_ema.value
    assert ema20_val is not None

    # Bar 60: Pullback (High = 400.0 >= EMA20)
    pb = make_candle(60, open_p=380.0, high_p=400.0, low_p=375.0, close_p=378.0)
    # Bar 61: Confirmation (Close = 370.0 < Low 375 and < EMA20)
    conf = make_candle(61, open_p=377.0, high_p=378.0, low_p=365.0, close_p=370.0)

    return candles + [pb, conf]


def test_7_8_9_entry_sl_tp_calculation():
    """Requirements 7, 8, 9: Entry at next candle OPEN, SL = pullback Low, TP = 2R."""
    candles = build_base_uptrend_setup()
    # Bar 62: Entry candle with Open = 220.0
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=215.0, close_p=222.0)
    all_candles = candles + [bar_62]

    engine = BacktestEngine(config=BacktestConfig(initial_equity=10000.0, risk_pct=0.01))
    result = engine.run(all_candles)

    # Position entered at bar 62 and closed at END_OF_DATA at bar 62 close
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_timestamp == bar_62.timestamp
    assert trade.entry_price == 220.0  # Bar 62 Open
    assert trade.stop_price == 185.0   # Bar 60 Pullback Low
    # Risk per unit = 220.0 - 185.0 = 35.0
    # TP (2R) = 220.0 + (2 * 35.0) = 290.0
    assert trade.target_price == 290.0


def test_10_long_sl_hit():
    """Requirement 10: Long position exits on SL hit."""
    candles = build_base_uptrend_setup()
    # Bar 62: Entry at open 220.0
    bar_62 = make_candle(62, open_p=220.0, high_p=222.0, low_p=210.0, close_p=215.0)
    # Bar 63: Drops below SL (185.0), hitting Low = 180.0
    bar_63 = make_candle(63, open_p=215.0, high_p=216.0, low_p=180.0, close_p=182.0)
    all_candles = candles + [bar_62, bar_63]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "SL_HIT"
    assert trade.exit_price == 185.0
    assert trade.exit_timestamp == bar_63.timestamp
    assert trade.net_pnl < 0


def test_11_long_tp_hit():
    """Requirement 11: Long position exits on TP hit."""
    candles = build_base_uptrend_setup()
    # Bar 62: Entry at open 220.0, SL=185 (R=35), TP=290
    bar_62 = make_candle(62, open_p=220.0, high_p=230.0, low_p=218.0, close_p=228.0)
    # Bar 63: Rallies past TP (290.0), reaching High = 295.0
    bar_63 = make_candle(63, open_p=228.0, high_p=295.0, low_p=225.0, close_p=292.0)
    all_candles = candles + [bar_62, bar_63]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "TP_HIT"
    assert trade.exit_price == 290.0
    assert trade.exit_timestamp == bar_63.timestamp
    assert trade.net_pnl > 0
    assert pytest.approx(trade.r_multiple, 1e-4) == 2.0


def test_12_short_sl_hit():
    """Requirement 12: Short position exits on SL hit."""
    candles = build_base_downtrend_setup()
    # Pullback Low was 375, High was 400 (SL = 400.0)
    # Bar 62: Entry at open 368.0. Risk = 400 - 368 = 32. TP = 368 - 64 = 304.
    bar_62 = make_candle(62, open_p=368.0, high_p=372.0, low_p=365.0, close_p=369.0)
    # Bar 63: Price surges past SL (400.0) hitting High = 405.0
    bar_63 = make_candle(63, open_p=369.0, high_p=405.0, low_p=368.0, close_p=402.0)
    all_candles = candles + [bar_62, bar_63]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "SHORT"
    assert trade.exit_reason == "SL_HIT"
    assert trade.exit_price == 400.0
    assert trade.net_pnl < 0


def test_13_short_tp_hit():
    """Requirement 13: Short position exits on TP hit."""
    candles = build_base_downtrend_setup()
    # SL = 400.0, Bar 62 entry open = 368.0 -> R = 32 -> TP = 304.0
    bar_62 = make_candle(62, open_p=368.0, high_p=370.0, low_p=360.0, close_p=362.0)
    # Bar 63: Drops past TP (304.0) hitting Low = 300.0
    bar_63 = make_candle(63, open_p=362.0, high_p=363.0, low_p=300.0, close_p=302.0)
    all_candles = candles + [bar_62, bar_63]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "SHORT"
    assert trade.exit_reason == "TP_HIT"
    assert trade.exit_price == 304.0
    assert trade.net_pnl > 0
    assert pytest.approx(trade.r_multiple, 1e-4) == 2.0


def test_14_same_bar_sl_and_tp_precedence():
    """Requirement 14: If both SL and TP touched in same bar, SL happens first."""
    candles = build_base_uptrend_setup()
    # Entry at 220, SL=185, TP=290
    bar_62 = make_candle(62, open_p=220.0, high_p=222.0, low_p=218.0, close_p=220.0)
    # Bar 63 has extreme range touching both SL (180 <= 185) and TP (300 >= 290)
    bar_63 = make_candle(63, open_p=220.0, high_p=300.0, low_p=180.0, close_p=250.0)
    all_candles = candles + [bar_62, bar_63]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    # SL must take precedence
    assert trade.exit_reason == "SL_HIT"
    assert trade.exit_price == 185.0
    assert trade.net_pnl < 0


def test_15_invalid_entry_stop_on_wrong_side():
    """Requirement 15: If entry open price is beyond SL, reject setup."""
    candles = build_base_uptrend_setup()
    # SL is 185.0. Bar 62 gaps down below SL at Open = 180.0
    bar_62 = make_candle(62, open_p=180.0, high_p=184.0, low_p=175.0, close_p=182.0)
    all_candles = candles + [bar_62]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    # No trade created
    assert len(result.trades) == 0
    # Rejection recorded
    assert len(result.rejections) == 1
    assert result.rejections[0].reason == "INVALID_STOP_AT_OPEN"
    assert result.rejections[0].direction == "LONG"


def test_16_17_one_position_only_and_no_reversal():
    """Requirements 16, 17: Maximum one open position, no pyramiding, no reversal."""
    candles = build_base_uptrend_setup()
    # Bar 62: Enter long
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=222.0)
    # Bars 63-65: Price stays between SL and TP, and triggers another pullback+confirmation
    bar_63 = make_candle(63, open_p=222.0, high_p=225.0, low_p=200.0, close_p=221.0)
    bar_64 = make_candle(64, open_p=221.0, high_p=230.0, low_p=220.0, close_p=228.0)
    bar_65 = make_candle(65, open_p=228.0, high_p=232.0, low_p=225.0, close_p=230.0)
    all_candles = candles + [bar_62, bar_63, bar_64, bar_65]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    # Only 1 trade existed and was closed at END_OF_DATA
    assert len(result.trades) == 1
    assert result.trades[0].entry_timestamp == bar_62.timestamp


def test_18_end_of_data_handling():
    """Requirement 18: Position open at final candle is closed at final CLOSE with END_OF_DATA."""
    candles = build_base_uptrend_setup()
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=224.0)
    all_candles = candles + [bar_62]

    engine = BacktestEngine()
    result = engine.run(all_candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "END_OF_DATA"
    assert trade.exit_price == 224.0
    assert trade.exit_timestamp == bar_62.timestamp


def test_20_position_sizing_one_percent_risk():
    """Requirement 20: Position sizing matches risk_amount / abs(entry - stop)."""
    candles = build_base_uptrend_setup()
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=222.0)
    all_candles = candles + [bar_62]

    # Equity = 20,000, risk = 2% -> risk_amount = 400.0
    # Entry = 220.0, Stop = 185.0 -> Risk per unit = 35.0
    # Expected quantity = 400.0 / 35.0 = 11.4285714...
    engine = BacktestEngine(config=BacktestConfig(initial_equity=20000.0, risk_pct=0.02))
    result = engine.run(all_candles)

    trade = result.trades[0]
    assert trade.risk_amount == 400.0
    expected_qty = 400.0 / 35.0
    assert pytest.approx(trade.quantity, 1e-6) == expected_qty


def test_21_commission_cost_model():
    """Requirement 21: Commission rate is deducted from gross PnL."""
    candles = build_base_uptrend_setup()
    # Entry at 220, TP at 290 (Gross gain = 70/unit)
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=222.0)
    bar_63 = make_candle(63, open_p=222.0, high_p=295.0, low_p=220.0, close_p=292.0)
    all_candles = candles + [bar_62, bar_63]

    cost_model = CostModel(commission_rate=0.001)  # 0.1% per trade
    engine = BacktestEngine(config=BacktestConfig(cost_model=cost_model))
    result = engine.run(all_candles)

    trade = result.trades[0]
    entry_val = trade.entry_price * trade.quantity
    exit_val = trade.exit_price * trade.quantity
    expected_fee = (entry_val + exit_val) * 0.001

    assert pytest.approx(trade.fees, 1e-4) == expected_fee
    assert pytest.approx(trade.net_pnl, 1e-4) == trade.gross_pnl - expected_fee


def test_22_slippage_cost_model():
    """Requirement 22: Slippage adds adverse cost to both entry and exit."""
    candles = build_base_uptrend_setup()
    # Raw entry at 220.0, raw TP at 290.0
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=222.0)
    bar_63 = make_candle(63, open_p=222.0, high_p=295.0, low_p=220.0, close_p=292.0)
    all_candles = candles + [bar_62, bar_63]

    cost_model = CostModel(slippage_points=1.0)  # $1.0 adverse slippage per unit
    engine = BacktestEngine(config=BacktestConfig(cost_model=cost_model))
    result = engine.run(all_candles)

    trade = result.trades[0]
    # Long entry slippage adds $1 to entry price -> 221.0
    assert trade.entry_price == 221.0
    # Long exit slippage subtracts $1 from exit price -> 289.0
    assert trade.exit_price == 289.0
    # Total slippage cost = 2.0 * quantity
    assert pytest.approx(trade.slippage, 1e-4) == 2.0 * trade.quantity


def test_23_no_lookahead_bias():
    """Requirement 23: Future candles cannot alter past signals or executions."""
    base_candles = build_base_uptrend_setup()
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=222.0)
    bar_63_a = make_candle(63, open_p=222.0, high_p=225.0, low_p=220.0, close_p=223.0)
    bar_63_b = make_candle(63, open_p=222.0, high_p=500.0, low_p=10.0, close_p=300.0)  # Wildly different

    engine_a = BacktestEngine()
    engine_b = BacktestEngine()

    res_a = engine_a.run(base_candles + [bar_62, bar_63_a])
    res_b = engine_b.run(base_candles + [bar_62, bar_63_b])

    # Trade entry at bar 62 MUST be identical regardless of bar 63
    trade_a = res_a.trades[0]
    trade_b = res_b.trades[0]
    assert trade_a.entry_timestamp == trade_b.entry_timestamp
    assert trade_a.entry_price == trade_b.entry_price
    assert trade_a.stop_price == trade_b.stop_price
    assert trade_a.quantity == trade_b.quantity


def test_24_deterministic_repeated_backtest():
    """Requirement 24: Repeated backtest runs produce identical results."""
    candles = build_base_uptrend_setup()
    bar_62 = make_candle(62, open_p=220.0, high_p=225.0, low_p=218.0, close_p=222.0)
    bar_63 = make_candle(63, open_p=222.0, high_p=295.0, low_p=220.0, close_p=292.0)
    all_candles = candles + [bar_62, bar_63]

    engine = BacktestEngine()
    res_1 = engine.run(all_candles)
    res_2 = engine.run(all_candles)

    assert res_1.model_dump() == res_2.model_dump()
