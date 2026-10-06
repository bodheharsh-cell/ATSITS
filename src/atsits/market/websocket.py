"""Public unauthenticated Binance WebSocket client with bounded reconnect and backoff."""

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Dict, Optional
import websockets

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """Public, unauthenticated WebSocket client for Binance market data streams.

    Connects strictly to public market streams (no API keys, no order capabilities).
    Implements reconnection with bounded exponential backoff and graceful shutdown.
    """

    DEFAULT_BASE_URL: str = "wss://stream.binance.com:9443/ws"

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        base_url: Optional[str] = None,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        max_reconnect_delay: float = 30.0,
        initial_reconnect_delay: float = 1.0,
        backoff_factor: float = 2.0,
    ):
        self.symbol: str = symbol.upper()
        self.interval: str = interval.lower()
        self.base_url: str = base_url or self.DEFAULT_BASE_URL
        self.stream_url: str = f"{self.base_url}/{self.symbol.lower()}@kline_{self.interval}"

        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error

        self.max_reconnect_delay = max_reconnect_delay
        self.initial_reconnect_delay = initial_reconnect_delay
        self.backoff_factor = backoff_factor

        self._running: bool = False
        self._connected: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[Any] = None

    @property
    def is_connected(self) -> bool:
        """True if the WebSocket connection is currently active."""
        return self._connected

    @property
    def is_running(self) -> bool:
        """True if the client lifecycle loop is active."""
        return self._running

    async def _listen_loop(self) -> None:
        """Async connection and message processing loop with bounded retry backoff."""
        reconnect_delay = self.initial_reconnect_delay

        while self._running:
            try:
                logger.info(f"Connecting to public market stream: {self.stream_url}")
                async with websockets.connect(
                    self.stream_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    reconnect_delay = self.initial_reconnect_delay
                    logger.info(f"Connected to stream {self.symbol}@{self.interval}")

                    if self.on_connect:
                        try:
                            self.on_connect()
                        except Exception as e:
                            logger.error(f"Error in on_connect callback: {e}")

                    while self._running:
                        try:
                            msg_str = await ws.recv()
                            if isinstance(msg_str, bytes):
                                msg_str = msg_str.decode("utf-8")
                            payload = json.loads(msg_str)

                            if self.on_message:
                                try:
                                    self.on_message(payload)
                                except Exception as cb_err:
                                    logger.error(f"Error in on_message callback: {cb_err}")

                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WebSocket connection closed by remote host")
                            break

            except Exception as err:
                if self._running:
                    logger.warning(f"WebSocket connection error: {err}")
                    if self.on_error:
                        try:
                            self.on_error(err)
                        except Exception as cb_err:
                            logger.error(f"Error in on_error callback: {cb_err}")
            finally:
                self._connected = False
                self._ws = None
                if self.on_disconnect:
                    try:
                        self.on_disconnect()
                    except Exception as e:
                        logger.error(f"Error in on_disconnect callback: {e}")

            if self._running:
                logger.info(f"Reconnecting in {reconnect_delay:.1f}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * self.backoff_factor, self.max_reconnect_delay)

    def start(self, in_background: bool = True) -> None:
        """Start the WebSocket listener.

        Args:
            in_background: If True, spawns a dedicated daemon thread.
        """
        if self._running:
            return

        self._running = True

        def run_thread():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._listen_loop())
            finally:
                self._loop.close()

        if in_background:
            self._thread = threading.Thread(target=run_thread, daemon=True, name="BinanceWSClient")
            self._thread.start()
        else:
            run_thread()

    def stop(self) -> None:
        """Gracefully stop the WebSocket client."""
        if not self._running:
            return

        logger.info("Stopping WebSocket client...")
        self._running = False

        if self._loop and self._loop.is_running():
            # Trigger clean close of active websocket connection
            if self._ws:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        self._connected = False
        logger.info("WebSocket client stopped.")
