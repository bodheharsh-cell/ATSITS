"""Phase 9: Binance-backed Paper Trading Session.

Manages a paper trading session that uses live Binance market data
for candle feeds and runs the complete strategy pipeline:

    Binance 1H REST klines (completed candles)
        ↓
    EMAExperimentalStrategy.on_candle(candle)  [EMA20 / EMA30]
        ↓
    EntrySignal (if confirmed setup)
        ↓
    PaperExecutor (entry on next bar open, intrabar SL/TP via on_tick)
        ↓
    PaperAccount (position sizing, equity tracking)
        ↓
    TradingJournal (all events: setup, entry, exit, observation)

SECURITY CONTRACT:
- This session CANNOT place, cancel, or modify real Binance orders.
- Real Binance balances are NEVER used as paper account equity.
- Binance credentials are NEVER exposed to Gemini, MCP, browser, or logs.
- The paper account starts with a fixed synthetic equity (default: $10,000).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from atsits.binance.client import BinanceReadOnlyClient, BinanceClientError
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline
from atsits.models.market_data import Candle
from atsits.paper.account import PaperAccount
from atsits.paper.bootstrap import warmup_strategy, fetch_public_binance_klines
from atsits.paper.executor import PaperExecutor
from atsits.paper.models import PaperPosition
from atsits.strategies.ema_pullback import EMAPullbackStrategy, EntrySignal

logger = logging.getLogger(__name__)

# Default session parameters
DEFAULT_SESSION_ID = "PAPER-BINANCE-BTCUSDT-1H"
DEFAULT_INITIAL_EQUITY = 10_000.0


class PaperOrder:
    """Represents a pending or completed paper order."""

    def __init__(
        self,
        order_id: str,
        session_id: str,
        symbol: str,
        side: str,          # BUY or SELL
        order_type: str,    # MARKET
        quantity: float,
        price: float,       # execution price
        stop_price: float,
        target_price: float,
        direction: str,     # LONG or SHORT
        status: str,        # PENDING, FILLED, REJECTED, CANCELLED
        created_at: datetime,
        source: str = "MANUAL",  # MANUAL or STRATEGY
    ) -> None:
        self.order_id = order_id
        self.session_id = session_id
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.price = price
        self.stop_price = stop_price
        self.target_price = target_price
        self.direction = direction
        self.status = status
        self.created_at = created_at
        self.filled_at: Optional[datetime] = None
        self.source = source

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": round(self.quantity, 6),
            "price": self.price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "direction": self.direction,
            "status": self.status,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
        }


class CompletedPaperTrade:
    """Represents a fully completed paper trade."""

    def __init__(
        self,
        trade_id: str,
        session_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        stop_price: float,
        target_price: float,
        quantity: float,
        entry_at: datetime,
        exit_at: datetime,
        exit_reason: str,   # TP_HIT, SL_HIT, MANUAL_CLOSE
        net_pnl: float,
        r_multiple: float,
        equity_before: float,
        equity_after: float,
        source: str = "MANUAL",
    ) -> None:
        self.trade_id = trade_id
        self.session_id = session_id
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.stop_price = stop_price
        self.target_price = target_price
        self.quantity = quantity
        self.entry_at = entry_at
        self.exit_at = exit_at
        self.exit_reason = exit_reason
        self.net_pnl = net_pnl
        self.r_multiple = r_multiple
        self.equity_before = equity_before
        self.equity_after = equity_after
        self.source = source

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "quantity": round(self.quantity, 6),
            "entry_at": self.entry_at.isoformat(),
            "exit_at": self.exit_at.isoformat(),
            "exit_reason": self.exit_reason,
            "net_pnl": round(self.net_pnl, 4),
            "r_multiple": round(self.r_multiple, 4),
            "equity_before": round(self.equity_before, 4),
            "equity_after": round(self.equity_after, 4),
            "source": self.source,
        }


class BinancePaperSession:
    """Binance-backed paper trading session.

    Runs the COMPLETE live-paper data pipeline:

        Binance 1H completed klines (public REST, unauthenticated)
            ↓
        EMAExperimentalStrategy.on_candle()   (EMA20 / EMA30 / 3R)
            ↓
        EntrySignal (on confirmed pullback setup)
            ↓
        PaperExecutor.on_tick()               (next-bar entry, SL/TP)
            ↓
        PaperAccount                          (position sizing, equity)
            ↓
        TradingJournal                        (setup, entry, exit, obs)

    SECURITY:
    - binance_client is read-only — NO order placement capability.
    - Real Binance balances are NEVER used as paper equity.
    - Binance credentials are NEVER serialised or logged.
    - get_account_status() / get_binance_balances() use authenticated
      read-only endpoints only; no write endpoints exist.
    """

    def __init__(
        self,
        binance_client: BinanceReadOnlyClient,
        strategy: EMAPullbackStrategy,
        session_id: str = DEFAULT_SESSION_ID,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        initial_equity: float = DEFAULT_INITIAL_EQUITY,
        risk_pct: float = 0.01,
        journal: Optional[TradingJournal] = None,
        run_id: Optional[str] = None,
    ) -> None:
        self.binance_client = binance_client
        self.strategy = strategy
        self.session_id = session_id
        self.symbol = symbol.upper()
        self.interval = interval.lower()

        # Paper account — fixed synthetic equity, NOT real Binance balance
        self.account = PaperAccount(
            initial_equity=initial_equity,
            risk_pct=risk_pct,
        )

        # Journal for all events (setup detected, entry, exit, observation)
        self.journal = journal

        # Executor wires strategy → account → journal
        _run_id = run_id or f"paper-{session_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        self.executor = PaperExecutor(
            account=self.account,
            strategy=self.strategy,
            journal=self.journal,
            run_id=_run_id,
            record_observations=True,
        )

        # Session state
        self.started_at: datetime = datetime.now(timezone.utc)
        self._order_counter: int = 0
        self._trade_counter: int = 0
        self._candles_processed: int = 0
        self._is_warmed_up: bool = False

        # History (for session-level tracking; executor owns strategy signals)
        self.orders: List[PaperOrder] = []
        self.completed_trades: List[CompletedPaperTrade] = []

    # ------------------------------------------------------------------
    # Strategy warmup — must be called before on_completed_candle()
    # ------------------------------------------------------------------

    def warmup(self, warmup_candles: Optional[List[Candle]] = None, warmup_limit: int = 100) -> int:
        """Warm up EMA indicators from Binance historical klines or supplied candles.

        Call this before feeding live candles via on_completed_candle().

        Args:
            warmup_candles: Optional pre-fetched candle list. If None, fetches
                            from Binance public REST API.
            warmup_limit: Number of historical candles to use (default 100).

        Returns:
            Number of candles used for warmup.
        """
        if warmup_candles is None:
            try:
                warmup_candles = fetch_public_binance_klines(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=warmup_limit + 1,  # +1 to account for forming bar exclusion
                )
            except Exception as exc:
                logger.warning("Warmup kline fetch failed: %s — strategy may not be ready.", exc)
                warmup_candles = []

        # Feed candles to strategy with has_open_position=True to avoid
        # spurious signals during warmup
        count = warmup_strategy(self.strategy, warmup_candles)
        self._is_warmed_up = self.strategy.is_ready
        logger.info(
            "BinancePaperSession warmup: %d candles processed, is_ready=%s",
            count, self._is_warmed_up,
        )
        return count

    # ------------------------------------------------------------------
    # Live candle pipeline — the core data path
    # ------------------------------------------------------------------

    def on_completed_candle(self, candle: Candle) -> Optional[EntrySignal]:
        """Process a completed 1H candle through the full strategy pipeline.

        Data path:
            Candle  →  EMA20/EMA30 update  →  strategy.on_candle()
                    →  EntrySignal (if confirmed)
                    →  executor.pending_signal set
                    →  next on_tick() call enters position
                    →  journal records all events

        CRITICAL: Only completed (closed) candles must be passed here.
        Forming candles MUST NOT be passed to this method.

        Args:
            candle: A fully completed OHLCV candle (close_time has passed).

        Returns:
            EntrySignal if a new confirmed setup was detected, else None.
        """
        self._last_candle = candle
        self._candles_processed += 1

        # Build a minimal NormalizedKline for on_tick() within on_candle_completed()
        # We synthesize a completed kline from the REST candle
        kline = _candle_to_normalized_kline(candle, is_closed=True)

        # Delegate entirely to the executor which calls strategy.on_candle() internally
        signal = self.executor.on_candle_completed(candle=candle, kline=kline)

        if signal is not None:
            logger.info(
                "Paper session: new signal %s on %s @ %s (SL: %.2f)",
                signal.direction, candle.symbol,
                candle.timestamp.isoformat(), signal.stop_price,
            )

        return signal

    def on_tick(self, kline: NormalizedKline) -> None:
        """Process a real-time intrabar tick for SL/TP monitoring and pending entry.

        Use this when the WebSocket observer delivers forming-bar updates.
        Forming candles are NEVER used for new strategy signals — only for
        intrabar SL/TP monitoring of an already-open position, and for
        triggering pending entry on the next bar's open.

        Args:
            kline: Normalized real-time kline update (may be forming or completed).
        """
        self.executor.on_tick(kline)

    # ------------------------------------------------------------------
    # Public method for polling: fetch latest candles and process them
    # ------------------------------------------------------------------

    def poll_and_process(self, limit: int = 5) -> List[Optional[EntrySignal]]:
        """Fetch the latest completed candles from Binance and run them through the pipeline.

        This is the polling alternative to the WebSocket-based on_tick / on_completed_candle
        flow. It fetches the most recent `limit` completed bars and processes any that
        haven't been seen yet.

        Returns:
            List of EntrySignals produced (may be empty).
        """
        try:
            candle_dicts = self.binance_client.get_klines(
                symbol=self.symbol,
                interval=self.interval,
                limit=limit + 1,
            )
        except BinanceClientError as exc:
            logger.warning("poll_and_process: kline fetch failed: %s", exc)
            return []

        # Convert raw dicts to Candle objects
        signals: List[Optional[EntrySignal]] = []
        for cd in candle_dicts:
            try:
                candle = Candle(
                    symbol=cd["symbol"],
                    timeframe=cd["interval"],
                    timestamp=datetime.fromisoformat(cd["open_time_iso"]),
                    open=cd["open"],
                    high=cd["high"],
                    low=cd["low"],
                    close=cd["close"],
                    volume=cd["volume"],
                )
                signal = self.on_completed_candle(candle)
                signals.append(signal)
            except Exception as exc:
                logger.warning("poll_and_process: candle conversion failed: %s", exc)

        return signals

    # ------------------------------------------------------------------
    # Market data methods (delegate to read-only Binance client)
    # ------------------------------------------------------------------

    def get_current_price(self) -> float:
        """Fetch latest live BTC price from Binance (unauthenticated)."""
        return self.binance_client.get_ticker_price(self.symbol)

    def get_recent_candles(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent completed klines from Binance (unauthenticated)."""
        limit = max(1, min(limit, 200))
        return self.binance_client.get_klines(
            symbol=self.symbol,
            interval=self.interval,
            limit=limit + 1,  # +1 to account for forming bar exclusion
        )

    # ------------------------------------------------------------------
    # Account status (read-only Binance + paper state)
    # ------------------------------------------------------------------

    def get_account_status(self) -> Dict[str, Any]:
        """Return read-only Binance account metadata.

        Does NOT include paper equity. Call get_paper_account() for that.
        SECURITY: No credentials, balances are real but read-only.
        """
        try:
            return self.binance_client.get_account_status()
        except BinanceClientError as exc:
            return {"error": str(exc), "available": False}

    def get_binance_balances(
        self,
        assets: Optional[List[str]] = None,
        hide_zero: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return real Binance balances (read-only, never used as paper equity)."""
        try:
            return self.binance_client.get_balances(assets=assets, hide_zero=hide_zero)
        except BinanceClientError as exc:
            return [{"error": str(exc)}]

    # ------------------------------------------------------------------
    # Paper account state — reads from executor / account / journal
    # ------------------------------------------------------------------

    def get_paper_account(self, current_price: Optional[float] = None) -> Dict[str, Any]:
        """Return complete paper account state snapshot.

        SECURITY: Paper equity is synthetic — never derived from real Binance balance.
        """
        if current_price is None:
            try:
                current_price = self.get_current_price()
            except Exception:
                current_price = None

        equity = self.account.get_equity(current_price)

        return {
            "session_id": self.session_id,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy.VERSION,
            "take_profit_rr": getattr(self.strategy, "take_profit_rr", 2.0),
            "initial_equity": self.account.initial_equity,
            "cash_balance": round(self.account.cash_balance, 4),
            "equity": round(equity, 4),
            "realized_pnl": round(self.account.realized_pnl, 4),
            "total_fees": round(self.account.total_fees, 4),
            "total_slippage": round(self.account.total_slippage, 4),
            "trade_count": self.account.trade_count,
            "has_active_position": self.account.has_active_position,
            "pending_signal": self.executor.pending_signal is not None,
            "ema20": self.strategy.fast_ema.value,
            "ema30": self.strategy.slow_ema.value,
            "last_candle": {
                "timestamp": self._last_candle.timestamp.isoformat(),
                "open": self._last_candle.open,
                "high": self._last_candle.high,
                "low": self._last_candle.low,
                "close": self._last_candle.close,
                "volume": self._last_candle.volume,
            } if self._last_candle else None,
            "candles_processed": self._candles_processed,
            "is_warmed_up": self._is_warmed_up,
            "strategy_ready": self.strategy.is_ready,
            "started_at": self.started_at.isoformat(),
            "note": "Paper equity is synthetic and unrelated to any real Binance balance.",
        }

    def get_paper_positions(self) -> List[Dict[str, Any]]:
        """Return active paper positions (0 or 1)."""
        if not self.account.has_active_position or self.account.active_position is None:
            return []
        pos = self.account.active_position
        try:
            current_price = self.get_current_price()
        except Exception:
            current_price = None

        unrealized_pnl: Optional[float] = None
        if current_price is not None:
            if pos.direction == "LONG":
                unrealized_pnl = (current_price - pos.raw_entry_price) * pos.quantity
            else:
                unrealized_pnl = (pos.raw_entry_price - current_price) * pos.quantity

        return [{
            "trade_id": pos.trade_id,
            "session_id": self.session_id,
            "symbol": pos.symbol,
            "timeframe": pos.timeframe,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "raw_entry_price": pos.raw_entry_price,
            "stop_price": pos.stop_price,
            "target_price": pos.target_price,
            "take_profit_rr": getattr(self.strategy, "take_profit_rr", 2.0),
            "quantity": round(pos.quantity, 6),
            "risk_amount": round(pos.risk_amount, 4),
            "equity_before": round(pos.equity_before, 4),
            "entry_fee": round(pos.entry_fee, 4),
            "entry_timestamp": pos.entry_timestamp.isoformat(),
            "current_price": current_price,
            "unrealized_pnl": round(unrealized_pnl, 4) if unrealized_pnl is not None else None,
        }]

    def get_paper_orders(self) -> List[Dict[str, Any]]:
        """Return all paper orders (manual only — strategy orders are in executor)."""
        return [o.to_dict() for o in self.orders]

    def get_paper_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return completed paper trades (strategy + manual, most recent first)."""
        limit = max(1, min(limit, 200))
        # Executor completed_trades_history has the raw close results.
        # We combine with manual completed_trades for a unified view.
        executor_trades = self.executor.completed_trades_history
        manual_trades = [t.to_dict() for t in self.completed_trades]

        # Build unified list from executor (strategy-driven trades)
        strategy_trades = []
        for i, tr in enumerate(executor_trades):
            pos: PaperPosition = tr["position"]
            strategy_trades.append({
                "trade_id": pos.trade_id,
                "session_id": self.session_id,
                "symbol": pos.symbol,
                "direction": pos.direction,
                "entry_price": pos.entry_price,
                "exit_price": tr["effective_exit_price"],
                "stop_price": pos.stop_price,
                "target_price": pos.target_price,
                "quantity": round(pos.quantity, 6),
                "entry_at": pos.entry_timestamp.isoformat(),
                "exit_at": self.started_at.isoformat(),  # approximate
                "exit_reason": tr["exit_reason"],
                "net_pnl": round(tr["net_pnl"], 4),
                "r_multiple": round(tr["r_multiple"], 4),
                "equity_before": round(tr["equity_before"], 4),
                "equity_after": round(tr["equity_after"], 4),
                "source": "STRATEGY",
            })

        all_trades = strategy_trades + manual_trades
        return list(reversed(all_trades))[:limit]

    # ------------------------------------------------------------------
    # Manual paper order placement — NO real Binance execution
    # ------------------------------------------------------------------

    def place_paper_order(
        self,
        side: str,
        quantity: float,
        stop_price: float,
        target_price: float,
    ) -> Dict[str, Any]:
        """Simulate a manual paper market order.

        SECURITY: This method NEVER calls any real Binance order endpoint.
        It is 100% simulated within the paper account.

        Note: Strategy-driven orders flow through the executor automatically
        via on_completed_candle() → signal → on_tick(). This method is for
        manual operator-initiated paper orders from the GUI or MCP.
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"success": False, "error": "Invalid side. Must be BUY or SELL."}

        if self.account.has_active_position:
            return {
                "success": False,
                "error": "Cannot place paper order: an active position already exists.",
            }

        try:
            current_price = self.get_current_price()
        except BinanceClientError as exc:
            return {"success": False, "error": f"Cannot fetch price: {exc}"}

        direction = "LONG" if side == "BUY" else "SHORT"

        # Validate stop side
        if direction == "LONG" and current_price <= stop_price:
            return {
                "success": False,
                "error": f"Invalid LONG stop: price ({current_price}) must be above stop ({stop_price}).",
            }
        if direction == "SHORT" and current_price >= stop_price:
            return {
                "success": False,
                "error": f"Invalid SHORT stop: price ({current_price}) must be below stop ({stop_price}).",
            }

        self._order_counter += 1
        order_id = f"PAPER-ORD-{self._order_counter:05d}"
        now = datetime.now(timezone.utc)

        order = PaperOrder(
            order_id=order_id,
            session_id=self.session_id,
            symbol=self.symbol,
            side=side,
            order_type="MARKET",
            quantity=quantity,
            price=current_price,
            stop_price=stop_price,
            target_price=target_price,
            direction=direction,
            status="PENDING",
            created_at=now,
            source="MANUAL",
        )

        # Execute paper order immediately (market order simulation)
        rr = getattr(self.strategy, "take_profit_rr", 2.0)
        try:
            pos = self.account.open_position(
                trade_id=order_id,
                strategy_version=self.strategy.VERSION,
                symbol=self.symbol,
                timeframe=self.interval,
                direction=direction,
                pullback_timestamp=now,
                confirmation_timestamp=now,
                entry_timestamp=now,
                open_price=current_price,
                stop_price=stop_price,
                take_profit_rr=rr,
            )
            order.status = "FILLED"
            order.filled_at = now
        except (ValueError, RuntimeError) as err:
            order.status = "REJECTED"
            self.orders.append(order)
            return {"success": False, "error": str(err), "order": order.to_dict()}

        self.orders.append(order)
        logger.info(
            "Manual paper order placed: %s %s %s qty=%.6f @ %.2f (SL: %.2f TP: %.2f)",
            order_id, direction, self.symbol, quantity, current_price, stop_price, target_price,
        )
        return {"success": True, "order": order.to_dict()}

    def close_paper_position(self, reason: str = "MANUAL_CLOSE") -> Dict[str, Any]:
        """Manually close the active paper position at current market price.

        SECURITY: This only closes a simulated paper position.
        No real Binance order is placed.
        """
        if not self.account.has_active_position:
            return {"success": False, "error": "No active paper position to close."}

        try:
            current_price = self.get_current_price()
        except BinanceClientError as exc:
            return {"success": False, "error": f"Cannot fetch price for close: {exc}"}

        pos = self.account.active_position
        assert pos is not None

        self._trade_counter += 1
        trade_id = f"PAPER-TRD-{self._trade_counter:05d}"
        now = datetime.now(timezone.utc)

        result = self.account.close_position(
            raw_exit_price=current_price,
            exit_reason=reason,
        )

        trade = CompletedPaperTrade(
            trade_id=trade_id,
            session_id=self.session_id,
            symbol=pos.symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=result["effective_exit_price"],
            stop_price=pos.stop_price,
            target_price=pos.target_price,
            quantity=pos.quantity,
            entry_at=pos.entry_timestamp,
            exit_at=now,
            exit_reason=reason,
            net_pnl=result["net_pnl"],
            r_multiple=result["r_multiple"],
            equity_before=result["equity_before"],
            equity_after=result["equity_after"],
            source="MANUAL",
        )
        self.completed_trades.append(trade)

        logger.info(
            "Manual paper position closed: %s reason=%s price=%.2f net_pnl=%.4f",
            pos.trade_id, reason, current_price, result["net_pnl"],
        )
        return {"success": True, "trade": trade.to_dict()}

    # ------------------------------------------------------------------
    # Session summary
    # ------------------------------------------------------------------

    def get_session_summary(self) -> Dict[str, Any]:
        """Return a complete session summary."""
        try:
            current_price = self.get_current_price()
        except Exception:
            current_price = None

        account_state = self.get_paper_account(current_price)
        return {
            "session_id": self.session_id,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy.VERSION,
            "take_profit_rr": getattr(self.strategy, "take_profit_rr", 2.0),
            "started_at": self.started_at.isoformat(),
            "current_price": current_price,
            "account": account_state,
            "total_orders": len(self.orders),
            "completed_trades": len(self.completed_trades),
            "strategy_trades": len(self.executor.completed_trades_history),
            "active_positions": len(self.get_paper_positions()),
            "pending_signal": self.executor.pending_signal is not None,
            "is_warmed_up": self._is_warmed_up,
            "strategy_ready": self.strategy.is_ready,
            "candles_processed": self._candles_processed,
            "ema20": self.strategy.fast_ema.value,
            "ema30": self.strategy.slow_ema.value,
            "last_candle": {
                "timestamp": self._last_candle.timestamp.isoformat(),
                "open": self._last_candle.open,
                "high": self._last_candle.high,
                "low": self._last_candle.low,
                "close": self._last_candle.close,
                "volume": self._last_candle.volume,
            } if self._last_candle else None,
        }

    # ------------------------------------------------------------------
    # Internal reference for last candle
    # ------------------------------------------------------------------
    _last_candle: Optional[Candle] = None


# ---------------------------------------------------------------------------
# Helper: synthesize a NormalizedKline from a REST Candle
# ---------------------------------------------------------------------------

def _candle_to_normalized_kline(candle: Candle, is_closed: bool = True) -> NormalizedKline:
    """Convert a Candle (from REST) to a NormalizedKline (for PaperExecutor).

    PaperExecutor.on_candle_completed() requires a NormalizedKline to call
    on_tick() internally for same-bar SL/TP evaluation before strategy evaluation.
    """
    close_time = candle.timestamp  # REST candles use open_time as timestamp
    return NormalizedKline(
        candle=candle,
        is_closed=is_closed,
        event_time=close_time,
        close_time=close_time,
        trade_count=0,
        quote_volume=0.0,
        raw_payload={},
    )
