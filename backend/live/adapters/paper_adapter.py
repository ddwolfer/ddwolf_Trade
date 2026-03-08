"""
Paper Trading Adapter — simulates exchange order execution in-memory.

Implements the ExchangeAdapter interface with simulated fills that match
the backtest engine's commission and slippage logic. All state is
protected by a threading.Lock for safe concurrent access.
"""
import threading
import time
from typing import Dict, List, Optional

from live.adapters.base_adapter import ExchangeAdapter
from live.models import LiveOrder, Position, AccountState


class PaperTradingAdapter(ExchangeAdapter):
    """
    Simulated exchange adapter for paper trading.

    Fills MARKET orders instantly with configurable slippage and commission
    rates. Financial calculations mirror the backtest StrategyEngine so
    paper-trading results are directly comparable to backtest results.
    """

    def __init__(
        self,
        session_id: str,
        initial_capital: float = 10000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005,
    ):
        self.session_id = session_id
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

        self._cash: float = initial_capital
        self._orders: Dict[str, LiveOrder] = {}
        self._positions: Dict[str, Position] = {}
        self._closed_positions: List[Position] = []
        self._current_prices: Dict[str, float] = {}
        self._realized_pnl: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Price feed
    # ------------------------------------------------------------------

    def set_current_price(self, symbol: str, price: float) -> None:
        """Update the latest market price and refresh unrealized PnL."""
        with self._lock:
            self._current_prices[symbol] = price
            # Refresh unrealized PnL on any open position for this symbol
            pos = self._positions.get(symbol)
            if pos is not None and pos.status == "OPEN":
                pos.unrealized_pnl = (price - pos.entry_price) * pos.quantity

    def get_current_price(self, symbol: str) -> float:
        """Return the last-set price for *symbol*."""
        with self._lock:
            return self._current_prices.get(symbol, 0.0)

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float = 0.0,
        reason: str = "",
    ) -> LiveOrder:
        """
        Place and immediately fill a MARKET order.

        BUY fill logic:
            fill_price  = current_price * (1 + slippage_rate)
            cost        = fill_price * quantity
            commission  = cost * commission_rate
            total_cost  = cost + commission
            If total_cost > cash, quantity is adjusted down.

        SELL fill logic:
            fill_price  = current_price * (1 - slippage_rate)
            proceeds    = fill_price * sell_qty
            commission  = proceeds * commission_rate
            pnl         = (fill_price - entry_price) * sell_qty - commission
        """
        with self._lock:
            now_ms = int(time.time() * 1000)

            order = LiveOrder(
                session_id=self.session_id,
                symbol=symbol,
                side=side.upper(),
                order_type=order_type.upper(),
                quantity=quantity,
                price=price,
                status="NEW",
                created_time=now_ms,
                reason=reason,
            )

            if side.upper() == "BUY":
                order = self._fill_buy(order, now_ms)
            elif side.upper() == "SELL":
                order = self._fill_sell(order, now_ms)
            else:
                order.status = "REJECTED"
                order.reason = f"Unknown side: {side}"

            self._orders[order.order_id] = order
            return order

    # ------------------------------------------------------------------
    # Internal fill helpers (must be called while holding _lock)
    # ------------------------------------------------------------------

    def _fill_buy(self, order: LiveOrder, now_ms: int) -> LiveOrder:
        """Execute a MARKET BUY order."""
        symbol = order.symbol

        # Reject if no price feed
        current_price = self._current_prices.get(symbol)
        if current_price is None:
            order.status = "REJECTED"
            order.reason = "No current price for symbol"
            return order

        fill_price = current_price * (1 + self.slippage_rate)
        quantity = order.quantity
        cost = fill_price * quantity
        commission = cost * self.commission_rate
        total_cost = cost + commission

        # Adjust quantity down if insufficient cash
        if total_cost > self._cash:
            available = self._cash / (1 + self.commission_rate)
            quantity = available / fill_price
            cost = fill_price * quantity
            commission = cost * self.commission_rate
            total_cost = cost + commission

        if quantity <= 0:
            order.status = "REJECTED"
            order.reason = "Insufficient funds"
            return order

        # Deduct from cash
        self._cash -= total_cost

        # Create or update position
        existing_pos = self._positions.get(symbol)
        if existing_pos is not None and existing_pos.status == "OPEN":
            # Average into existing position
            old_qty = existing_pos.quantity
            new_qty = old_qty + quantity
            existing_pos.entry_price = (
                (existing_pos.entry_price * old_qty + fill_price * quantity) / new_qty
            )
            existing_pos.quantity = new_qty
            # Refresh unrealized PnL
            existing_pos.unrealized_pnl = (
                (current_price - existing_pos.entry_price) * existing_pos.quantity
            )
        else:
            pos = Position(
                session_id=self.session_id,
                symbol=symbol,
                side="LONG",
                quantity=quantity,
                entry_price=fill_price,
                entry_time=now_ms,
                status="OPEN",
                entry_order_id=order.order_id,
                unrealized_pnl=(current_price - fill_price) * quantity,
            )
            self._positions[symbol] = pos

        # Fill the order
        order.status = "FILLED"
        order.filled_quantity = quantity
        order.avg_fill_price = fill_price
        order.commission = commission
        order.filled_time = now_ms
        return order

    def _fill_sell(self, order: LiveOrder, now_ms: int) -> LiveOrder:
        """Execute a MARKET SELL order."""
        symbol = order.symbol

        pos = self._positions.get(symbol)
        if pos is None or pos.status != "OPEN":
            order.status = "REJECTED"
            order.reason = "No open position to sell"
            return order

        current_price = self._current_prices.get(symbol)
        if current_price is None:
            order.status = "REJECTED"
            order.reason = "No current price for symbol"
            return order

        sell_qty = min(order.quantity, pos.quantity)
        fill_price = current_price * (1 - self.slippage_rate)
        proceeds = fill_price * sell_qty
        commission = proceeds * self.commission_rate
        net_proceeds = proceeds - commission

        # PnL matches backtest engine:
        # pnl = (fill_price - entry_price) * sell_qty - commission
        pnl = (fill_price - pos.entry_price) * sell_qty - commission

        self._cash += net_proceeds
        self._realized_pnl += pnl

        # Close or reduce position
        remaining_qty = pos.quantity - sell_qty
        if remaining_qty <= 1e-12:
            # Fully closed
            pos.status = "CLOSED"
            pos.exit_price = fill_price
            pos.exit_time = now_ms
            pos.exit_order_id = order.order_id
            pos.realized_pnl = pnl
            pos.unrealized_pnl = 0.0
            pos.quantity = 0.0
            self._closed_positions.append(pos)
            del self._positions[symbol]
        else:
            # Partial close
            pos.quantity = remaining_qty
            pos.unrealized_pnl = (current_price - pos.entry_price) * remaining_qty

        # Fill the order
        order.status = "FILLED"
        order.filled_quantity = sell_qty
        order.avg_fill_price = fill_price
        order.commission = commission
        order.filled_time = now_ms
        return order

    # ------------------------------------------------------------------
    # Order queries
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. MARKET orders fill immediately, so always False."""
        with self._lock:
            return False

    def get_order(self, order_id: str) -> Optional[LiveOrder]:
        """Look up an order by its id."""
        with self._lock:
            return self._orders.get(order_id)

    def get_open_orders(self, symbol: str = "") -> List[LiveOrder]:
        """Return unfilled orders, optionally filtered by symbol."""
        terminal = {"FILLED", "CANCELLED", "REJECTED"}
        with self._lock:
            results: List[LiveOrder] = []
            for o in self._orders.values():
                if o.status in terminal:
                    continue
                if symbol and o.symbol != symbol:
                    continue
                results.append(o)
            return results

    # ------------------------------------------------------------------
    # Position queries
    # ------------------------------------------------------------------

    def get_position(self, symbol: str) -> Optional[Position]:
        """Return the open position for *symbol*, or None."""
        with self._lock:
            pos = self._positions.get(symbol)
            if pos is not None and pos.status == "OPEN":
                return pos
            return None

    def get_all_positions(self) -> List[Position]:
        """Return all currently open positions."""
        with self._lock:
            return [p for p in self._positions.values() if p.status == "OPEN"]

    # ------------------------------------------------------------------
    # Account state
    # ------------------------------------------------------------------

    def get_account_state(self) -> AccountState:
        """Build a snapshot of the account."""
        with self._lock:
            unrealized = 0.0
            position_value = 0.0
            for pos in self._positions.values():
                if pos.status == "OPEN":
                    unrealized += pos.unrealized_pnl
                    price = self._current_prices.get(pos.symbol, pos.entry_price)
                    position_value += pos.quantity * price

            total_equity = self._cash + position_value
            return AccountState(
                session_id=self.session_id,
                total_equity=total_equity,
                available_cash=self._cash,
                unrealized_pnl=unrealized,
                realized_pnl=self._realized_pnl,
                timestamp=int(time.time() * 1000),
            )

    # ------------------------------------------------------------------
    # Emergency close
    # ------------------------------------------------------------------

    def close_all_positions(self, reason: str = "Manual close") -> List[LiveOrder]:
        """Close every open position at market."""
        with self._lock:
            # Snapshot symbols + quantities before mutating
            to_close = [
                (sym, pos.quantity)
                for sym, pos in self._positions.items()
                if pos.status == "OPEN"
            ]

        if not to_close:
            return []

        orders: List[LiveOrder] = []
        for sym, qty in to_close:
            order = self.place_order(sym, "SELL", "MARKET", qty, reason=reason)
            orders.append(order)
        return orders
