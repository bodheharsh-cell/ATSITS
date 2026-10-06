"""Comprehensive tests for Phase 2 Trading Journal (Requirements 1-21)."""

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from pydantic import ValidationError
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.journal.models import (
    JOURNAL_SCHEMA_VERSION,
    EntryRecord,
    ExitRecord,
    JournalRecordType,
    MarketObservationRecord,
    SetupDetectedRecord,
    SetupRejectedRecord,
    TradeRecord,
    deserialize_journal_record,
)
from atsits.journal.storage import TradingJournal
from atsits.models.backtest import BacktestConfig
from tests.conftest import make_candle, make_trending_candles


def build_test_candles():
    """Helper creating 60 uptrend bars + pullback (bar 60) + confirmation (bar 61) + entry (bar 62) + exit (bar 63)."""
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    # Pullback bar 60
    pb = make_candle(60, open_p=210.0, high_p=212.0, low_p=185.0, close_p=205.0)
    # Confirmation bar 61
    conf = make_candle(61, open_p=206.0, high_p=220.0, low_p=205.0, close_p=218.0)
    # Entry bar 62
    entry = make_candle(62, open_p=220.0, high_p=230.0, low_p=218.0, close_p=228.0)
    # Exit bar 63 (TP hit at 290.0)
    exit_c = make_candle(63, open_p=228.0, high_p=295.0, low_p=225.0, close_p=292.0)
    return candles + [pb, conf, entry, exit_c]


def test_1_2_3_record_creation_schema_version_record_id():
    """Requirements 1, 2, 3: Create journal records, verify schema version and record ID."""
    now = datetime.now(timezone.utc)
    rec = SetupDetectedRecord(
        record_id="run01_setup_00001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=now,
        pullback_high=212.0,
        pullback_low=185.0,
        confirmation_timestamp=now,
        ema20=200.0,
        ema50=180.0,
        facts={"stop_price": 185.0},
    )
    assert rec.schema_version == JOURNAL_SCHEMA_VERSION
    assert rec.schema_version == "1.0.0"
    assert rec.record_id == "run01_setup_00001"
    assert rec.record_type == JournalRecordType.SETUP_DETECTED


def test_4_5_immutability_and_nested_immutability():
    """Requirements 4, 5: Record fields and nested facts dictionaries cannot be mutated."""
    now = datetime.now(timezone.utc)
    facts_dict = {"param": "value", "nested": {"level": 1}}
    rec = SetupDetectedRecord(
        record_id="run01_setup_00002",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=now,
        pullback_high=212.0,
        pullback_low=185.0,
        confirmation_timestamp=now,
        ema20=200.0,
        ema50=180.0,
        facts=facts_dict,
    )

    # 1. Field mutation blocked
    with pytest.raises(ValidationError):
        rec.symbol = "ETHUSDT"  # type: ignore

    # 2. Top-level facts mutation blocked
    with pytest.raises(TypeError, match="does not support item assignment"):
        rec.facts["param"] = "mutated"  # type: ignore

    # 3. Nested facts mutation blocked
    with pytest.raises(TypeError, match="does not support item assignment"):
        rec.facts["nested"]["level"] = 2  # type: ignore


def test_6_json_serialization_deserialization():
    """Requirement 6: Serialization and deserialization roundtrip for all record types."""
    now = datetime.now(timezone.utc)
    entry_rec = EntryRecord(
        record_id="run01_entry_00001",
        trade_id="trd-0001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        price=220.0,
        raw_price=220.0,
        quantity=0.5,
        stop_price=185.0,
        target_price=290.0,
        risk_amount=100.0,
        equity_before=10000.0,
    )
    json_str = entry_rec.model_dump_json()
    reconstructed = deserialize_journal_record(json_str)
    assert isinstance(reconstructed, EntryRecord)
    assert reconstructed.record_id == entry_rec.record_id
    assert reconstructed.price == 220.0
    assert reconstructed.trade_id == "trd-0001"


def test_7_8_append_and_read_all(tmp_path: Path):
    """Requirements 7, 8: Append records to TradingJournal and read them back."""
    journal_file = tmp_path / "test_journal.jsonl"
    journal = TradingJournal(file_path=journal_file)

    now = datetime.now(timezone.utc)
    r1 = MarketObservationRecord(
        record_id="run01_obs_00001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=10.0,
    )
    r2 = SetupRejectedRecord(
        record_id="run01_rej_00001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        reason="INVALID_STOP_AT_OPEN",
        details={"open": 180.0, "stop": 185.0},
    )

    journal.append(r1)
    journal.append(r2)

    assert journal.count() == 2
    records = journal.read_all()
    assert len(records) == 2
    assert records[0].record_id == "run01_obs_00001"
    assert records[1].record_id == "run01_rej_00001"

    # Verify reload from disk into a fresh TradingJournal instance
    journal_reloaded = TradingJournal(file_path=journal_file)
    assert journal_reloaded.count() == 2
    assert journal_reloaded.read_all()[1].record_type == JournalRecordType.SETUP_REJECTED


def test_9_filtering(tmp_path: Path):
    """Requirement 9: Filtering records by symbol, strategy_version, record_type, trade_id, run_id."""
    journal = TradingJournal()
    now = datetime.now(timezone.utc)

    r1 = EntryRecord(
        record_id="r1",
        trade_id="trd-001",
        timestamp=now,
        run_id="run_A",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        price=100.0,
        raw_price=100.0,
        quantity=1.0,
        stop_price=90.0,
        target_price=120.0,
        risk_amount=10.0,
        equity_before=1000.0,
    )
    r2 = EntryRecord(
        record_id="r2",
        trade_id="trd-002",
        timestamp=now,
        run_id="run_B",
        strategy_version="2.0.0",
        symbol="ETHUSDT",
        timeframe="1h",
        direction="SHORT",
        price=2000.0,
        raw_price=2000.0,
        quantity=0.1,
        stop_price=2100.0,
        target_price=1800.0,
        risk_amount=10.0,
        equity_before=1000.0,
    )

    journal.append_many([r1, r2])

    assert len(journal.filter_records(symbol="BTCUSDT")) == 1
    assert len(journal.filter_records(symbol="ETHUSDT")) == 1
    assert len(journal.filter_records(run_id="run_A")) == 1
    assert len(journal.filter_records(strategy_version="2.0.0")) == 1
    assert len(journal.filter_records(trade_id="trd-001")) == 1
    assert len(journal.filter_records(record_type=JournalRecordType.ENTRY)) == 2
    assert len(journal.filter_records(record_type=JournalRecordType.EXIT)) == 0


def test_10_trade_reconstruction():
    """Requirement 10: Complete trade lifecycle retrieval by trade_id."""
    journal = TradingJournal()
    now = datetime.now(timezone.utc)

    entry = EntryRecord(
        record_id="r1",
        trade_id="trd-001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        price=100.0,
        raw_price=100.0,
        quantity=1.0,
        stop_price=90.0,
        target_price=120.0,
        risk_amount=10.0,
        equity_before=1000.0,
    )
    exit_rec = ExitRecord(
        record_id="r2",
        trade_id="trd-001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        exit_price=120.0,
        raw_exit_price=120.0,
        exit_reason="TP_HIT",
        quantity=1.0,
        gross_pnl=20.0,
        fees=0.0,
        slippage=0.0,
        net_pnl=20.0,
        equity_after=1020.0,
    )
    trade_rec = TradeRecord(
        record_id="r3",
        trade_id="trd-001",
        timestamp=now,
        run_id="run01",
        strategy_version="1.0.0",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="LONG",
        pullback_timestamp=now,
        confirmation_timestamp=now,
        entry_timestamp=now,
        entry_price=100.0,
        stop_price=90.0,
        target_price=120.0,
        quantity=1.0,
        risk_amount=10.0,
        exit_timestamp=now,
        exit_price=120.0,
        exit_reason="TP_HIT",
        gross_pnl=20.0,
        fees=0.0,
        slippage=0.0,
        net_pnl=20.0,
        r_multiple=2.0,
        equity_before=1000.0,
        equity_after=1020.0,
    )

    journal.append_many([entry, exit_rec, trade_rec])
    lifecycle = journal.get_trade_lifecycle("trd-001")
    assert len(lifecycle) == 3
    types = [r.record_type for r in lifecycle]
    assert types == [JournalRecordType.ENTRY, JournalRecordType.EXIT, JournalRecordType.TRADE]


def test_11_12_13_14_15_16_17_18_backtest_journal_lifecycle():
    """Requirements 11-18: Full backtest integration, metadata propagation, and lifecycle recording."""
    candles = build_test_candles()
    journal = TradingJournal()
    engine = BacktestEngine(config=BacktestConfig(initial_equity=10000.0, risk_pct=0.01))

    result = engine.run(candles, run_id="bt_run_100", journal=journal)

    assert result.number_of_trades == 1
    records = journal.read_all()
    assert len(records) >= 4  # SETUP_DETECTED, ENTRY, EXIT, TRADE

    # Check run_id, strategy_version, execution_mode propagation
    for r in records:
        assert r.run_id == "bt_run_100"
        assert r.strategy_version == "1.0.0"
        assert r.execution_mode == "BACKTEST"
        assert r.symbol == "BTCUSDT"

    # Verify record sequence
    types = [r.record_type for r in records]
    assert JournalRecordType.SETUP_DETECTED in types
    assert JournalRecordType.ENTRY in types
    assert JournalRecordType.EXIT in types
    assert JournalRecordType.TRADE in types

    # Verify trade record contents
    trades = journal.get_trades(run_id="bt_run_100")
    assert len(trades) == 1
    t = trades[0]
    assert t.trade_id == "trd-0001"
    assert t.direction == "LONG"
    assert t.exit_reason == "TP_HIT"
    assert t.r_multiple == 2.0


def test_15_rejected_setup_journal_recording():
    """Requirement 15: Rejected setups are recorded in journal."""
    candles = make_trending_candles(60, start_price=100.0, step=2.0)
    pb = make_candle(60, open_p=210.0, high_p=212.0, low_p=185.0, close_p=205.0)
    conf = make_candle(61, open_p=206.0, high_p=220.0, low_p=205.0, close_p=218.0)
    # Entry candle gaps below SL 185.0
    bad_entry = make_candle(62, open_p=180.0, high_p=184.0, low_p=175.0, close_p=182.0)

    journal = TradingJournal()
    engine = BacktestEngine()
    result = engine.run(candles + [pb, conf, bad_entry], run_id="bt_rej_run", journal=journal)

    assert result.number_of_trades == 0
    rej_records = journal.filter_records(record_type=JournalRecordType.SETUP_REJECTED)
    assert len(rej_records) == 1
    rej = rej_records[0]
    assert isinstance(rej, SetupRejectedRecord)
    assert rej.reason == "INVALID_STOP_AT_OPEN"
    assert rej.details["open_price"] == 180.0
    assert rej.details["stop_price"] == 185.0


def test_19_journal_with_real_historical_data():
    """Requirement 19: TradingJournal execution against real historical BTCUSDT dataset."""
    csv_path = Path("data/btcusdt_1h.csv")
    if not csv_path.is_file():
        pytest.skip("Historical data CSV not found")

    candles = load_candles_from_csv(csv_path)
    journal = TradingJournal()
    engine = BacktestEngine()
    result = engine.run(candles, run_id="real_btc_run", journal=journal)

    assert result.number_of_trades == 201
    trades = journal.get_trades()
    assert len(trades) == 201

    entries = journal.filter_records(record_type=JournalRecordType.ENTRY)
    exits = journal.filter_records(record_type=JournalRecordType.EXIT)
    assert len(entries) == 201
    assert len(exits) == 201


def test_20_deterministic_journal_generation():
    """Requirement 20: Repeated backtests produce bit-for-bit identical journal records."""
    candles = build_test_candles()

    journal_1 = TradingJournal()
    journal_2 = TradingJournal()

    engine_1 = BacktestEngine()
    engine_2 = BacktestEngine()

    engine_1.run(candles, run_id="det_run", journal=journal_1)
    engine_2.run(candles, run_id="det_run", journal=journal_2)

    dump_1 = [r.model_dump() for r in journal_1.read_all()]
    dump_2 = [r.model_dump() for r in journal_2.read_all()]
    assert dump_1 == dump_2


def test_21_no_strategy_behavior_changed():
    """Requirement 21: Backtest results with and without journal are completely identical."""
    candles = build_test_candles()

    engine_no_journal = BacktestEngine()
    res_no_journal = engine_no_journal.run(candles)

    journal = TradingJournal()
    engine_with_journal = BacktestEngine()
    res_with_journal = engine_with_journal.run(candles, journal=journal)

    assert res_no_journal.model_dump() == res_with_journal.model_dump()
