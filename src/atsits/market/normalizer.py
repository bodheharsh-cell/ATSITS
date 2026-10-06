"""Normalizer converting raw exchange WebSocket kline payloads into canonical Candle models."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Union
from atsits.models.market_data import Candle


@dataclass(frozen=True)
class NormalizedKline:
    """Normalized real-time kline update with exchange metadata."""

    candle: Candle
    is_closed: bool
    event_time: datetime
    close_time: datetime
    trade_count: int
    quote_volume: float
    raw_payload: Dict[str, Any]


def normalize_binance_kline(raw_data: Union[Dict[str, Any], str]) -> NormalizedKline:
    """Normalize a raw Binance WebSocket kline payload.

    Expected payload formats:
    - Direct stream payload: {"e": "kline", "E": ..., "s": "BTCUSDT", "k": {...}}
    - Combined stream payload: {"stream": "btcusdt@kline_1h", "data": {"e": "kline", ...}}

    Args:
        raw_data: Raw JSON string or parsed dictionary from Binance WebSocket.

    Returns:
        NormalizedKline instance containing the canonical Candle and metadata.

    Raises:
        ValueError: If payload structure is invalid, missing required fields, or fails OHLC validation.
    """
    if isinstance(raw_data, str):
        try:
            payload = json.loads(raw_data)
        except Exception as err:
            raise ValueError(f"Malformed JSON payload: {err}") from err
    elif isinstance(raw_data, dict):
        payload = raw_data
    else:
        raise ValueError(f"Expected dict or JSON string, got {type(raw_data).__name__}")

    # Handle combined stream envelope
    if "data" in payload and isinstance(payload["data"], dict) and "k" in payload["data"]:
        payload = payload["data"]

    if not isinstance(payload, dict) or "k" not in payload:
        raise ValueError(f"Payload does not contain expected 'k' (kline) object: {payload}")

    k = payload["k"]
    if not isinstance(k, dict):
        raise ValueError(f"Field 'k' must be a dictionary, got {type(k).__name__}")

    try:
        symbol = str(k.get("s", payload.get("s", ""))).strip().upper()
        if not symbol:
            raise ValueError("Missing symbol 's' in kline payload")

        interval = str(k.get("i", "")).strip().lower()
        if not interval:
            raise ValueError("Missing interval 'i' in kline payload")

        start_time_ms = int(k["t"])
        close_time_ms = int(k["T"])
        event_time_ms = int(payload.get("E", close_time_ms))

        start_dt = datetime.fromtimestamp(start_time_ms / 1000.0, tz=timezone.utc)
        close_dt = datetime.fromtimestamp(close_time_ms / 1000.0, tz=timezone.utc)
        event_dt = datetime.fromtimestamp(event_time_ms / 1000.0, tz=timezone.utc)

        open_p = float(k["o"])
        high_p = float(k["h"])
        low_p = float(k["l"])
        close_p = float(k["c"])
        vol = float(k["v"])
        quote_vol = float(k.get("q", 0.0))
        trade_count = int(k.get("n", 0))
        is_closed = bool(k.get("x", False))

        # Instantiate canonical Phase 0/1 Candle model (enforces strict OHLC bounds)
        candle = Candle(
            symbol=symbol,
            timeframe=interval,
            timestamp=start_dt,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=vol,
        )

        return NormalizedKline(
            candle=candle,
            is_closed=is_closed,
            event_time=event_dt,
            close_time=close_dt,
            trade_count=trade_count,
            quote_volume=quote_vol,
            raw_payload=payload,
        )
    except KeyError as err:
        raise ValueError(f"Missing required field {err} in kline payload") from err
    except (TypeError, ValueError) as err:
        raise ValueError(f"Invalid numeric value or constraint in kline payload: {err}") from err
