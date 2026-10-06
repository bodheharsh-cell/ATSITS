"""Historical data ingestion and validation."""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Union
from atsits.models.market_data import Candle


def parse_timestamp(val: Union[str, int, float]) -> datetime:
    """Parse a timestamp from ISO string or unix epoch (seconds or milliseconds)."""
    if isinstance(val, (int, float)):
        # If value is large (e.g. > 1e11), treat as milliseconds
        if val > 1e11:
            return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(val, tz=timezone.utc)

    val_str = str(val).strip()
    # Try parsing numeric string
    try:
        num = float(val_str)
        if num > 1e11:
            return datetime.fromtimestamp(num / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(num, tz=timezone.utc)
    except ValueError:
        pass

    # Try ISO formats
    if val_str.endswith("Z"):
        val_str = val_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(val_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validate_candle_series(candles: Sequence[Candle]) -> None:
    """Validate input integrity of a sequence of candles.

    Checks:
    - Sequence is not empty.
    - Strictly increasing chronological order (no out-of-order bars).
    - No duplicate timestamps.
    - Consistent symbol and timeframe across all candles.

    Raises:
        ValueError: If any validation condition is violated.
    """
    if not candles:
        raise ValueError("Candle series is empty")

    expected_symbol = candles[0].symbol
    expected_timeframe = candles[0].timeframe
    last_timestamp: Optional[datetime] = None

    for i, candle in enumerate(candles):
        if candle.symbol != expected_symbol:
            raise ValueError(
                f"Inconsistent symbol at index {i}: expected '{expected_symbol}', got '{candle.symbol}'"
            )
        if candle.timeframe != expected_timeframe:
            raise ValueError(
                f"Inconsistent timeframe at index {i}: expected '{expected_timeframe}', got '{candle.timeframe}'"
            )

        if last_timestamp is not None:
            if candle.timestamp == last_timestamp:
                raise ValueError(f"Duplicate timestamp detected at index {i}: {candle.timestamp}")
            if candle.timestamp < last_timestamp:
                raise ValueError(
                    f"Out-of-order timestamp detected at index {i}: {candle.timestamp} is before {last_timestamp}"
                )

        last_timestamp = candle.timestamp


def load_candles_from_csv(
    file_path: Union[str, Path],
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> List[Candle]:
    """Load and validate OHLCV historical candles from a CSV file.

    Expected CSV header variations:
    - Timestamp: 'timestamp', 'datetime', 'time', 'date', 'open_time'
    - Open: 'open', 'o'
    - High: 'high', 'h'
    - Low: 'low', 'l'
    - Close: 'close', 'c'
    - Volume: 'volume', 'v', 'vol'

    Args:
        file_path: Path to CSV file.
        symbol: Symbol identifier for the series.
        timeframe: Timeframe string.

    Returns:
        List of validated Candle objects in chronological order.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If required columns are missing or data is malformed.
    """
    resolved_path = Path(file_path).resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Historical data CSV file not found: {resolved_path}")

    candles: List[Candle] = []

    with open(resolved_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV file is empty or missing headers: {resolved_path}")

        # Normalize header keys to lowercase
        field_map = {name.strip().lower(): name for name in reader.fieldnames if name}

        def find_col(candidates: List[str]) -> str:
            for cand in candidates:
                if cand in field_map:
                    return field_map[cand]
            raise ValueError(
                f"Missing required column (looked for one of {candidates}) in {resolved_path}. "
                f"Available headers: {reader.fieldnames}"
            )

        ts_col = find_col(["timestamp", "datetime", "time", "date", "open_time"])
        open_col = find_col(["open", "o"])
        high_col = find_col(["high", "h"])
        low_col = find_col(["low", "l"])
        close_col = find_col(["close", "c"])
        vol_col = find_col(["volume", "v", "vol"])

        for row_idx, row in enumerate(reader, start=2):
            try:
                ts = parse_timestamp(row[ts_col])
                o = float(row[open_col])
                h = float(row[high_col])
                l = float(row[low_col])
                c = float(row[close_col])
                v = float(row[vol_col])

                candle = Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=ts,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                )
                candles.append(candle)
            except Exception as err:
                raise ValueError(
                    f"Malformed row #{row_idx} in CSV '{resolved_path}': {err}"
                ) from err

    validate_candle_series(candles)
    return candles
