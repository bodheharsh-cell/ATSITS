"""Unit tests for Phase 3 Live Market Observer with mocked WebSocket data (Requirements 1-20)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import pytest
from atsits.journal.models import JournalRecordType
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline, normalize_binance_kline
from atsits.market.observer import LiveMarketObserver
from atsits.models.market_data import Candle


def make_raw_kline_payload(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    start_time_ms: int = 1767225600000,  # 2026-01-01 00:00:00 UTC
    open_p: float = 50000.0,
    high_p: float = 51000.0,
    low_p: float = 49500.0,
    close_p: float = 50500.0,
    volume: float = 100.0,
    is_closed: bool = False,
    quote_volume: float = 5000000.0,
    trade_count: int = 150,
) -> Dict[str, Any]:
    """Generate raw Binance WebSocket kline payload dictionary."""
    effective_high = max(high_p, open_p, close_p)
    effective_low = min(low_p, open_p, close_p)
    return {
        "e": "kline",
        "E": start_time_ms + 3599000,
        "s": symbol,
        "k": {
            "t": start_time_ms,
            "T": start_time_ms + 3599999,
            "s": symbol,
            "i": interval,
            "f": 1,
            "L": trade_count,
            "o": str(open_p),
            "c": str(close_p),
            "h": str(effective_high),
            "l": str(effective_low),
            "v": str(volume),
            "n": trade_count,
            "x": is_closed,
            "q": str(quote_volume),
            "V": str(volume / 2),
            "Q": str(quote_volume / 2),
            "B": "0",
        },
    }


def test_1_valid_completed_candle_normalization():
    """Requirement 1: Valid completed kline payload normalizes to canonical Candle."""
    payload = make_raw_kline_payload(is_closed=True)
    kline = normalize_binance_kline(payload)

    assert isinstance(kline, NormalizedKline)
    assert kline.is_closed is True
    assert isinstance(kline.candle, Candle)
    assert kline.candle.symbol == "BTCUSDT"
    assert kline.candle.timeframe == "1h"
    assert kline.candle.open == 50000.0
    assert kline.candle.high == 51000.0
    assert kline.candle.low == 49500.0
    assert kline.candle.close == 50500.0
    assert kline.candle.volume == 100.0


def test_2_unfinished_candle_is_ignored():
    """Requirement 2: Unfinished candle (is_closed=False) is not emitted as a completed candle."""
    observer = LiveMarketObserver()
    emitted_candles: List[Candle] = []
    observer.on_candle_completed = lambda c, k: emitted_candles.append(c)

    payload = make_raw_kline_payload(is_closed=False)
    res = observer.process_raw_message(payload)

    assert res is None
    assert len(emitted_candles) == 0
    assert observer.completed_count == 0
    assert observer.forming_kline is not None
    assert observer.forming_kline.candle.close == 50500.0


def test_3_multiple_updates_to_same_forming_candle():
    """Requirement 3: Sequential updates to a forming candle update state without emitting."""
    observer = LiveMarketObserver()
    start_ms = 1767225600000

    # Tick 1
    observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, close_p=50100.0, is_closed=False))
    assert observer.forming_kline.candle.close == 50100.0
    assert observer.completed_count == 0

    # Tick 2
    observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, close_p=50350.0, is_closed=False))
    assert observer.forming_kline.candle.close == 50350.0
    assert observer.completed_count == 0

    # Tick 3
    observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, close_p=50800.0, is_closed=False))
    assert observer.forming_kline.candle.close == 50800.0
    assert observer.completed_count == 0


def test_4_completed_candle_emitted_exactly_once():
    """Requirement 4: When is_closed=True arrives, completed candle is emitted exactly once."""
    observer = LiveMarketObserver()
    emitted_candles: List[Candle] = []
    observer.on_candle_completed = lambda c, k: emitted_candles.append(c)
    start_ms = 1767225600000

    # Forming ticks
    observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, close_p=50100.0, is_closed=False))
    observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, close_p=50200.0, is_closed=False))

    # Final closed tick
    final_payload = make_raw_kline_payload(start_time_ms=start_ms, close_p=50500.0, is_closed=True)
    res = observer.process_raw_message(final_payload)

    assert res is not None
    assert len(emitted_candles) == 1
    assert observer.completed_count == 1
    assert observer.latest_completed_candle == res
    assert res.close == 50500.0


def test_5_duplicate_completed_candle_rejected():
    """Requirement 5: Duplicate completed candle with same timestamp is ignored."""
    observer = LiveMarketObserver()
    start_ms = 1767225600000

    payload = make_raw_kline_payload(start_time_ms=start_ms, is_closed=True)
    res1 = observer.process_raw_message(payload)
    assert res1 is not None
    assert observer.completed_count == 1

    # Send duplicate
    res2 = observer.process_raw_message(payload)
    assert res2 is None
    assert observer.completed_count == 1
    assert observer.duplicates_count == 1


def test_6_chronological_ordering():
    """Requirement 6: Consecutive completed candles in chronological order are processed."""
    observer = LiveMarketObserver()
    start_ms = 1767225600000

    # Bar 1 (00:00)
    c1 = observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, is_closed=True))
    assert c1 is not None

    # Bar 2 (01:00)
    c2 = observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms + 3600000, is_closed=True))
    assert c2 is not None
    assert observer.completed_count == 2
    assert c2.timestamp > c1.timestamp


def test_7_malformed_ohlc_rejected():
    """Requirement 7: Malformed OHLC payload (e.g. High < Open) is rejected."""
    observer = LiveMarketObserver()
    rejections: List[Dict[str, Any]] = []
    observer.on_rejection = lambda reason, details: rejections.append({"reason": reason, "details": details})

    # Explicit raw payload where High (49000.0) is lower than Open (50000.0)
    bad_payload = {
        "e": "kline",
        "E": 1767225600000 + 3599000,
        "s": "BTCUSDT",
        "k": {
            "t": 1767225600000,
            "T": 1767225600000 + 3599999,
            "s": "BTCUSDT",
            "i": "1h",
            "o": "50000.0",
            "c": "49500.0",
            "h": "49000.0",  # High < Open -> Invalid OHLC
            "l": "48000.0",
            "v": "100.0",
            "x": True,
        },
    }
    res = observer.process_raw_message(bad_payload)

    assert res is None
    assert observer.completed_count == 0
    assert observer.rejections_count == 1
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "MALFORMED_PAYLOAD"


def test_8_invalid_volume_rejected():
    """Requirement 8: Negative volume is rejected."""
    observer = LiveMarketObserver()
    bad_payload = make_raw_kline_payload(volume=-10.0, is_closed=True)
    res = observer.process_raw_message(bad_payload)

    assert res is None
    assert observer.rejections_count == 1


def test_9_10_candle_gap_detected_and_no_fabrication():
    """Requirements 9, 10: 1H interval gap is detected without fabricating missing candles."""
    observer = LiveMarketObserver()
    detected_gaps: List[Any] = []
    observer.on_gap_detected = lambda prev_t, next_t, gap: detected_gaps.append((prev_t, next_t, gap))

    start_ms = 1767225600000  # 00:00 UTC

    # Bar 1 at 00:00
    observer.process_raw_message(make_raw_kline_payload(start_time_ms=start_ms, is_closed=True))

    # Bar 2 at 03:00 (Gap of 3 hours, missing 01:00 and 02:00)
    gap_ms = start_ms + (3 * 3600000)
    res_gap = observer.process_raw_message(make_raw_kline_payload(start_time_ms=gap_ms, is_closed=True))

    assert res_gap is not None
    assert observer.completed_count == 2
    assert observer.gaps_count == 1
    assert len(detected_gaps) == 1
    assert detected_gaps[0][2] == timedelta(hours=3)


def test_11_12_reconnect_deduplication():
    """Requirements 11, 12: Reconnection does not re-emit already completed candles."""
    observer = LiveMarketObserver()
    start_ms = 1767225600000

    # Emit completed candle before disconnect
    payload = make_raw_kline_payload(start_time_ms=start_ms, is_closed=True)
    observer.process_raw_message(payload)
    assert observer.completed_count == 1

    # Simulate reconnect replay of same completed candle
    replayed = observer.process_raw_message(payload)
    assert replayed is None
    assert observer.completed_count == 1
    assert observer.duplicates_count == 1


def test_13_clean_shutdown():
    """Requirement 13: Clean stop without errors."""
    observer = LiveMarketObserver()
    observer.stop()
    assert not observer.ws_client.is_running


def test_14_15_16_journal_integration_metadata_propagation():
    """Requirements 14, 15, 16: Completed candle records MarketObservationRecord with session ID & mode."""
    journal = TradingJournal()
    session_id = "test_live_session_99"
    observer = LiveMarketObserver(session_id=session_id, journal=journal)

    start_ms = 1767225600000
    payload = make_raw_kline_payload(start_time_ms=start_ms, close_p=51250.0, is_closed=True)
    observer.process_raw_message(payload)

    records = journal.read_all()
    assert len(records) == 1
    rec = records[0]
    assert rec.record_type == JournalRecordType.MARKET_OBSERVATION
    assert rec.run_id == session_id
    assert rec.execution_mode == "LIVE_OBSERVER"
    assert rec.symbol == "BTCUSDT"
    assert rec.close == 51250.0


def test_17_exchange_timestamps_preserved():
    """Requirement 17: Exchange start and close timestamps are correctly mapped to UTC."""
    payload = make_raw_kline_payload(start_time_ms=1767225600000, is_closed=True)
    kline = normalize_binance_kline(payload)

    assert kline.candle.timestamp == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert kline.close_time == datetime(2026, 1, 1, 0, 59, 59, 999000, tzinfo=timezone.utc)


def test_18_multiple_consecutive_completed_candles():
    """Requirement 18: Processing 10 consecutive hourly bars completes successfully."""
    observer = LiveMarketObserver()
    start_ms = 1767225600000

    for i in range(10):
        ts = start_ms + (i * 3600000)
        c = observer.process_raw_message(make_raw_kline_payload(start_time_ms=ts, close_p=50000.0 + i, is_closed=True))
        assert c is not None

    assert observer.completed_count == 10
    assert observer.duplicates_count == 0
    assert observer.gaps_count == 0


def test_19_malformed_websocket_payload_handled_safely():
    """Requirement 19: Malformed JSON string or invalid payload does not crash observer."""
    observer = LiveMarketObserver()
    res1 = observer.process_raw_message("not valid json")
    assert res1 is None

    res2 = observer.process_raw_message({"invalid": "schema"})
    assert res2 is None
    assert observer.rejections_count == 2


def test_20_deterministic_mocked_sequence():
    """Requirement 20: Processing identical sequence across two observers yields identical state."""
    obs_1 = LiveMarketObserver()
    obs_2 = LiveMarketObserver()

    start_ms = 1767225600000
    events = [
        make_raw_kline_payload(start_time_ms=start_ms, close_p=50100.0, is_closed=False),
        make_raw_kline_payload(start_time_ms=start_ms, close_p=50500.0, is_closed=True),
        make_raw_kline_payload(start_time_ms=start_ms + 3600000, close_p=51000.0, is_closed=True),
    ]

    for ev in events:
        obs_1.process_raw_message(ev)
        obs_2.process_raw_message(ev)

    assert obs_1.completed_count == obs_2.completed_count == 2
    assert obs_1.latest_completed_candle == obs_2.latest_completed_candle
