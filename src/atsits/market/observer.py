"""Live Market Observer managing forming klines, completed candles, gaps, and duplicate protection."""

from collections import deque
from datetime import datetime, timedelta
import logging
from typing import Any, Callable, Dict, Optional, Set, Union
from atsits.journal.models import MarketObservationRecord
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline, normalize_binance_kline
from atsits.market.websocket import BinanceWebSocketClient
from atsits.models.market_data import Candle

logger = logging.getLogger(__name__)


class LiveMarketObserver:
    """Real-time market observer for BTCUSDT (and other public streams).

    Core Responsibilities:
    1. Receive live real-time klines from WebSocket stream.
    2. Maintain state of the currently forming candle without emitting it.
    3. Validate and emit completed candles exactly once upon closure (kline.is_closed == True).
    4. Detect and report missing interval gaps without fabricating data.
    5. Deduplicate completed candles across reconnects.
    6. Record factual market observations into the TradingJournal.
    7. Strictly observer-only: NO order execution capabilities.
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        session_id: str = "observer_session_001",
        journal: Optional[TradingJournal] = None,
        expected_interval: Optional[timedelta] = None,
        max_seen_history: int = 1000,
        ws_base_url: Optional[str] = None,
        on_candle_completed: Optional[Callable[[Candle, NormalizedKline], None]] = None,
        on_kline_update: Optional[Callable[[NormalizedKline], None]] = None,
        on_gap_detected: Optional[Callable[[datetime, datetime, timedelta], None]] = None,
        on_rejection: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.symbol: str = symbol.upper()
        self.interval: str = interval.lower()
        self.session_id: str = session_id
        self.journal: Optional[TradingJournal] = journal

        if expected_interval is not None:
            self.expected_interval: timedelta = expected_interval
        elif self.interval == "1h":
            self.expected_interval = timedelta(hours=1)
        elif self.interval == "1m":
            self.expected_interval = timedelta(minutes=1)
        else:
            self.expected_interval = timedelta(hours=1)

        self.max_seen_history: int = max_seen_history
        self.on_candle_completed = on_candle_completed
        self.on_kline_update = on_kline_update
        self.on_gap_detected = on_gap_detected
        self.on_rejection = on_rejection

        # Internal state
        self.forming_kline: Optional[NormalizedKline] = None
        self.latest_completed_candle: Optional[Candle] = None
        self.last_completed_timestamp: Optional[datetime] = None

        # Statistics
        self.completed_count: int = 0
        self.duplicates_count: int = 0
        self.gaps_count: int = 0
        self.rejections_count: int = 0
        self._rec_counter: int = 0

        # Bounded deduplication tracking
        self._seen_queue: deque = deque(maxlen=max_seen_history)
        self._seen_set: Set[datetime] = set()

        # WebSocket client
        self.ws_client: BinanceWebSocketClient = BinanceWebSocketClient(
            symbol=self.symbol,
            interval=self.interval,
            base_url=ws_base_url,
            on_message=self.process_raw_message,
            on_connect=lambda: logger.info(f"Observer session {self.session_id} connected"),
            on_disconnect=lambda: logger.warning(f"Observer session {self.session_id} disconnected"),
            on_error=lambda e: logger.error(f"Observer session {self.session_id} error: {e}"),
        )

    def _mark_seen(self, dt: datetime) -> None:
        """Add timestamp to bounded deduplication set."""
        if len(self._seen_queue) >= self.max_seen_history:
            oldest = self._seen_queue.popleft()
            self._seen_set.discard(oldest)
        self._seen_queue.append(dt)
        self._seen_set.add(dt)

    def process_raw_message(self, raw_msg: Union[Dict[str, Any], str]) -> Optional[Candle]:
        """Process a raw WebSocket message payload.

        Args:
            raw_msg: Raw JSON string or dictionary from market data feed.

        Returns:
            The completed Candle if the kline closed on this message, otherwise None.
        """
        try:
            kline = normalize_binance_kline(raw_msg)
        except Exception as err:
            self.rejections_count += 1
            logger.warning(f"Rejected malformed kline payload: {err}")
            if self.on_rejection:
                try:
                    self.on_rejection("MALFORMED_PAYLOAD", {"error": str(err)})
                except Exception as cb_err:
                    logger.error(f"Error in on_rejection callback: {cb_err}")
            return None

        # 1. Update forming candle state
        self.forming_kline = kline
        if self.on_kline_update:
            try:
                self.on_kline_update(kline)
            except Exception as cb_err:
                logger.error(f"Error in on_kline_update callback: {cb_err}")

        # 2. If the kline is NOT closed, do NOT emit completed candle
        if not kline.is_closed:
            return None

        # 3. Handle completed candle
        candle = kline.candle
        candle_ts = candle.timestamp

        # Check for duplicate completed candle
        if candle_ts in self._seen_set:
            self.duplicates_count += 1
            logger.warning(f"Duplicate completed candle ignored for timestamp {candle_ts.isoformat()}")
            return None

        # Check for out-of-order or gap anomalies
        if self.last_completed_timestamp is not None:
            if candle_ts < self.last_completed_timestamp:
                self.rejections_count += 1
                logger.warning(
                    f"Out-of-order completed candle rejected: {candle_ts.isoformat()} is before {self.last_completed_timestamp.isoformat()}"
                )
                if self.on_rejection:
                    try:
                        self.on_rejection(
                            "OUT_OF_ORDER_CANDLE",
                            {
                                "candle_ts": candle_ts.isoformat(),
                                "last_ts": self.last_completed_timestamp.isoformat(),
                            },
                        )
                    except Exception as cb_err:
                        logger.error(f"Error in on_rejection callback: {cb_err}")
                return None

            diff = candle_ts - self.last_completed_timestamp
            if diff > self.expected_interval:
                self.gaps_count += 1
                logger.warning(
                    f"Candle interval gap detected: {self.last_completed_timestamp.isoformat()} -> {candle_ts.isoformat()} (gap: {diff})"
                )
                if self.on_gap_detected:
                    try:
                        self.on_gap_detected(self.last_completed_timestamp, candle_ts, diff)
                    except Exception as cb_err:
                        logger.error(f"Error in on_gap_detected callback: {cb_err}")

        # Mark seen and update state
        self._mark_seen(candle_ts)
        self.last_completed_timestamp = candle_ts
        self.latest_completed_candle = candle
        self.completed_count += 1
        self._rec_counter += 1

        logger.info(
            f"Completed candle received: {candle.symbol} {candle.timeframe} @ {candle_ts.isoformat()} (Close: {candle.close})"
        )

        # 4. Record into factual TradingJournal if configured
        if self.journal is not None:
            self.journal.append(
                MarketObservationRecord(
                    record_id=f"{self.session_id}_obs_{self._rec_counter:05d}",
                    timestamp=candle_ts,
                    run_id=self.session_id,
                    strategy_version="1.0.0",
                    execution_mode="LIVE_OBSERVER",
                    symbol=candle.symbol,
                    timeframe=candle.timeframe,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                )
            )

        # 5. Emit completed candle callback
        if self.on_candle_completed:
            try:
                self.on_candle_completed(candle, kline)
            except Exception as cb_err:
                logger.error(f"Error in on_candle_completed callback: {cb_err}")

        return candle

    def start(self, in_background: bool = True) -> None:
        """Start the live market observer WebSocket stream."""
        logger.info(f"Starting LiveMarketObserver for {self.symbol}@{self.interval} (Session: {self.session_id})")
        self.ws_client.start(in_background=in_background)

    def stop(self) -> None:
        """Gracefully stop the live market observer."""
        logger.info(f"Stopping LiveMarketObserver (Session: {self.session_id})...")
        self.ws_client.stop()
