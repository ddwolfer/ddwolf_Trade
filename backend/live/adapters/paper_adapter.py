"""
Paper Trading Adapter — simulates exchange order execution in-memory.

Implements the ExchangeAdapter interface with simulated fills that match
the backtest engine's commission and slippage logic. All state is
protected by a threading.Lock for safe concurrent access.

Supports both LONG and SHORT positions.
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

    Order sides:
        BUY         — open LONG or close SHORT
        SELL        — close LONG
        SHORT_OPEN  — open SHORT position
        SHORT_CLOSE — close SHORT position (alias for BUY when SHORT)
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
            pos = self._positions.get(symbol)
            if pos is not None and pos.status == "OPEN":
                if pos.side == "LONG":
                    pos.unrealized_pnl = (price - pos.entry_price) * pos.quantity
                else:  # SHORT
                    pos.unrealized_pnl = (pos.entry_price - price) * pos.quantity

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
        leverage: float = 1.0,
        maintenance_margin_rate: float = 0.005,
    ) -> LiveOrder:
        """
        Place and immediately fill a MARKET order.

        Supported sides: BUY, SELL, SHORT_OPEN, SHORT_CLOSE

        When leverage > 1.0 and quantity == 0 (auto-size), the position
        is sized using leveraged capital: qty = (cash * leverage) / price.
        Margin tracking, liquidation price, and funding fields are set
        on the resulting Position.
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

            side_upper = side.upper()
            if side_upper == "BUY":
                # Check if there's a SHORT position to close first
                pos = self._positions.get(symbol)
                if pos is not None and pos.status == "OPEN" and pos.side == "SHORT":
                    order = self._fill_short_close(order, now_ms)
                else:
                    order = self._fill_buy(order, now_ms, leverage, maintenance_margin_rate)
            elif side_upper == "SELL":
                order = self._fill_sell(order, now_ms)
            elif side_upper == "SHORT_OPEN":
                order = self._fill_short_open(order, now_ms, leverage, maintenance_margin_rate)
            elif side_upper == "SHORT_CLOSE":
                order = self._fill_short_close(order, now_ms)
            else:
                order.status = "REJECTED"
                order.reason = f"Unknown side: {side}"

            self._orders[order.order_id] = order
            return order

    # ------------------------------------------------------------------
    # Internal fill helpers (must be called while holding _lock)
    # ------------------------------------------------------------------

    def _fill_buy(self, order: LiveOrder, now_ms: int,
                  leverage: float = 1.0,
                  maintenance_margin_rate: float = 0.005) -> LiveOrder:
        """Execute a MARKET BUY order (open LONG)."""
        symbol = order.symbol

        current_price = self._current_prices.get(symbol)
        if current_price is None:
            order.status = "REJECTED"
            order.reason = "No current price for symbol"
            return order

        fill_price = current_price * (1 + self.slippage_rate)
        quantity = order.quantity

        if leverage > 1.0:
            # --- Leveraged position ---
            if quantity == 0:
                quantity = (self._cash * leverage) / fill_price

            margin = self._cash
            commission = fill_price * quantity * self.commission_rate
            if commission > margin:
                order.status = "REJECTED"
                order.reason = "Insufficient funds for commission"
                return order
            self._cash = 0.0  # All cash used as margin (minus commission)

            # Liquidation price for LONG:
            # liq = fill_price * (1 - 1/leverage + mmr)
            liq_price = fill_price * (1.0 - 1.0 / leverage + maintenance_margin_rate)

            existing_pos = self._positions.get(symbol)
            if existing_pos is not None and existing_pos.status == "OPEN" and existing_pos.side == "LONG":
                old_qty = existing_pos.quantity
                new_qty = old_qty + quantity
                existing_pos.entry_price = (
                    (existing_pos.entry_price * old_qty + fill_price * quantity) / new_qty
                )
                existing_pos.quantity = new_qty
                existing_pos.unrealized_pnl = (
                    (current_price - existing_pos.entry_price) * existing_pos.quantity
                )
                existing_pos.leverage = leverage
                existing_pos.margin_used = margin
                existing_pos.liquidation_price = liq_price
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
                    leverage=leverage,
                    margin_used=margin,
                    liquidation_price=liq_price,
                )
                self._positions[symbol] = pos
        else:
            # --- 1x (existing behavior) ---
            # Auto-size: if quantity is 0, use all available cash
            if quantity == 0:
                available = self._cash / (1 + self.commission_rate)
                quantity = available / fill_price

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

            self._cash -= total_cost

            existing_pos = self._positions.get(symbol)
            if existing_pos is not None and existing_pos.status == "OPEN" and existing_pos.side == "LONG":
                old_qty = existing_pos.quantity
                new_qty = old_qty + quantity
                existing_pos.entry_price = (
                    (existing_pos.entry_price * old_qty + fill_price * quantity) / new_qty
                )
                existing_pos.quantity = new_qty
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

        order.status = "FILLED"
        order.filled_quantity = quantity
        order.avg_fill_price = fill_price
        order.commission = commission
        order.filled_time = now_ms
        return order

    def _fill_sell(self, order: LiveOrder, now_ms: int) -> LiveOrder:
        """Execute a MARKET SELL order (close LONG)."""
        symbol = order.symbol

        pos = self._positions.get(symbol)
        if pos is None or pos.status != "OPEN" or pos.side != "LONG":
            order.status = "REJECTED"
            order.reason = "No open LONG position to sell"
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

        pnl = (fill_price - pos.entry_price) * sell_qty - commission

        self._cash += net_proceeds
        self._realized_pnl += pnl

        remaining_qty = pos.quantity - sell_qty
        if remaining_qty <= 1e-12:
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
            pos.quantity = remaining_qty
            pos.unrealized_pnl = (current_price - pos.entry_price) * remaining_qty

        order.status = "FILLED"
        order.filled_quantity = sell_qty
        order.avg_fill_price = fill_price
        order.commission = commission
        order.filled_time = now_ms
        return order

    def _fill_short_open(self, order: LiveOrder, now_ms: int,
                         leverage: float = 1.0,
                         maintenance_margin_rate: float = 0.005) -> LiveOrder:
        """Execute a SHORT_OPEN order (open SHORT position)."""
        symbol = order.symbol

        current_price = self._current_prices.get(symbol)
        if current_price is None:
            order.status = "REJECTED"
            order.reason = "No current price for symbol"
            return order

        # SHORT: sell borrowed asset at slippage-adjusted price
        fill_price = current_price * (1 - self.slippage_rate)
        quantity = order.quantity

        if leverage > 1.0:
            # --- Leveraged SHORT ---
            if quantity == 0:
                quantity = (self._cash * leverage) / fill_price

            margin = self._cash
            commission = fill_price * quantity * self.commission_rate
            if commission > margin:
                order.status = "REJECTED"
                order.reason = "Insufficient funds for commission"
                return order
            self._cash = 0.0  # All cash used as margin

            # Liquidation price for SHORT:
            # liq = fill_price * (1 + 1/leverage - mmr)
            liq_price = fill_price * (1.0 + 1.0 / leverage - maintenance_margin_rate)

            pos = Position(
                session_id=self.session_id,
                symbol=symbol,
                side="SHORT",
                quantity=quantity,
                entry_price=fill_price,
                entry_time=now_ms,
                status="OPEN",
                entry_order_id=order.order_id,
                unrealized_pnl=(fill_price - current_price) * quantity,
                leverage=leverage,
                margin_used=margin,
                liquidation_price=liq_price,
            )
            self._positions[symbol] = pos
        else:
            # --- 1x SHORT (existing behavior) ---
            commission = fill_price * quantity * self.commission_rate

            if commission > self._cash:
                order.status = "REJECTED"
                order.reason = "Insufficient funds for commission"
                return order

            self._cash -= commission

            pos = Position(
                session_id=self.session_id,
                symbol=symbol,
                side="SHORT",
                quantity=quantity,
                entry_price=fill_price,
                entry_time=now_ms,
                status="OPEN",
                entry_order_id=order.order_id,
                unrealized_pnl=(fill_price - current_price) * quantity,
            )
            self._positions[symbol] = pos

        order.status = "FILLED"
        order.filled_quantity = quantity
        order.avg_fill_price = fill_price
        order.commission = commission
        order.filled_time = now_ms
        return order

    def _fill_short_close(self, order: LiveOrder, now_ms: int) -> LiveOrder:
        """Execute a SHORT_CLOSE order (close SHORT position by buying back)."""
        symbol = order.symbol

        pos = self._positions.get(symbol)
        if pos is None or pos.status != "OPEN" or pos.side != "SHORT":
            order.status = "REJECTED"
            order.reason = "No open SHORT position to cover"
            return order

        current_price = self._current_prices.get(symbol)
        if current_price is None:
            order.status = "REJECTED"
            order.reason = "No current price for symbol"
            return order

        cover_qty = min(order.quantity, pos.quantity)
        # Buy back at worse price (slippage up)
        fill_price = current_price * (1 + self.slippage_rate)
        buy_cost = fill_price * cover_qty
        commission = buy_cost * self.commission_rate

        # PnL = (entry - exit) * qty - commission
        pnl = (pos.entry_price - fill_price) * cover_qty - commission

        # Cash adjustment: we sold at entry, now buy back
        # Net cash change = entry_proceeds - buy_cost - commission
        # But entry proceeds were not added to cash (SHORT model: cash stays as margin)
        # So: cash += pnl (the net effect)
        self._cash += pnl
        self._realized_pnl += pnl

        remaining_qty = pos.quantity - cover_qty
        if remaining_qty <= 1e-12:
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
            pos.quantity = remaining_qty
            pos.unrealized_pnl = (pos.entry_price - current_price) * remaining_qty

        order.status = "FILLED"
        order.filled_quantity = cover_qty
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
                    if pos.side == "LONG":
                        position_value += pos.quantity * price
                    else:  # SHORT: value is the unrealized PnL
                        position_value += pos.unrealized_pnl

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
    # Leverage: liquidation + funding
    # ------------------------------------------------------------------

    def check_liquidation(self, symbol: str, candle) -> bool:
        """Check if position should be liquidated. Returns True if liquidated."""
        with self._lock:
            pos = self._positions.get(symbol)
            if (not pos or pos.status != "OPEN"
                    or pos.leverage <= 1.0 or pos.liquidation_price <= 0):
                return False

            triggered = False
            if pos.side == "LONG" and candle.low <= pos.liquidation_price:
                triggered = True
            elif pos.side == "SHORT" and candle.high >= pos.liquidation_price:
                triggered = True

            if triggered:
                self._liquidate(symbol, pos)
                return True
            return False

    def _liquidate(self, symbol: str, pos: Position) -> None:
        """Execute liquidation -- margin is lost. Must be called while holding _lock."""
        pos.exit_price = pos.liquidation_price
        pos.exit_time = int(time.time() * 1000)
        pos.realized_pnl = -pos.margin_used
        pos.unrealized_pnl = 0.0
        pos.status = "CLOSED"
        pos.quantity = 0.0
        self._closed_positions.append(pos)
        del self._positions[symbol]
        self._cash = 0.0

    def apply_funding(self, symbol: str, current_price: float,
                      funding_rate: float) -> float:
        """Apply funding rate to position. Returns cost deducted."""
        with self._lock:
            pos = self._positions.get(symbol)
            if not pos or pos.status != "OPEN" or pos.leverage <= 1.0:
                return 0.0
            cost = pos.quantity * current_price * funding_rate
            pos.funding_paid += cost
            self._cash -= cost
            return cost

    # ------------------------------------------------------------------
    # Emergency close
    # ------------------------------------------------------------------

    def close_all_positions(self, reason: str = "Manual close") -> List[LiveOrder]:
        """Close every open position at market."""
        with self._lock:
            to_close = [
                (sym, pos.quantity, pos.side)
                for sym, pos in self._positions.items()
                if pos.status == "OPEN"
            ]

        if not to_close:
            return []

        orders: List[LiveOrder] = []
        for sym, qty, side in to_close:
            if side == "LONG":
                order = self.place_order(sym, "SELL", "MARKET", qty, reason=reason)
            else:  # SHORT
                order = self.place_order(sym, "SHORT_CLOSE", "MARKET", qty, reason=reason)
            orders.append(order)
        return orders
