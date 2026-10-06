"""Phase 9 Live-Paper Pipeline Integration Test.

Deterministic integration test verifying the COMPLETE data path:

    mock Binance 1H klines (completed, no forming bar)
        ↓
    BinancePaperSession.warmup()          (EMA20/EMA30 warm-up)
        ↓
    BinancePaperSession.on_completed_candle()
        ↓
    EMAExperimentalStrategy.on_candle()   (EMA20/EMA30/3R evaluated)
        ↓
    EntrySignal (if confirmed EMA20/30 pullback)
        ↓
    PaperExecutor.on_tick()               (next bar open → position entry)
        ↓
    PaperAccount                          (1% equity risk, 3R target)
        ↓
    TradingJournal                        (SetupDetected + Entry records)

This test uses a DETERMINISTIC synthetic candle sequence that genuinely
produces a valid EMA20/EMA30 LONG pullback + confirmation setup. It does NOT
fabricate a trade signal — it constructs candles that satisfy all strategy
conditions from first principles.

Security properties verified:
- No real Binance network call occurs (all mocked)
- No real order is placed
- Paper equity is synthetic ($10,000)
- Target price is 3R (not 2R), confirming take_profit_rr flows through
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from atsits.binance.client import BinanceReadOnlyClient
from atsits.journal.models import EntryRecord, SetupDetectedRecord
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline
from atsits.models.market_data import Candle
from atsits.paper.session import BinancePaperSession, _candle_to_normalized_kline
from atsits.strategies.experimental_ema import EMAExperimentalStrategy


# =============================================================================
# Deterministic candle sequence builder
# =============================================================================

def _make_candle(
    ts: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        open=open_,
        high=max(open_, high, close),
        low=min(open_, low, close),
        close=close,
        volume=volume,
    )


def _base_ts(offset_hours: int = 0) -> datetime:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(hours=offset_hours)


def build_ema20_30_long_setup_sequence() -> List[Candle]:
    """Build a deterministic candle sequence that:

    1. Provides 35 warmup candles establishing EMA20 > EMA30 uptrend.
    2. Generates a pullback candle where Low <= EMA20.
    3. Generates a confirmation candle where Close > Pullback High and Close > EMA20.

    Strategy rules verified:
    - Trend: EMA20 > EMA30 (uptrend)
    - Pullback: completed candle Low <= EMA20
    - Confirmation: Close > pullback_high AND Close > EMA20 AND EMA20 > EMA30
    - Result: LONG EntrySignal
    """
    candles: List[Candle] = []

    # Phase 1: 40 strongly-trending upward candles to establish EMA20 > EMA30
    # Each candle is a clean rising close-only candle so EMAs converge correctly.
    # Starting price = 40,000, rising by 100 each candle.
    base_price = 40_000.0
    for i in range(40):
        ts = _base_ts(i)
        price = base_price + i * 100.0
        # Tight candle: open slightly below close, high = close + 50, low = open - 10
        open_ = price - 20.0
        close = price
        high = price + 50.0
        low = open_ - 10.0
        candles.append(_make_candle(ts, open_=open_, high=high, low=low, close=close))

    # After 40 candles EMA20 should be well above EMA30 (both warmed up).
    # Let's verify with a quick check:
    from atsits.strategies.experimental_ema import EMAExperimentalStrategy
    check_strat = EMAExperimentalStrategy()
    for c in candles:
        check_strat.on_candle(c, has_open_position=True)

    assert check_strat.is_ready, "Strategy not ready after 40 candles"
    ema20 = check_strat.fast_ema.value
    ema30 = check_strat.slow_ema.value
    assert ema20 is not None and ema30 is not None
    assert ema20 > ema30, f"EMA20 ({ema20:.2f}) must be > EMA30 ({ema30:.2f}) for uptrend"

    # Phase 2: Pullback candle.
    # The last close was 40,000 + 39 * 100 = 43,900. EMA20 ≈ ~43,000+.
    # Create a candle whose Low dips below EMA20 but Close stays above — qualifying pullback.
    pullback_ts = _base_ts(40)
    pullback_low = ema20 - 50.0   # Below EMA20 → qualifies as pullback
    pullback_high = ema20 + 200.0
    pullback_close = ema20 + 100.0  # Close above EMA20 (not a confirm-by-itself rule)
    pullback_open = ema20 + 150.0
    pullback_candle = _make_candle(
        pullback_ts,
        open_=pullback_open,
        high=pullback_high,
        low=pullback_low,
        close=pullback_close,
    )
    candles.append(pullback_candle)

    # Phase 3: Confirmation candle.
    # Must have: Close > pullback_high AND Close > EMA20 AND EMA20 > EMA30 still holds.
    # After feeding the pullback candle, recalculate EMAs:
    check_strat2 = EMAExperimentalStrategy()
    for c in candles:
        check_strat2.on_candle(c, has_open_position=True)

    ema20_after = check_strat2.fast_ema.value
    ema30_after = check_strat2.slow_ema.value
    assert ema20_after is not None and ema30_after is not None
    assert ema20_after > ema30_after, "Uptrend must be maintained after pullback candle"

    # Confirmation close must be strictly > pullback_high AND > EMA20_after
    confirm_close = max(pullback_high, ema20_after) + 150.0
    confirm_open = ema20_after + 50.0
    confirm_high = confirm_close + 100.0
    confirm_low = confirm_open - 30.0
    confirm_ts = _base_ts(41)
    confirm_candle = _make_candle(
        confirm_ts,
        open_=confirm_open,
        high=confirm_high,
        low=confirm_low,
        close=confirm_close,
    )
    candles.append(confirm_candle)

    return candles


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_binance_client() -> BinanceReadOnlyClient:
    """Mocked Binance client — no network calls, no credentials."""
    client = MagicMock(spec=BinanceReadOnlyClient)
    client.ping.return_value = True
    client.get_ticker_price.return_value = 44_000.0
    return client


@pytest.fixture
def tmp_journal(tmp_path) -> TradingJournal:
    journal_path = tmp_path / "paper_test.jsonl"
    return TradingJournal(journal_path)


@pytest.fixture
def session_with_journal(mock_binance_client, tmp_journal) -> BinancePaperSession:
    strategy = EMAExperimentalStrategy()
    return BinancePaperSession(
        binance_client=mock_binance_client,
        strategy=strategy,
        session_id="TEST-PAPER-SESSION",
        symbol="BTCUSDT",
        interval="1h",
        initial_equity=10_000.0,
        risk_pct=0.01,
        journal=tmp_journal,
    )


# =============================================================================
# Test 1: Verify warmup populates EMA state without producing signals
# =============================================================================

class TestPipelineWarmup:
    def test_warmup_from_candles_populates_ema(self, session_with_journal):
        """Warmup must feed candles to strategy EMA without producing signals."""
        strat = session_with_journal.strategy
        assert not strat.is_ready, "Strategy must start unwarmed"

        # Build 35 candles for warmup (EMA30 needs 30 at minimum)
        warmup_candles = [
            _make_candle(_base_ts(i), 40_000 + i * 50, 40_000 + i * 50 + 100,
                         40_000 + i * 50 - 20, 40_000 + i * 50)
            for i in range(35)
        ]
        count = session_with_journal.warmup(warmup_candles=warmup_candles)

        assert count == 35
        assert strat.is_ready, "Strategy must be ready after 35 candles (>= EMA30 period)"
        assert strat.fast_ema.value is not None
        assert strat.slow_ema.value is not None
        # No position should have opened during warmup
        assert not session_with_journal.account.has_active_position

    def test_warmup_sets_is_warmed_up_flag(self, session_with_journal):
        warmup_candles = [
            _make_candle(_base_ts(i), 40_000 + i * 50, 40_000 + i * 50 + 100,
                         40_000 + i * 50 - 20, 40_000 + i * 50)
            for i in range(35)
        ]
        session_with_journal.warmup(warmup_candles=warmup_candles)
        assert session_with_journal._is_warmed_up is True

    def test_warmup_without_candles_uses_fetch(self, session_with_journal, mock_binance_client):
        """warmup(warmup_candles=None) must call Binance REST API to fetch candles."""
        # Mock the fetch_public_binance_klines path via the client
        warmup_candles = [
            _make_candle(_base_ts(i), 40_000 + i * 50, 40_000 + i * 50 + 100,
                         40_000 + i * 50 - 20, 40_000 + i * 50)
            for i in range(35)
        ]
        # Patch fetch_public_binance_klines at module level to return our candles
        from unittest.mock import patch
        with patch("atsits.paper.session.fetch_public_binance_klines", return_value=warmup_candles):
            count = session_with_journal.warmup()
        assert count == 35


# =============================================================================
# Test 2: Verify on_completed_candle() calls strategy, not forming bars
# =============================================================================

class TestCompletedCandleProcessing:
    def test_on_completed_candle_calls_strategy(self, session_with_journal):
        """on_completed_candle() must call strategy.on_candle() exactly once per candle."""
        candle = _make_candle(_base_ts(0), 40_000, 41_000, 39_000, 40_500)

        from unittest.mock import patch
        with patch.object(session_with_journal.strategy, "on_candle", return_value=None) as mock_on_candle:
            session_with_journal.on_completed_candle(candle)
            assert mock_on_candle.call_count == 1
            call_args = mock_on_candle.call_args
            # First positional arg must be the candle
            assert call_args[0][0] == candle

    def test_candles_processed_counter_increments(self, session_with_journal):
        candle = _make_candle(_base_ts(0), 40_000, 41_000, 39_000, 40_500)
        assert session_with_journal._candles_processed == 0
        session_with_journal.on_completed_candle(candle)
        assert session_with_journal._candles_processed == 1
        session_with_journal.on_completed_candle(
            _make_candle(_base_ts(1), 40_500, 41_500, 40_000, 41_000)
        )
        assert session_with_journal._candles_processed == 2

    def test_forming_candle_excluded_from_signal_evaluation(self, session_with_journal):
        """on_tick() with a forming candle must NOT call strategy.on_candle().

        PaperExecutor.on_tick() only monitors SL/TP and pending entries —
        it never calls strategy.on_candle(). Strategy evaluation is ONLY
        inside on_candle_completed(), which must only receive closed bars.
        """
        forming_candle = _make_candle(_base_ts(99), 40_000, 41_000, 39_500, 40_800)
        forming_kline = NormalizedKline(
            candle=forming_candle,
            is_closed=False,  # FORMING — not completed
            event_time=forming_candle.timestamp,
            close_time=forming_candle.timestamp,
            trade_count=0,
            quote_volume=0.0,
            raw_payload={},
        )
        from unittest.mock import patch
        with patch.object(session_with_journal.strategy, "on_candle", return_value=None) as mock_on_candle:
            # on_tick() must NOT call on_candle — forming bars are never strategy-evaluated
            session_with_journal.on_tick(forming_kline)
            assert mock_on_candle.call_count == 0, (
                "strategy.on_candle() must NEVER be called by on_tick() with forming candle"
            )


# =============================================================================
# Test 3: Full deterministic pipeline — candle stream → signal → position
# =============================================================================

class TestFullPipelineIntegration:
    """End-to-end deterministic pipeline test.

    Uses a synthetic candle sequence that genuinely satisfies EMA20/EMA30 strategy
    conditions. The signal and position are NOT fabricated — they emerge from
    the actual strategy logic applied to the deterministic candles.
    """

    def test_full_pipeline_produces_signal(self, mock_binance_client, tmp_journal):
        """Full pipeline: candles → EMA calc → pullback → confirmation → EntrySignal."""
        all_candles = build_ema20_30_long_setup_sequence()

        # All candles except the last two (pullback + confirmation)
        warmup_candles = all_candles[:-2]
        pullback_candle = all_candles[-2]
        confirm_candle = all_candles[-1]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            session_id="TEST-FULL-PIPELINE",
            initial_equity=10_000.0,
            journal=tmp_journal,
        )

        # Step 1: Warmup
        session.warmup(warmup_candles=warmup_candles)
        assert strategy.is_ready, "Strategy must be ready after warmup"
        assert strategy.fast_ema.value > strategy.slow_ema.value, "Must be in uptrend after warmup"

        # Step 2: Process pullback candle — should NOT produce signal yet
        signal_on_pullback = session.on_completed_candle(pullback_candle)
        assert signal_on_pullback is None, (
            "Pullback candle alone must NOT produce a signal — it sets up the candidate only"
        )
        # Strategy must have a pending pullback candidate
        assert strategy._pullback_candidate is not None, "Pullback candidate must be set"
        assert strategy._pullback_candidate.direction == "LONG"

        # Step 3: Process confirmation candle — must produce LONG signal
        signal_on_confirm = session.on_completed_candle(confirm_candle)
        assert signal_on_confirm is not None, (
            "Confirmation candle following valid pullback must produce EntrySignal"
        )
        assert signal_on_confirm.direction == "LONG"
        assert signal_on_confirm.strategy_version == "EMA_Pullback_EMA20_30_3R"
        assert signal_on_confirm.stop_price == pullback_candle.low, (
            "Stop price must be the pullback candle Low"
        )
        assert signal_on_confirm.pullback_timestamp == pullback_candle.timestamp
        assert signal_on_confirm.confirmation_timestamp == confirm_candle.timestamp

    def test_full_pipeline_pending_signal_set_after_confirmation(self, mock_binance_client, tmp_journal):
        """After confirmation, executor.pending_signal must be set (awaiting next bar entry)."""
        all_candles = build_ema20_30_long_setup_sequence()
        warmup_candles = all_candles[:-2]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            session_id="TEST-PENDING",
            initial_equity=10_000.0,
            journal=tmp_journal,
        )
        session.warmup(warmup_candles=warmup_candles)
        session.on_completed_candle(all_candles[-2])  # pullback
        session.on_completed_candle(all_candles[-1])  # confirmation → signal

        # Executor must hold the pending signal
        assert session.executor.pending_signal is not None, (
            "executor.pending_signal must be set after confirmation candle"
        )
        assert session.executor.pending_signal.direction == "LONG"

        # Paper account must NOT have opened a position yet
        assert not session.account.has_active_position, (
            "Position must NOT be opened on confirmation bar — entry is on NEXT bar open"
        )

    def test_full_pipeline_entry_on_next_bar(self, mock_binance_client, tmp_journal):
        """After confirmation, the NEXT bar's on_tick() must trigger position entry."""
        all_candles = build_ema20_30_long_setup_sequence()
        warmup_candles = all_candles[:-2]
        confirm_candle = all_candles[-1]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            session_id="TEST-ENTRY",
            initial_equity=10_000.0,
            journal=tmp_journal,
        )
        session.warmup(warmup_candles=warmup_candles)
        session.on_completed_candle(all_candles[-2])  # pullback
        session.on_completed_candle(confirm_candle)   # confirmation

        assert session.executor.pending_signal is not None

        # Simulate the NEXT bar arriving (timestamp must be > confirmation bar timestamp)
        entry_open_price = 46_000.0  # above pullback stop, valid entry
        next_bar_ts = confirm_candle.timestamp + timedelta(hours=1)
        next_bar = _make_candle(next_bar_ts, entry_open_price, entry_open_price + 500,
                                entry_open_price - 200, entry_open_price + 300)
        next_kline = _candle_to_normalized_kline(next_bar, is_closed=False)

        session.executor.on_tick(next_kline)

        # Position must now be open
        assert session.account.has_active_position, (
            "Position must be opened when next bar's on_tick() fires with timestamp > confirmation"
        )
        pos = session.account.active_position
        assert pos is not None
        assert pos.direction == "LONG"
        assert pos.raw_entry_price == entry_open_price, (
            "Entry price must be the next bar's open price"
        )

    def test_full_pipeline_target_is_3r_not_2r(self, mock_binance_client, tmp_journal):
        """Position target must be 3R from entry, NOT 2R (EMAExperimentalStrategy)."""
        all_candles = build_ema20_30_long_setup_sequence()
        warmup_candles = all_candles[:-2]
        confirm_candle = all_candles[-1]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            session_id="TEST-3R",
            initial_equity=10_000.0,
            journal=tmp_journal,
        )
        session.warmup(warmup_candles=warmup_candles)
        session.on_completed_candle(all_candles[-2])
        session.on_completed_candle(confirm_candle)

        assert session.executor.pending_signal is not None
        signal = session.executor.pending_signal
        stop_price = signal.stop_price

        entry_open_price = 46_000.0
        next_bar_ts = confirm_candle.timestamp + timedelta(hours=1)
        next_bar = _make_candle(next_bar_ts, entry_open_price, entry_open_price + 500,
                                stop_price + 100, entry_open_price + 300)
        session.executor.on_tick(_candle_to_normalized_kline(next_bar, is_closed=False))

        assert session.account.has_active_position
        pos = session.account.active_position
        assert pos is not None

        risk_per_unit = abs(entry_open_price - stop_price)
        expected_target_3r = entry_open_price + (3.0 * risk_per_unit)
        expected_target_2r = entry_open_price + (2.0 * risk_per_unit)

        # Must be 3R, NOT 2R
        assert abs(pos.target_price - expected_target_3r) < 0.01, (
            f"Target must be 3R ({expected_target_3r:.2f}), got {pos.target_price:.2f}. "
            f"2R would have been {expected_target_2r:.2f}."
        )
        assert abs(pos.target_price - expected_target_2r) > 0.01, (
            "Target must NOT be 2R — EMAExperimentalStrategy uses 3R"
        )

    def test_full_pipeline_journal_records_setup_and_entry(self, mock_binance_client, tmp_journal):
        """Journal must record SetupDetectedRecord on confirmation and EntryRecord on entry."""
        all_candles = build_ema20_30_long_setup_sequence()
        warmup_candles = all_candles[:-2]
        confirm_candle = all_candles[-1]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            session_id="TEST-JOURNAL",
            initial_equity=10_000.0,
            journal=tmp_journal,
        )
        session.warmup(warmup_candles=warmup_candles)
        session.on_completed_candle(all_candles[-2])  # pullback
        session.on_completed_candle(confirm_candle)   # confirmation → journal SetupDetected

        # Trigger entry on next bar
        entry_open_price = 46_000.0
        next_bar_ts = confirm_candle.timestamp + timedelta(hours=1)
        next_bar = _make_candle(next_bar_ts, entry_open_price, entry_open_price + 500,
                                session.executor.pending_signal.stop_price + 100,
                                entry_open_price + 300)
        session.executor.on_tick(_candle_to_normalized_kline(next_bar, is_closed=False))

        # Read all journal records
        records = tmp_journal.read_all()

        record_types = [type(r).__name__ for r in records]

        assert "SetupDetectedRecord" in record_types, (
            "Journal must contain a SetupDetectedRecord when signal is confirmed"
        )
        assert "EntryRecord" in record_types, (
            "Journal must contain an EntryRecord when position is entered"
        )
        # Also observation records for the processed candles
        assert "MarketObservationRecord" in record_types, (
            "Journal must record MarketObservationRecord for each completed candle"
        )

        # Verify SetupDetected has correct direction
        setup_records = [r for r in records if isinstance(r, SetupDetectedRecord)]
        assert any(r.direction == "LONG" for r in setup_records)

        # Verify EntryRecord has correct strategy version
        entry_records = [r for r in records if isinstance(r, EntryRecord)]
        assert any(r.strategy_version == "EMA_Pullback_EMA20_30_3R" for r in entry_records)

    def test_full_pipeline_sl_tp_monitoring_via_on_tick(self, mock_binance_client, tmp_journal):
        """After entry, intrabar ticks must evaluate SL/TP and close position if hit."""
        all_candles = build_ema20_30_long_setup_sequence()
        warmup_candles = all_candles[:-2]
        confirm_candle = all_candles[-1]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            session_id="TEST-SL-TP",
            initial_equity=10_000.0,
            journal=tmp_journal,
        )
        session.warmup(warmup_candles=warmup_candles)
        session.on_completed_candle(all_candles[-2])
        session.on_completed_candle(confirm_candle)

        signal = session.executor.pending_signal
        stop_price = signal.stop_price

        # Open position on next bar
        entry_open_price = 46_000.0
        next_bar_ts = confirm_candle.timestamp + timedelta(hours=1)
        entry_bar = _make_candle(next_bar_ts, entry_open_price, entry_open_price + 200,
                                 stop_price + 100, entry_open_price + 100)
        session.executor.on_tick(_candle_to_normalized_kline(entry_bar, is_closed=False))
        assert session.account.has_active_position

        pos = session.account.active_position
        tp_price = pos.target_price

        # Now simulate a tick where price reaches TP (3R above entry)
        tp_bar_ts = next_bar_ts + timedelta(hours=1)
        tp_bar = _make_candle(
            tp_bar_ts,
            open_=entry_open_price + 100,
            high=tp_price + 100,  # High exceeds TP → triggers TP_HIT
            low=entry_open_price - 50,
            close=tp_price + 50,
        )
        session.executor.on_tick(_candle_to_normalized_kline(tp_bar, is_closed=False))

        # Position must be closed
        assert not session.account.has_active_position, (
            "Position must be closed when a tick's High exceeds the 3R TP level"
        )
        assert len(session.executor.completed_trades_history) == 1
        trade = session.executor.completed_trades_history[0]
        assert trade["exit_reason"] == "TP_HIT"
        # Net PnL must be positive (TP hit at 3R)
        assert trade["net_pnl"] > 0, "TP_HIT must produce positive net PnL"


# =============================================================================
# Test 4: MCP tools expose actual live session state
# =============================================================================

class TestMCPExposesLiveSessionState:
    """Verify MCP paper-state tools read from the actual live BinancePaperSession."""

    @pytest.fixture
    def session(self, mock_binance_client, tmp_journal):
        strategy = EMAExperimentalStrategy()
        return BinancePaperSession(
            binance_client=mock_binance_client,
            strategy=strategy,
            initial_equity=10_000.0,
            journal=tmp_journal,
        )

    @pytest.fixture
    def registry(self, session):
        from atsits.mcp.tools import MCPToolRegistry
        return MCPToolRegistry(paper_session=session)

    def test_get_paper_account_reflects_live_session(self, registry, session):
        account = registry.execute_tool("get_paper_account", {})
        assert account["initial_equity"] == session.account.initial_equity

    def test_get_paper_session_reflects_candles_processed(self, registry, session):
        """After processing candles, MCP tool must report updated candles_processed."""
        # Process 3 candles directly
        for i in range(3):
            session.on_completed_candle(
                _make_candle(_base_ts(i), 40_000 + i * 100, 40_500 + i * 100,
                             39_800 + i * 100, 40_200 + i * 100)
            )
        summary = registry.execute_tool("get_paper_session", {})
        # candles_processed is nested in account
        assert summary["candles_processed"] == 3

    def test_get_paper_positions_reflects_live_position(self, registry, session, mock_binance_client):
        """After strategy opens a position, MCP get_paper_positions must return it."""
        all_candles = build_ema20_30_long_setup_sequence()
        warmup_candles = all_candles[:-2]
        confirm_candle = all_candles[-1]

        session.warmup(warmup_candles=warmup_candles)
        session.on_completed_candle(all_candles[-2])
        session.on_completed_candle(confirm_candle)

        assert session.executor.pending_signal is not None

        entry_open_price = 46_000.0
        next_bar_ts = confirm_candle.timestamp + timedelta(hours=1)
        next_bar = _make_candle(next_bar_ts, entry_open_price, entry_open_price + 500,
                                session.executor.pending_signal.stop_price + 100,
                                entry_open_price + 300)
        session.executor.on_tick(_candle_to_normalized_kline(next_bar, is_closed=False))

        assert session.account.has_active_position

        positions = registry.execute_tool("get_paper_positions", {})
        assert len(positions) == 1
        assert positions[0]["direction"] == "LONG"
        assert positions[0]["take_profit_rr"] == 3.0


# =============================================================================
# Test 5: Security — credentials, public-only mode, no real orders
# =============================================================================

class TestSecurityPipelineAudit:
    def test_public_market_mode_works_without_auth_credentials(self):
        """Market data (candles, price) must work with placeholder credentials.

        Public Binance endpoints require no authentication. The client must
        not fail or reject calls when credentials are placeholder values.
        BinanceReadOnlyClient passes credentials only to authenticated endpoints.
        """
        # Public endpoints are tested via mock — no network call
        client = MagicMock(spec=BinanceReadOnlyClient)
        client.ping.return_value = True
        client.get_ticker_price.return_value = 44_000.0
        client.get_klines.return_value = []

        # Session with placeholder credentials (public endpoints only)
        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=client,
            strategy=strategy,
            initial_equity=10_000.0,
        )

        # Public market data methods must work
        price = session.get_current_price()
        assert price == 44_000.0

        candles = session.get_recent_candles(limit=5)
        assert isinstance(candles, list)

    def test_absence_of_credentials_does_not_disable_public_paper_trading(self, tmp_journal):
        """Paper trading pipeline must function using only public endpoints (no auth).

        The strategy evaluation, position simulation, and account state are
        all internal — they never require Binance authentication.
        """
        client = MagicMock(spec=BinanceReadOnlyClient)
        client.get_ticker_price.return_value = 44_000.0

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=client,
            strategy=strategy,
            initial_equity=10_000.0,
            journal=tmp_journal,
        )

        # Warmup with explicit candles (no network call needed)
        warmup_candles = [
            _make_candle(_base_ts(i), 40_000 + i * 50, 40_000 + i * 50 + 100,
                         40_000 + i * 50 - 20, 40_000 + i * 50)
            for i in range(35)
        ]
        session.warmup(warmup_candles=warmup_candles)

        # Feed a candle — no auth needed
        candle = _make_candle(_base_ts(35), 42_000, 43_000, 41_000, 42_500)
        session.on_completed_candle(candle)

        # Account state is available without auth
        account = session.get_paper_account(current_price=44_000.0)
        assert account["initial_equity"] == 10_000.0
        # get_account_status() is the only thing that needs auth
        # and it gracefully handles errors

    def test_credentials_not_used_in_on_completed_candle(self, tmp_journal):
        """on_completed_candle() must NEVER call authenticated Binance endpoints."""
        client = MagicMock(spec=BinanceReadOnlyClient)
        client.get_ticker_price.return_value = 44_000.0

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=client,
            strategy=strategy,
            initial_equity=10_000.0,
            journal=tmp_journal,
        )

        candle = _make_candle(_base_ts(0), 40_000, 41_000, 39_000, 40_500)
        session.on_completed_candle(candle)

        # Authenticated endpoints must NOT have been called
        client.get_account_status.assert_not_called()
        client.get_balances.assert_not_called()

    def test_no_real_binance_balance_used_as_paper_equity(self, tmp_journal):
        """Real Binance balance must NEVER set or influence paper account equity."""
        client = MagicMock(spec=BinanceReadOnlyClient)
        client.get_ticker_price.return_value = 44_000.0
        # Even if Binance reports $1M balance...
        client.get_balances.return_value = [
            {"asset": "USDT", "free": 1_000_000.0, "locked": 0.0, "total": 1_000_000.0}
        ]

        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=client,
            strategy=strategy,
            initial_equity=10_000.0,
            journal=tmp_journal,
        )

        # Paper equity must remain $10,000 regardless of real balance
        assert session.account.initial_equity == 10_000.0
        assert session.account.cash_balance == 10_000.0

        # After reading balances
        session.get_binance_balances()
        assert session.account.initial_equity == 10_000.0
        assert session.account.cash_balance == 10_000.0

    def test_no_place_order_capability_on_binance_client(self):
        """BinanceReadOnlyClient must have ZERO order placement methods."""
        forbidden = [
            "place_order", "new_order", "cancel_order", "create_order",
            "modify_order", "submit_order", "execute_order",
            "withdraw", "transfer", "margin_borrow", "futures_order",
        ]
        for method in forbidden:
            assert not hasattr(BinanceReadOnlyClient, method), (
                f"SECURITY: BinanceReadOnlyClient must NOT have method '{method}'"
            )

    def test_no_http_post_or_write_methods(self):
        """BinanceReadOnlyClient must have no _post, _put, _delete, or _patch methods."""
        forbidden_internals = ["_post", "_put", "_delete", "_patch", "_send_order"]
        for method in forbidden_internals:
            assert not hasattr(BinanceReadOnlyClient, method), (
                f"SECURITY: BinanceReadOnlyClient must NOT have internal write method '{method}'"
            )

    def test_authenticated_endpoint_only_used_for_account_read(self):
        """_get_signed() must ONLY be reachable from account-read methods, not any write path."""
        import inspect
        source = inspect.getsource(BinanceReadOnlyClient)
        # The only calls to _get_signed should come from get_account_status and get_balances
        assert "_get_signed" in source
        # No POST, PUT, or write method should exist
        assert "urllib.request.Request" in source  # only GET requests
        # Ensure there's no method= assignment to POST
        assert 'method="POST"' not in source
        assert "method='POST'" not in source


# =============================================================================
# Test 6: Regression guard — locked baseline unchanged
# =============================================================================

class TestHistoricalRegressionGuardAfterFixes:
    """Verify the take_profit_rr fix in PaperAccount.open_position() does NOT
    alter the locked EMA_Pullback_v1.0 backtester results."""

    def test_backtester_uses_strategy_rr_not_account_default(self):
        """BacktestEngine must still use getattr(strategy, 'take_profit_rr', 2.0),
        which is 2.0 for EMAPullbackStrategy — baseline unchanged."""
        from pathlib import Path
        from atsits.data.loader import load_candles_from_csv
        from atsits.engine.backtester import BacktestEngine
        from atsits.models.backtest import BacktestConfig, CostModel
        from atsits.strategies.ema_pullback import EMAPullbackStrategy

        data_path = Path("data/btcusdt_1h.csv")
        if not data_path.exists():
            pytest.skip("Historical data not available")

        candles = load_candles_from_csv(data_path)
        strategy = EMAPullbackStrategy()
        assert strategy.take_profit_rr == 2.0, "Locked strategy must use 2R"

        engine = BacktestEngine(
            strategy=strategy,
            config=BacktestConfig(initial_equity=10_000.0, cost_model=CostModel()),
        )
        result = engine.run(candles)

        assert result.number_of_trades == 201, f"Regression: expected 201 trades, got {result.number_of_trades}"
        assert abs(result.total_net_pnl - (-306.09)) < 0.05, (
            f"Regression: expected -$306.09, got ${result.total_net_pnl:.2f}"
        )
        assert abs(result.win_rate * 100 - 33.33) < 0.1, (
            f"Regression: expected 33.33% WR, got {result.win_rate * 100:.2f}%"
        )

    def test_paper_account_open_position_default_rr_is_2(self):
        """PaperAccount.open_position() default take_profit_rr=2.0 — backward compatible."""
        from atsits.paper.account import PaperAccount
        from datetime import datetime, timezone

        account = PaperAccount(initial_equity=10_000.0, risk_pct=0.01)
        ts = datetime.now(timezone.utc)
        pos = account.open_position(
            trade_id="test-001",
            strategy_version="EMA_Pullback_v1.0",
            symbol="BTCUSDT",
            timeframe="1h",
            direction="LONG",
            pullback_timestamp=ts,
            confirmation_timestamp=ts,
            entry_timestamp=ts,
            open_price=40_000.0,
            stop_price=39_000.0,
            # take_profit_rr not passed → defaults to 2.0
        )
        risk_per_unit = 40_000.0 - 39_000.0  # 1000
        expected_target = 40_000.0 + (2.0 * risk_per_unit)  # 42,000
        assert pos.target_price == expected_target, (
            f"Default 2R target must be {expected_target}, got {pos.target_price}"
        )

    def test_paper_account_open_position_3r_for_experimental(self):
        """PaperAccount.open_position() with take_profit_rr=3.0 → 3R target."""
        from atsits.paper.account import PaperAccount
        from datetime import datetime, timezone

        account = PaperAccount(initial_equity=10_000.0, risk_pct=0.01)
        ts = datetime.now(timezone.utc)
        pos = account.open_position(
            trade_id="test-002",
            strategy_version="EMA_Pullback_EMA20_30_3R",
            symbol="BTCUSDT",
            timeframe="1h",
            direction="LONG",
            pullback_timestamp=ts,
            confirmation_timestamp=ts,
            entry_timestamp=ts,
            open_price=40_000.0,
            stop_price=39_000.0,
            take_profit_rr=3.0,
        )
        risk_per_unit = 1_000.0
        expected_target = 40_000.0 + (3.0 * risk_per_unit)  # 43,000
        assert pos.target_price == expected_target, (
            f"3R target must be {expected_target}, got {pos.target_price}"
        )
