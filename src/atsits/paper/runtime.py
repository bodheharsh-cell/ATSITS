"""Paper Trading Runtime orchestrating market data observation, strategy evaluation, execution, and journaling."""

from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline
from atsits.market.observer import LiveMarketObserver
from atsits.models.market_data import Candle
from atsits.paper.account import PaperAccount
from atsits.paper.bootstrap import (
    bootstrap_warmup_from_csv,
    fetch_public_binance_klines,
    warmup_strategy,
)
from atsits.paper.executor import PaperExecutor
from atsits.strategies.ema_pullback import EMAPullbackStrategy

logger = logging.getLogger(__name__)


class PaperRuntime:
    """Paper Trading Runtime for ATSITS.

    Combines LiveMarketObserver, EMAPullbackStrategy, PaperAccount, PaperExecutor,
    and TradingJournal into a cohesive, unauthenticated, fully simulated paper trading system.
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        session_id: str = "paper_session_001",
        initial_equity: float = 10000.0,
        risk_pct: float = 0.01,
        journal: Optional[TradingJournal] = None,
        strategy: Optional[EMAPullbackStrategy] = None,
        account: Optional[PaperAccount] = None,
        ws_base_url: Optional[str] = None,
        record_observations: bool = True,
    ):
        self.symbol: str = symbol.upper()
        self.interval: str = interval.lower()
        self.session_id: str = session_id

        self.strategy: EMAPullbackStrategy = strategy or EMAPullbackStrategy()
        self.account: PaperAccount = account or PaperAccount(
            initial_equity=initial_equity,
            risk_pct=risk_pct,
        )
        self.journal: Optional[TradingJournal] = journal

        self.executor: PaperExecutor = PaperExecutor(
            account=self.account,
            strategy=self.strategy,
            journal=self.journal,
            run_id=self.session_id,
            record_observations=record_observations,
        )

        # Observer attaches callbacks directly to the executor
        self.observer: LiveMarketObserver = LiveMarketObserver(
            symbol=self.symbol,
            interval=self.interval,
            session_id=self.session_id,
            journal=None,  # We let PaperExecutor log market observations with execution_mode="PAPER"
            ws_base_url=ws_base_url,
            on_kline_update=self.executor.on_tick,
            on_candle_completed=self.executor.on_candle_completed,
            on_gap_detected=self._handle_gap_detected,
            on_rejection=self._handle_observer_rejection,
        )

        self._is_running: bool = False

    def _handle_gap_detected(self, last_ts: datetime, curr_ts: datetime, diff: timedelta) -> None:
        logger.warning(f"Paper Runtime observed candle gap: {last_ts.isoformat()} -> {curr_ts.isoformat()} ({diff})")

    def _handle_observer_rejection(self, reason: str, details: Dict[str, Any]) -> None:
        logger.warning(f"Paper Runtime observer rejected payload: {reason} details={details}")

    def warmup(
        self,
        candles: Optional[Sequence[Candle]] = None,
        csv_path: Optional[Union[str, Path]] = None,
        use_public_rest: bool = False,
        limit: int = 100,
    ) -> int:
        """Warm up strategy indicators before starting live stream.

        Args:
            candles: Optional sequence of historical candles.
            csv_path: Optional path to historical CSV file.
            use_public_rest: Whether to query public Binance REST API.
            limit: Number of candles to fetch if using REST API.

        Returns:
            Number of candles ingested for warmup.
        """
        if candles is not None:
            return warmup_strategy(self.strategy, candles)
        elif csv_path is not None:
            return bootstrap_warmup_from_csv(self.strategy, csv_path, max_candles=limit)
        elif use_public_rest:
            try:
                rest_candles = fetch_public_binance_klines(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=limit,
                )
                return warmup_strategy(self.strategy, rest_candles)
            except Exception as err:
                logger.error(f"Warmup via public REST failed: {err}")
                return 0
        return 0

    def start(self, in_background: bool = True) -> None:
        """Start the live market data observer and paper trading engine."""
        logger.info(f"Starting PaperRuntime for {self.symbol}@{self.interval} (Session: {self.session_id})")
        self._is_running = True
        self.observer.start(in_background=in_background)

    def stop(self) -> None:
        """Gracefully stop live stream and market observer."""
        logger.info(f"Stopping PaperRuntime (Session: {self.session_id})...")
        self.observer.stop()
        self._is_running = False

    def process_raw_message(self, raw_msg: Union[Dict[str, Any], str]) -> Optional[Candle]:
        """Manually inject a raw WebSocket message (useful for testing and deterministic mock feeds).

        Args:
            raw_msg: Raw payload dict or JSON string.

        Returns:
            Completed Candle if bar closed, else None.
        """
        return self.observer.process_raw_message(raw_msg)

    def get_summary(self) -> Dict[str, Any]:
        """Generate a complete status summary of paper account and execution state."""
        return {
            "session_id": self.session_id,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy.VERSION,
            "strategy_is_ready": self.strategy.is_ready,
            "cash_balance": self.account.cash_balance,
            "equity": self.account.get_equity(
                self.observer.forming_kline.candle.close if self.observer.forming_kline else None
            ),
            "realized_pnl": self.account.realized_pnl,
            "total_fees": self.account.total_fees,
            "total_slippage": self.account.total_slippage,
            "trade_count": self.account.trade_count,
            "has_active_position": self.account.has_active_position,
            "active_position": self.account.active_position.model_dump() if self.account.active_position else None,
            "completed_trades_count": len(self.executor.completed_trades_history),
            "rejections_count": len(self.executor.rejections_history),
            "observer_completed_candles": self.observer.completed_count,
            "observer_gaps": self.observer.gaps_count,
        }
