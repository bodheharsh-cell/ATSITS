"""Tests for historical data loader and validation (Requirement 25)."""

from datetime import datetime, timezone
from pathlib import Path
import pytest
from atsits.data.loader import load_candles_from_csv, parse_timestamp, validate_candle_series
from atsits.models.market_data import Candle
from tests.conftest import make_candle


def test_parse_timestamp_iso_and_epochs():
    """Verify timestamp parsing from ISO strings and unix epochs."""
    dt_iso = parse_timestamp("2026-01-01T12:00:00Z")
    assert dt_iso == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    # Seconds epoch
    dt_s = parse_timestamp(1767268800)
    assert dt_s.year == 2026

    # Milliseconds epoch
    dt_ms = parse_timestamp(1767268800000)
    assert dt_ms.year == 2026


def test_validate_candle_series_valid():
    """Verify valid candle series passes validation."""
    candles = [
        make_candle(0, 100, 105, 95, 102),
        make_candle(1, 102, 106, 100, 104),
        make_candle(2, 104, 108, 103, 107),
    ]
    validate_candle_series(candles)  # Should not raise


def test_validate_candle_series_empty():
    """Verify empty series raises ValueError."""
    with pytest.raises(ValueError, match="empty"):
        validate_candle_series([])


def test_validate_candle_series_duplicates():
    """Verify duplicate timestamps are rejected."""
    c1 = make_candle(0, 100, 105, 95, 102)
    c2 = make_candle(0, 102, 106, 100, 104)  # same timestamp
    with pytest.raises(ValueError, match="Duplicate timestamp"):
        validate_candle_series([c1, c2])


def test_validate_candle_series_out_of_order():
    """Verify out-of-order timestamps are rejected."""
    c1 = make_candle(1, 100, 105, 95, 102)
    c2 = make_candle(0, 102, 106, 100, 104)  # earlier timestamp
    with pytest.raises(ValueError, match="Out-of-order timestamp"):
        validate_candle_series([c1, c2])


def test_validate_candle_series_inconsistent_symbol_timeframe():
    """Verify inconsistent symbols or timeframes are rejected."""
    c1 = make_candle(0, 100, 105, 95, 102, symbol="BTCUSDT")
    c2 = make_candle(1, 102, 106, 100, 104, symbol="ETHUSDT")
    with pytest.raises(ValueError, match="Inconsistent symbol"):
        validate_candle_series([c1, c2])

    c3 = make_candle(0, 100, 105, 95, 102, timeframe="1h")
    c4 = make_candle(1, 102, 106, 100, 104, timeframe="5m")
    with pytest.raises(ValueError, match="Inconsistent timeframe"):
        validate_candle_series([c3, c4])


def test_load_candles_from_csv_success(tmp_path: Path):
    """Verify loading candles from valid CSV file."""
    csv_file = tmp_path / "valid_data.csv"
    csv_content = (
        "timestamp,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,50000.0,50500.0,49500.0,50200.0,10.5\n"
        "2026-01-01T01:00:00Z,50200.0,51000.0,50000.0,50800.0,15.2\n"
        "2026-01-01T02:00:00Z,50800.0,51200.0,50600.0,51100.0,12.0\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    candles = load_candles_from_csv(csv_file, symbol="BTCUSDT", timeframe="1h")
    assert len(candles) == 3
    assert candles[0].open == 50000.0
    assert candles[1].high == 51000.0
    assert candles[2].close == 51100.0


def test_load_candles_from_csv_missing_file():
    """Verify FileNotFoundError for missing CSV file."""
    with pytest.raises(FileNotFoundError):
        load_candles_from_csv("non_existent_data_file.csv")


def test_load_candles_from_csv_malformed_ohlc(tmp_path: Path):
    """Verify malformed OHLC values in CSV are rejected."""
    csv_file = tmp_path / "bad_ohlc.csv"
    # High is lower than Low
    csv_content = (
        "timestamp,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,50000.0,49000.0,51000.0,50200.0,10.5\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed row"):
        load_candles_from_csv(csv_file)
