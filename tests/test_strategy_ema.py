"""Unit tests for EMA_Pullback_v1.0 Strategy logic."""

import pytest
from atsits.strategies.ema_pullback import EMAPullbackStrategy
from tests.conftest import make_candle, make_trending_candles


def test_1_valid_long_setup():
    """Requirement 1: Valid Long setup generates confirmed EntrySignal."""
    # 60 uptrend candles so EMA20 > EMA50
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    strategy = EMAPullbackStrategy()

    for c in candles:
        sig = strategy.on_candle(c, has_open_position=False)
        assert sig is None

    # At bar 60, EMA20 is around 190+, EMA50 is lower.
    # Pullback candle (bar 60): Low <= EMA20 (e.g. dips to 180)
    ema20_val = strategy.fast_ema.value
    assert ema20_val is not None
    pullback_candle = make_candle(
        index=60,
        open_p=210.0,
        high_p=212.0,
        low_p=ema20_val - 2.0,  # Low <= EMA20
        close_p=205.0,
    )
    sig_pb = strategy.on_candle(pullback_candle, has_open_position=False)
    # Pullback candle must NOT itself trigger an entry
    assert sig_pb is None

    # Confirmation candle (bar 61): Close > pullback High (212) and Close > EMA20
    confirm_candle = make_candle(
        index=61,
        open_p=206.0,
        high_p=220.0,
        low_p=205.0,
        close_p=218.0,  # > 212 and > EMA20
    )
    sig_confirm = strategy.on_candle(confirm_candle, has_open_position=False)
    assert sig_confirm is not None
    assert sig_confirm.direction == "LONG"
    assert sig_confirm.pullback_timestamp == pullback_candle.timestamp
    assert sig_confirm.confirmation_timestamp == confirm_candle.timestamp
    # Stop loss must be pullback Low
    assert sig_confirm.stop_price == pullback_candle.low


def test_2_valid_short_setup():
    """Requirement 2: Valid Short setup generates confirmed EntrySignal."""
    # 60 downtrend candles so EMA20 < EMA50
    candles = make_trending_candles(60, start_price=500.0, step=-2.0)
    strategy = EMAPullbackStrategy()

    for c in candles:
        strategy.on_candle(c, has_open_position=False)

    ema20_val = strategy.fast_ema.value
    assert ema20_val is not None

    # Pullback candle (bar 60): High >= EMA20
    pullback_candle = make_candle(
        index=60,
        open_p=380.0,
        high_p=ema20_val + 5.0,  # High >= EMA20
        low_p=375.0,
        close_p=378.0,
    )
    sig_pb = strategy.on_candle(pullback_candle, has_open_position=False)
    assert sig_pb is None

    # Confirmation candle (bar 61): Close < pullback Low (375) and Close < EMA20
    confirm_candle = make_candle(
        index=61,
        open_p=377.0,
        high_p=378.0,
        low_p=365.0,
        close_p=370.0,  # < 375 and < EMA20
    )
    sig_confirm = strategy.on_candle(confirm_candle, has_open_position=False)
    assert sig_confirm is not None
    assert sig_confirm.direction == "SHORT"
    assert sig_confirm.pullback_timestamp == pullback_candle.timestamp
    assert sig_confirm.confirmation_timestamp == confirm_candle.timestamp
    # Stop loss must be pullback High
    assert sig_confirm.stop_price == pullback_candle.high


def test_3_no_setup_when_trend_is_wrong():
    """Requirement 3: No setup when EMA trend is not aligned."""
    # In a downtrend (EMA20 < EMA50), a bullish pullback/bounce candle must NOT produce a LONG setup
    candles = make_trending_candles(60, start_price=500.0, step=-2.0)
    strategy = EMAPullbackStrategy()
    for c in candles:
        strategy.on_candle(c, has_open_position=False)

    ema20_val = strategy.fast_ema.value
    assert ema20_val is not None

    # In a downtrend, a candle with Low <= EMA20 and then closing above EMA20 must NOT produce a LONG setup
    c_pb = make_candle(60, open_p=375.0, high_p=382.0, low_p=370.0, close_p=375.0)
    sig_pb = strategy.on_candle(c_pb, has_open_position=False)
    assert sig_pb is None

    c_conf = make_candle(61, open_p=376.0, high_p=395.0, low_p=375.0, close_p=390.0)
    sig_conf = strategy.on_candle(c_conf, has_open_position=False)
    assert sig_conf is None  # Rejection: trend is downtrend (EMA20 < EMA50), cannot long


def test_4_pullback_candle_does_not_itself_trigger_entry():
    """Requirement 4: Pullback candle alone does not trigger entry."""
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    strategy = EMAPullbackStrategy()
    for c in candles:
        strategy.on_candle(c, has_open_position=False)

    ema20_val = strategy.fast_ema.value
    assert ema20_val is not None

    pb_candle = make_candle(60, 210.0, 212.0, ema20_val - 2.0, 205.0)
    sig = strategy.on_candle(pb_candle, has_open_position=False)
    assert sig is None


def test_5_confirmation_must_be_immediately_next_candle():
    """Requirement 5: Confirmation window is single-candle only."""
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    strategy = EMAPullbackStrategy()
    for c in candles:
        strategy.on_candle(c, has_open_position=False)

    ema20_val = strategy.fast_ema.value
    assert ema20_val is not None

    # Bar 60: Pullback
    pb_candle = make_candle(60, 210.0, 212.0, ema20_val - 2.0, 205.0)
    strategy.on_candle(pb_candle, has_open_position=False)

    # Bar 61: Fails confirmation (does not break High)
    fail_candle = make_candle(61, 205.0, 210.0, 204.0, 208.0)
    sig_fail = strategy.on_candle(fail_candle, has_open_position=False)
    assert sig_fail is None

    # Bar 62: Breaks bar 60 High, but window has passed
    delayed_candle = make_candle(62, 208.0, 220.0, 207.0, 218.0)
    sig_delayed = strategy.on_candle(delayed_candle, has_open_position=False)
    assert sig_delayed is None


def test_6_confirmation_must_break_pullback_high_low():
    """Requirement 6: Confirmation candle must close beyond pullback High (Long) or Low (Short)."""
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    strategy = EMAPullbackStrategy()
    for c in candles:
        strategy.on_candle(c, has_open_position=False)

    ema20_val = strategy.fast_ema.value
    assert ema20_val is not None

    # Pullback with High = 215.0
    pb_candle = make_candle(60, 210.0, 215.0, ema20_val - 2.0, 205.0)
    strategy.on_candle(pb_candle, has_open_position=False)

    # Next candle closes at 214.0 (above EMA20 but below pullback High 215.0)
    confirm_candle = make_candle(61, 206.0, 214.5, 205.0, 214.0)
    sig = strategy.on_candle(confirm_candle, has_open_position=False)
    assert sig is None


def test_19_ema_warmup():
    """Requirement 19: No signals or setups during EMA warmup period."""
    # First 49 bars (EMA50 needs 50 bars)
    candles = make_trending_candles(49, start_price=100.0, step=2.0)
    strategy = EMAPullbackStrategy()

    for c in candles:
        sig = strategy.on_candle(c, has_open_position=False)
        assert sig is None

    assert not strategy.is_ready
    assert strategy.slow_ema.value is None
