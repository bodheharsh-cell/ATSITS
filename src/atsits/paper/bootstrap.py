"""Bootstrap warmup utilities for initializing strategy indicators before live paper trading."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import List, Optional, Sequence, Union
import urllib.error
import urllib.request
from atsits.data.loader import load_candles_from_csv
from atsits.models.market_data import Candle
from atsits.strategies.ema_pullback import EMAPullbackStrategy

logger = logging.getLogger(__name__)

BINANCE_PUBLIC_REST_URL: str = "https://api.binance.com/api/v3/klines"


def fetch_public_binance_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 100,
    base_url: str = BINANCE_PUBLIC_REST_URL,
    timeout_sec: float = 10.0,
) -> List[Candle]:
    """Fetch completed historical klines from Binance public unauthenticated REST API.

    Args:
        symbol: Market pair symbol (e.g. BTCUSDT).
        interval: Kline interval (e.g. 1h).
        limit: Number of candles to fetch (max 1000).
        base_url: REST endpoint URL.
        timeout_sec: Network request timeout in seconds.

    Returns:
        List of completed OHLCV Candle objects in chronological order.
    """
    url = f"{base_url}?symbol={symbol.upper()}&interval={interval.lower()}&limit={limit}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATSITS-PaperTrading/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            raw_data = response.read().decode("utf-8")
            klines = json.loads(raw_data)
    except Exception as err:
        logger.warning(f"Failed to fetch public Binance klines from {url}: {err}")
        raise

    candles: List[Candle] = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    for item in klines:
        open_time_ms = int(item[0])
        close_time_ms = int(item[6])

        # Exclude currently forming (unfinished) candle
        if close_time_ms > now_ms:
            continue

        ts = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc)
        candle = Candle(
            symbol=symbol.upper(),
            timeframe=interval.lower(),
            timestamp=ts,
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
        )
        candles.append(candle)

    logger.info(f"Fetched {len(candles)} completed {interval} warmup candles from public Binance REST API.")
    return candles


def warmup_strategy(
    strategy: EMAPullbackStrategy,
    candles: Sequence[Candle],
) -> int:
    """Feed historical candles sequentially to warm up strategy indicators without opening trades.

    Args:
        strategy: Strategy instance to warm up.
        candles: Historical completed candles.

    Returns:
        Number of candles processed for warmup.
    """
    count = 0
    for candle in candles:
        strategy.on_candle(candle, has_open_position=True)
        count += 1

    logger.info(f"Warmed up strategy {strategy.NAME} with {count} historical candles. Is ready: {strategy.is_ready}")
    return count


def bootstrap_warmup_from_csv(
    strategy: EMAPullbackStrategy,
    csv_path: Union[str, Path],
    max_candles: int = 100,
) -> int:
    """Warm up strategy indicators using a local CSV dataset.

    Args:
        strategy: Strategy instance to warm up.
        csv_path: Path to historical CSV file.
        max_candles: Maximum trailing candles to use for warmup.

    Returns:
        Number of candles warmed up.
    """
    candles = load_candles_from_csv(csv_path)
    warmup_slice = candles[-max_candles:] if len(candles) > max_candles else candles
    return warmup_strategy(strategy, warmup_slice)
