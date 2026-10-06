"""Paper trading account managing equity, position sizing, fees, slippage, and state."""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from atsits.models.backtest import BacktestConfig, CostModel
from atsits.paper.models import PaperAccountState, PaperPosition


class PaperAccount:
    """Deterministic Paper Trading Account.

    Maintains paper equity, calculates position sizing and costs adhering to the
    exact deterministic cost models defined in BacktestConfig/CostModel, and manages
    active paper positions.
    """

    def __init__(
        self,
        initial_equity: float = 10000.0,
        risk_pct: float = 0.01,
        cost_model: Optional[CostModel] = None,
    ):
        self.initial_equity: float = float(initial_equity)
        self.risk_pct: float = float(risk_pct)
        self.cost_model: CostModel = cost_model or CostModel()

        # Account state
        self.cash_balance: float = float(initial_equity)
        self.realized_pnl: float = 0.0
        self.total_fees: float = 0.0
        self.total_slippage: float = 0.0
        self.trade_count: int = 0
        self.active_position: Optional[PaperPosition] = None

    @property
    def has_active_position(self) -> bool:
        """True if an open paper position currently exists."""
        return self.active_position is not None

    def get_equity(self, current_price: Optional[float] = None) -> float:
        """Calculate total account equity including unrealized PnL if a position is open.

        Args:
            current_price: Optional current market price to evaluate unrealized PnL.

        Returns:
            Total account equity.
        """
        if self.active_position is None or current_price is None:
            return self.cash_balance

        pos = self.active_position
        if pos.direction == "LONG":
            unrealized_gross = (current_price - pos.raw_entry_price) * pos.quantity
        else:
            unrealized_gross = (pos.raw_entry_price - current_price) * pos.quantity

        return self.cash_balance + unrealized_gross - pos.entry_fee - pos.entry_slippage

    def calculate_position_size(self, open_price: float, stop_price: float) -> Tuple[float, float]:
        """Calculate position size and risk amount based on current equity and stop distance.

        Args:
            open_price: Market open price for entry.
            stop_price: Invalidation stop loss level.

        Returns:
            Tuple of (quantity, risk_amount).
        """
        equity = self.cash_balance
        risk_amount = equity * self.risk_pct
        risk_per_unit = abs(open_price - stop_price)
        if risk_per_unit <= 0.0:
            raise ValueError(f"Invalid stop distance: open={open_price}, stop={stop_price}")
        quantity = risk_amount / risk_per_unit
        return quantity, risk_amount

    def open_position(
        self,
        trade_id: str,
        strategy_version: str,
        symbol: str,
        timeframe: str,
        direction: str,
        pullback_timestamp: datetime,
        confirmation_timestamp: datetime,
        entry_timestamp: datetime,
        open_price: float,
        stop_price: float,
        take_profit_rr: float = 2.0,
    ) -> PaperPosition:
        """Open a new paper position adhering to deterministic sizing and cost rules.

        Args:
            trade_id: Unique trade identifier.
            strategy_version: Strategy version string.
            symbol: Trading pair symbol.
            timeframe: Candle timeframe.
            direction: 'LONG' or 'SHORT'.
            pullback_timestamp: Qualifying pullback candle timestamp.
            confirmation_timestamp: Confirmation candle timestamp.
            entry_timestamp: Bar timestamp of entry.
            open_price: Raw bar open price.
            stop_price: Stop loss price level.

        Returns:
            Newly opened PaperPosition.
        """
        if self.active_position is not None:
            raise RuntimeError(f"Cannot open position {trade_id}: position {self.active_position.trade_id} already active")

        # Validate stop relative to open price
        if direction == "LONG" and open_price <= stop_price:
            raise ValueError(f"Invalid stop for LONG: open={open_price} <= stop={stop_price}")
        if direction == "SHORT" and open_price >= stop_price:
            raise ValueError(f"Invalid stop for SHORT: open={open_price} >= stop={stop_price}")

        equity_before = self.cash_balance
        risk_amount = equity_before * self.risk_pct
        risk_per_unit = abs(open_price - stop_price)
        quantity = risk_amount / risk_per_unit

        if direction == "LONG":
            target_price = open_price + (take_profit_rr * risk_per_unit)
            entry_slippage_delta = self.cost_model.slippage_points + (open_price * self.cost_model.slippage_pct)
            effective_entry = open_price + entry_slippage_delta
        else:
            target_price = open_price - (take_profit_rr * risk_per_unit)
            entry_slippage_delta = self.cost_model.slippage_points + (open_price * self.cost_model.slippage_pct)
            effective_entry = open_price - entry_slippage_delta

        entry_fee = effective_entry * quantity * self.cost_model.commission_rate
        entry_slippage_cost = entry_slippage_delta * quantity

        pos = PaperPosition(
            trade_id=trade_id,
            strategy_version=strategy_version,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            pullback_timestamp=pullback_timestamp,
            confirmation_timestamp=confirmation_timestamp,
            entry_timestamp=entry_timestamp,
            raw_entry_price=open_price,
            entry_price=effective_entry,
            stop_price=stop_price,
            target_price=target_price,
            quantity=quantity,
            risk_amount=risk_amount,
            equity_before=equity_before,
            entry_fee=entry_fee,
            entry_slippage=entry_slippage_cost,
        )

        self.active_position = pos
        return pos

    def close_position(
        self,
        raw_exit_price: float,
        exit_reason: str,
    ) -> Dict[str, Any]:
        """Close the active paper position and update cash balance and realized statistics.

        Args:
            raw_exit_price: Raw trigger/fill price at exit.
            exit_reason: Exit classification (e.g. 'TP_HIT', 'SL_HIT', 'END_OF_DATA', 'MANUAL').

        Returns:
            Dictionary containing closed position details, effective exit price, PnL, fees, slippage, and R-multiple.
        """
        if self.active_position is None:
            raise RuntimeError("Cannot close position: No active position open.")

        pos = self.active_position

        if pos.direction == "LONG":
            exit_slippage_delta = self.cost_model.slippage_points + (raw_exit_price * self.cost_model.slippage_pct)
            effective_exit = raw_exit_price - exit_slippage_delta
            exit_fee = effective_exit * pos.quantity * self.cost_model.commission_rate
            exit_slippage_cost = exit_slippage_delta * pos.quantity
            gross_pnl = (raw_exit_price - pos.raw_entry_price) * pos.quantity
        else:
            exit_slippage_delta = self.cost_model.slippage_points + (raw_exit_price * self.cost_model.slippage_pct)
            effective_exit = raw_exit_price + exit_slippage_delta
            exit_fee = effective_exit * pos.quantity * self.cost_model.commission_rate
            exit_slippage_cost = exit_slippage_delta * pos.quantity
            gross_pnl = (pos.raw_entry_price - raw_exit_price) * pos.quantity

        total_fees = pos.entry_fee + exit_fee
        total_slippage = pos.entry_slippage + exit_slippage_cost
        net_pnl = gross_pnl - total_fees - total_slippage
        r_multiple = net_pnl / pos.risk_amount if pos.risk_amount > 0 else 0.0

        equity_before = pos.equity_before
        self.cash_balance += net_pnl
        self.realized_pnl += net_pnl
        self.total_fees += total_fees
        self.total_slippage += total_slippage
        self.trade_count += 1
        equity_after = self.cash_balance

        self.active_position = None

        return {
            "position": pos,
            "raw_exit_price": raw_exit_price,
            "effective_exit_price": effective_exit,
            "exit_reason": exit_reason,
            "gross_pnl": gross_pnl,
            "fees": total_fees,
            "slippage": total_slippage,
            "net_pnl": net_pnl,
            "r_multiple": r_multiple,
            "equity_before": equity_before,
            "equity_after": equity_after,
        }

    def snapshot(self) -> PaperAccountState:
        """Generate an immutable snapshot of current account state."""
        return PaperAccountState(
            initial_equity=self.initial_equity,
            cash_balance=self.cash_balance,
            equity=self.cash_balance,
            realized_pnl=self.realized_pnl,
            total_fees=self.total_fees,
            total_slippage=self.total_slippage,
            trade_count=self.trade_count,
            active_position=self.active_position,
        )

    def restore(self, state: PaperAccountState) -> None:
        """Restore account state from a snapshot."""
        self.initial_equity = state.initial_equity
        self.cash_balance = state.cash_balance
        self.realized_pnl = state.realized_pnl
        self.total_fees = state.total_fees
        self.total_slippage = state.total_slippage
        self.trade_count = state.trade_count
        self.active_position = state.active_position
