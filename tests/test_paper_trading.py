"""Tests for Phase 4 Paper Trading Engine."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from atsits.journal.models import (
    EntryRecord,
    ExitRecord,
    MarketObservationRecord,
    SetupDetectedRecord,
    SetupRejectedRecord,
    TradeRecord,
)
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline
from atsits.models.backtest import CostModel
from atsits.models.market_data import Candle
from atsits.paper.account import PaperAccount
from atsits.paper.bootstrap import (
    bootstrap_warmup_from_csv,
    warmup_strategy,
)
from atsits.paper.executor import PaperExecutor
from atsits.paper.models import PaperAccountState, PaperPosition
from atsits.paper.runtime import PaperRuntime
from atsits.strategies.ema_pullback import EMAPullbackStrategy, EntrySignal


def _make_candle(
    timestamp: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 100.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_normalized_kline(
    timestamp: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 10.0,
    is_closed: bool = False,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> NormalizedKline:
    candle = _make_candle(timestamp, open_, high, low, close, volume, symbol, timeframe)
    close_time = timestamp + timedelta(hours=1)
    return NormalizedKline(
        candle=candle,
        is_closed=is_closed,
        event_time=close_time,
        close_time=close_time,
        trade_count=10,
        quote_volume=volume * close,
        raw_payload={},
    )


def _make_kline_payload(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    is_closed: bool,
) -> dict:
    return {
        "e": "kline",
        "E": end_ms,
        "s": symbol,
        "k": {
            "t": start_ms,
            "T": end_ms,
            "s": symbol,
            "i": interval,
            "f": 100,
            "L": 200,
            "o": str(open_),
            "c": str(close),
            "h": str(high),
            "l": str(low),
            "v": str(volume),
            "n": 50,
            "x": is_closed,
            "q": "1000.0",
            "V": "50.0",
            "Q": "500.0",
            "B": "0",
        },
    }


# =====================================================================
# Test A: Paper Account initialization, sizing, PnL math, and state
# =====================================================================
def test_a_paper_account_lifecycle_and_sizing():
    cost_model = CostModel(commission_rate=0.0004, slippage_pct=0.0001, slippage_points=0.0)
    account = PaperAccount(initial_equity=10000.0, risk_pct=0.01, cost_model=cost_model)

    assert account.initial_equity == 10000.0
    assert account.cash_balance == 10000.0
    assert not account.has_active_position
    assert account.trade_count == 0

    # Test sizing: 1% of 10000 = 100. Entry = 50000, Stop = 49000 (diff = 1000)
    # Quantity = 100 / 1000 = 0.1 BTC
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    pos = account.open_position(
        trade_id="trd-001",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=t0,
        confirmation_timestamp=t0 + timedelta(hours=1),
        entry_timestamp=t0 + timedelta(hours=2),
        open_price=50000.0,
        stop_price=49000.0,
    )

    assert pos.quantity == 0.1
    assert pos.risk_amount == 100.0
    # Long target = 50000 + 2 * 1000 = 52000
    assert pos.target_price == 52000.0
    # Entry slippage delta = 50000 * 0.0001 = 5.0 -> effective entry = 50005.0
    assert pos.entry_price == 50005.0
    # Entry fee = 50005.0 * 0.1 * 0.0004 = 2.0002
    assert pytest.approx(pos.entry_fee, 0.0001) == 2.0002
    assert account.has_active_position

    # Check mark-to-market equity at price 51000:
    # Gross unrealized = (51000 - 50000) * 0.1 = 100
    # Equity = 10000 + 100 - 2.0002 - 0.5 = 10097.4998
    equity_51k = account.get_equity(51000.0)
    assert pytest.approx(equity_51k, 0.01) == 10097.50

    # Close at TP (52000.0)
    # Exit slippage = 5.2, effective exit = 51994.8, exit fee = 51994.8 * 0.1 * 0.0004 = 2.079792
    # Gross PnL = (52000 - 50000) * 0.1 = 200.0
    # Total fees = 2.0002 + 2.079792 = 4.079992
    # Total slippage = 0.5 + 0.52 = 1.02
    # Net PnL = 200.0 - 4.079992 - 1.02 = 194.900008
    close_res = account.close_position(raw_exit_price=52000.0, exit_reason="TP_HIT")
    assert close_res["exit_reason"] == "TP_HIT"
    assert pytest.approx(close_res["gross_pnl"], 0.01) == 200.0
    assert pytest.approx(close_res["net_pnl"], 0.01) == 194.90
    assert pytest.approx(close_res["r_multiple"], 0.01) == 1.949
    assert account.trade_count == 1
    assert not account.has_active_position
    assert pytest.approx(account.cash_balance, 0.01) == 10194.90


# =====================================================================
# Test B: Next-Open Entry Execution with Pending Signal
# =====================================================================
def test_b_next_open_entry_execution(tmp_path: Path):
    journal_path = tmp_path / "test_paper_journal_b.jsonl"
    journal = TradingJournal(file_path=journal_path)

    account = PaperAccount(initial_equity=10000.0)
    strategy = EMAPullbackStrategy()
    executor = PaperExecutor(account=account, strategy=strategy, journal=journal, run_id="test_b")

    t_conf = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    t_entry = datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc)

    # Set pending signal manually
    executor.pending_signal = EntrySignal(
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
        confirmation_timestamp=t_conf,
        stop_price=49000.0,
        pullback_high=50000.0,
        pullback_low=49000.0,
    )

    # Feed tick of bar N (same timestamp as confirmation) -> Should NOT enter yet
    kline_n = _make_normalized_kline(
        timestamp=t_conf,
        open_=50000.0,
        high=50500.0,
        low=49800.0,
        close=50200.0,
        volume=10.0,
        is_closed=False,
    )
    executor.on_tick(kline_n)
    assert executor.pending_signal is not None
    assert not account.has_active_position

    # Feed first tick of bar N+1 -> Should enter at bar N+1 OPEN (50100.0)
    kline_n1 = _make_normalized_kline(
        timestamp=t_entry,
        open_=50100.0,
        high=50150.0,
        low=50080.0,
        close=50120.0,
        volume=5.0,
        is_closed=False,
    )
    executor.on_tick(kline_n1)

    assert executor.pending_signal is None
    assert account.has_active_position
    pos = account.active_position
    assert pos.raw_entry_price == 50100.0
    assert pos.entry_timestamp == t_entry

    # Check journal record
    records = journal.read_all()
    assert len(records) == 1
    assert isinstance(records[0], EntryRecord)
    assert records[0].execution_mode == "PAPER"
    assert records[0].raw_price == 50100.0


# =====================================================================
# Test C: Forming Candle Tick Updates Triggering SL/TP Exit
# =====================================================================
def test_c_forming_candle_tick_triggers_exit(tmp_path: Path):
    journal_path = tmp_path / "test_paper_journal_c.jsonl"
    journal = TradingJournal(file_path=journal_path)

    account = PaperAccount(initial_equity=10000.0)
    strategy = EMAPullbackStrategy()
    executor = PaperExecutor(account=account, strategy=strategy, journal=journal, run_id="test_c")

    t0 = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    # Open active LONG position
    account.open_position(
        trade_id="trd-c1",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=t0 - timedelta(hours=2),
        confirmation_timestamp=t0 - timedelta(hours=1),
        entry_timestamp=t0,
        open_price=50000.0,
        stop_price=49000.0,
    )
    assert account.has_active_position

    # Feed forming tick where low drops to 48900 (below SL 49000)
    kline_tick = _make_normalized_kline(
        timestamp=t0,
        open_=50000.0,
        high=50050.0,
        low=48900.0,
        close=48950.0,
        volume=12.0,
        is_closed=False,
    )
    executor.on_tick(kline_tick)

    assert not account.has_active_position
    assert len(executor.completed_trades_history) == 1
    assert executor.completed_trades_history[0]["exit_reason"] == "SL_HIT"

    records = journal.read_all()
    assert len(records) == 2
    assert isinstance(records[0], ExitRecord)
    assert isinstance(records[1], TradeRecord)
    assert records[0].execution_mode == "PAPER"
    assert records[1].execution_mode == "PAPER"
    assert records[0].exit_reason == "SL_HIT"


# =====================================================================
# Test D: Same-Bar SL/TP Ambiguity Resolving to SL First
# =====================================================================
def test_d_same_bar_sl_precedence(tmp_path: Path):
    journal_path = tmp_path / "test_paper_journal_d.jsonl"
    journal = TradingJournal(file_path=journal_path)

    account = PaperAccount(initial_equity=10000.0)
    strategy = EMAPullbackStrategy()
    executor = PaperExecutor(account=account, strategy=strategy, journal=journal, run_id="test_d")

    t0 = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    account.open_position(
        trade_id="trd-d1",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=t0 - timedelta(hours=2),
        confirmation_timestamp=t0 - timedelta(hours=1),
        entry_timestamp=t0,
        open_price=50000.0,
        stop_price=49000.0,  # TP is 52000.0
    )

    # Feed tick where both high >= 52000 and low <= 49000
    kline_tick = _make_normalized_kline(
        timestamp=t0,
        open_=50000.0,
        high=52500.0,
        low=48500.0,
        close=51000.0,
        volume=50.0,
        is_closed=False,
    )
    executor.on_tick(kline_tick)

    assert not account.has_active_position
    assert executor.completed_trades_history[0]["exit_reason"] == "SL_HIT"


# =====================================================================
# Test E: Rejection of Invalid Stop at Open
# =====================================================================
def test_e_rejection_of_invalid_stop_at_open(tmp_path: Path):
    journal_path = tmp_path / "test_paper_journal_e.jsonl"
    journal = TradingJournal(file_path=journal_path)

    account = PaperAccount(initial_equity=10000.0)
    strategy = EMAPullbackStrategy()
    executor = PaperExecutor(account=account, strategy=strategy, journal=journal, run_id="test_e")

    t_conf = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    t_entry = datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc)

    # Pending LONG signal with stop = 50000
    executor.pending_signal = EntrySignal(
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
        confirmation_timestamp=t_conf,
        stop_price=50000.0,
        pullback_high=50500.0,
        pullback_low=50000.0,
    )

    # Bar N+1 opens at 49800 <= stop_price (50000) -> Must reject
    kline_n1 = _make_normalized_kline(
        timestamp=t_entry,
        open_=49800.0,
        high=50200.0,
        low=49700.0,
        close=50100.0,
        volume=10.0,
        is_closed=False,
    )
    executor.on_tick(kline_n1)

    assert executor.pending_signal is None
    assert not account.has_active_position
    assert len(executor.rejections_history) == 1
    assert executor.rejections_history[0]["reason"] == "INVALID_STOP_AT_OPEN"

    records = journal.read_all()
    assert len(records) == 1
    assert isinstance(records[0], SetupRejectedRecord)
    assert records[0].execution_mode == "PAPER"
    assert records[0].reason == "INVALID_STOP_AT_OPEN"


# =====================================================================
# Test F: Single Active Position Rule (No Pyramiding)
# =====================================================================
def test_f_single_active_position_rule():
    account = PaperAccount(initial_equity=10000.0)
    strategy = EMAPullbackStrategy()
    executor = PaperExecutor(account=account, strategy=strategy, run_id="test_f")

    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    account.open_position(
        trade_id="trd-f1",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=t0 - timedelta(hours=2),
        confirmation_timestamp=t0 - timedelta(hours=1),
        entry_timestamp=t0,
        open_price=50000.0,
        stop_price=49000.0,
    )

    # Attempt to open second position directly -> raises RuntimeError
    with pytest.raises(RuntimeError):
        account.open_position(
            trade_id="trd-f2",
            strategy_version="1.0.0",
            symbol="BTCUSDT",
            timeframe="1h",
            direction="LONG",
            pullback_timestamp=t0,
            confirmation_timestamp=t0 + timedelta(hours=1),
            entry_timestamp=t0 + timedelta(hours=2),
            open_price=51000.0,
            stop_price=50000.0,
        )


# =====================================================================
# Test G: Warmup Strategy & CSV Bootstrap
# =====================================================================
def test_g_warmup_bootstrap():
    strategy = EMAPullbackStrategy()
    assert not strategy.is_ready

    # Generate 55 historical candles
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = [
        _make_candle(
            timestamp=t0 + timedelta(hours=i),
            open_=50000.0 + i * 10,
            high=50050.0 + i * 10,
            low=49950.0 + i * 10,
            close=50020.0 + i * 10,
        )
        for i in range(55)
    ]

    count = warmup_strategy(strategy, candles)
    assert count == 55
    assert strategy.is_ready
    assert strategy.fast_ema.value is not None
    assert strategy.slow_ema.value is not None


# =====================================================================
# Test H: Account Snapshot and State Restoration
# =====================================================================
def test_h_account_snapshot_and_restore():
    account = PaperAccount(initial_equity=10000.0, risk_pct=0.01)
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    pos = account.open_position(
        trade_id="trd-snap",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=t0 - timedelta(hours=2),
        confirmation_timestamp=t0 - timedelta(hours=1),
        entry_timestamp=t0,
        open_price=50000.0,
        stop_price=49000.0,
    )

    snapshot = account.snapshot()
    assert snapshot.cash_balance == 10000.0
    assert snapshot.active_position is not None
    assert snapshot.active_position.trade_id == "trd-snap"

    # Create new account and restore
    new_account = PaperAccount(initial_equity=5000.0)
    new_account.restore(snapshot)

    assert new_account.initial_equity == 10000.0
    assert new_account.cash_balance == 10000.0
    assert new_account.has_active_position
    assert new_account.active_position.trade_id == "trd-snap"


# =====================================================================
# Test J: End-to-End Deterministic Replay through PaperRuntime
# =====================================================================
def test_j_end_to_end_deterministic_paper_runtime(tmp_path: Path):
    journal_path = tmp_path / "test_paper_runtime_j.jsonl"
    journal = TradingJournal(file_path=journal_path)

    runtime = PaperRuntime(
        symbol="BTCUSDT",
        interval="1h",
        session_id="session_j",
        initial_equity=10000.0,
        risk_pct=0.01,
        journal=journal,
    )

    # 1. Warmup strategy with 55 candles in steady uptrend
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    warmup_candles = [
        _make_candle(
            timestamp=t0 + timedelta(hours=i),
            open_=40000.0 + i * 100,
            high=40080.0 + i * 100,
            low=39980.0 + i * 100,
            close=40050.0 + i * 100,
        )
        for i in range(55)
    ]
    runtime.warmup(candles=warmup_candles)
    assert runtime.strategy.is_ready

    # Fast EMA and Slow EMA are ready and in strong uptrend
    fast_ema = runtime.strategy.fast_ema.value
    slow_ema = runtime.strategy.slow_ema.value
    assert fast_ema > slow_ema

    # 2. Inject completed Pullback candle (Low <= EMA20)
    t_pullback = t0 + timedelta(hours=55)
    start_ms = int(t_pullback.timestamp() * 1000)
    end_ms = int((t_pullback + timedelta(hours=1)).timestamp() * 1000) - 1
    # Pullback bar: open=45500, high=45600, low=fast_ema - 10, close=45550
    pullback_low = fast_ema - 10.0
    pullback_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=45500.0, high=45600.0, low=pullback_low, close=45550.0, volume=100.0, is_closed=True
    )
    runtime.process_raw_message(pullback_msg)
    assert runtime.strategy._pullback_candidate is not None

    # 3. Inject completed Confirmation candle (Close > Pullback High & Close > EMA20 & EMA20 > EMA50)
    t_conf = t_pullback + timedelta(hours=1)
    start_ms = int(t_conf.timestamp() * 1000)
    end_ms = int((t_conf + timedelta(hours=1)).timestamp() * 1000) - 1
    conf_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=45550.0, high=45750.0, low=45500.0, close=45700.0, volume=150.0, is_closed=True
    )
    runtime.process_raw_message(conf_msg)
    assert runtime.executor.pending_signal is not None
    assert runtime.executor.pending_signal.direction == "LONG"
    assert not runtime.account.has_active_position

    # 4. Inject first tick of candle N+1 (entry execution at open)
    t_next = t_conf + timedelta(hours=1)
    start_ms = int(t_next.timestamp() * 1000)
    end_ms = int((t_next + timedelta(hours=1)).timestamp() * 1000) - 1
    tick1_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=45700.0, high=45720.0, low=45680.0, close=45710.0, volume=5.0, is_closed=False
    )
    runtime.process_raw_message(tick1_msg)
    assert runtime.executor.pending_signal is None
    assert runtime.account.has_active_position
    pos = runtime.account.active_position
    assert pos.raw_entry_price == 45700.0
    assert pos.stop_price == pullback_low

    # 5. Inject tick touching TP
    tp_level = pos.target_price
    tick2_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=45700.0, high=tp_level + 50.0, low=45650.0, close=tp_level + 10.0, volume=20.0, is_closed=False
    )
    runtime.process_raw_message(tick2_msg)
    assert not runtime.account.has_active_position
    assert runtime.account.trade_count == 1
    assert runtime.account.realized_pnl > 0.0

    # 6. Verify journal contents
    summary = runtime.get_summary()
    assert summary["trade_count"] == 1
    assert summary["realized_pnl"] > 0.0

    records = journal.read_all()
    # Records should contain: MarketObservationRecords, SetupDetectedRecord, EntryRecord, ExitRecord, TradeRecord
    record_types = [r.record_type.value for r in records]
    assert "SETUP_DETECTED" in record_types
    assert "ENTRY" in record_types
    assert "EXIT" in record_types
    assert "TRADE" in record_types

    # Ensure every single record has execution_mode == "PAPER"
    for r in records:
        assert r.execution_mode == "PAPER"


# =====================================================================
# Test K: Short Setup Lifecycle in Paper Trading
# =====================================================================
def test_k_short_trade_lifecycle(tmp_path: Path):
    journal_path = tmp_path / "test_paper_runtime_k.jsonl"
    journal = TradingJournal(file_path=journal_path)

    runtime = PaperRuntime(
        symbol="BTCUSDT",
        interval="1h",
        session_id="session_k",
        initial_equity=10000.0,
        risk_pct=0.01,
        journal=journal,
    )

    # 1. Warmup in downtrend
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    warmup_candles = [
        _make_candle(
            timestamp=t0 + timedelta(hours=i),
            open_=50000.0 - i * 100,
            high=50050.0 - i * 100,
            low=49950.0 - i * 100,
            close=49980.0 - i * 100,
        )
        for i in range(55)
    ]
    runtime.warmup(candles=warmup_candles)
    assert runtime.strategy.is_ready

    fast_ema = runtime.strategy.fast_ema.value
    slow_ema = runtime.strategy.slow_ema.value
    assert fast_ema < slow_ema

    # 2. Inject Pullback candle in downtrend (High >= EMA20)
    t_pullback = t0 + timedelta(hours=55)
    start_ms = int(t_pullback.timestamp() * 1000)
    end_ms = int((t_pullback + timedelta(hours=1)).timestamp() * 1000) - 1
    pullback_high = fast_ema + 10.0
    pullback_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=44000.0, high=pullback_high, low=43900.0, close=43950.0, volume=100.0, is_closed=True
    )
    runtime.process_raw_message(pullback_msg)
    assert runtime.strategy._pullback_candidate is not None

    # 3. Inject Confirmation candle (Close < Pullback Low & Close < EMA20 & EMA20 < EMA50)
    t_conf = t_pullback + timedelta(hours=1)
    start_ms = int(t_conf.timestamp() * 1000)
    end_ms = int((t_conf + timedelta(hours=1)).timestamp() * 1000) - 1
    conf_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=43950.0, high=43960.0, low=43700.0, close=43750.0, volume=150.0, is_closed=True
    )
    runtime.process_raw_message(conf_msg)
    assert runtime.executor.pending_signal is not None
    assert runtime.executor.pending_signal.direction == "SHORT"

    # 4. Inject next bar open tick (entry)
    t_next = t_conf + timedelta(hours=1)
    start_ms = int(t_next.timestamp() * 1000)
    end_ms = int((t_next + timedelta(hours=1)).timestamp() * 1000) - 1
    tick1_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=43750.0, high=43760.0, low=43720.0, close=43740.0, volume=5.0, is_closed=False
    )
    runtime.process_raw_message(tick1_msg)
    assert runtime.account.has_active_position
    pos = runtime.account.active_position
    assert pos.direction == "SHORT"
    assert pos.stop_price == pullback_high

    # 5. Inject tick reaching short TP
    tp_level = pos.target_price
    tick2_msg = _make_kline_payload(
        "BTCUSDT", "1h", start_ms, end_ms,
        open_=43750.0, high=43760.0, low=tp_level - 50.0, close=tp_level - 10.0, volume=20.0, is_closed=False
    )
    runtime.process_raw_message(tick2_msg)
    assert not runtime.account.has_active_position
    assert runtime.account.trade_count == 1
    assert runtime.account.realized_pnl > 0.0

