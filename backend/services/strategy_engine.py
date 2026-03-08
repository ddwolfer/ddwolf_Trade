"""
Strategy Engine - executes strategies on historical data candle by candle.

Supports:
- LONG positions (BUY to open, SELL to close)
- SHORT positions (SHORT to open, COVER/BUY to close)
- Stop-loss and take-profit (engine-level, any strategy benefits)
"""
from typing import List, Tuple, Optional
from models import Candle, OHLCVData, Trade, TradeSignal
from strategies.base_strategy import BaseStrategy


class StrategyEngine:
    """Core backtesting engine. Simulates trading candle-by-candle."""

    def __init__(self, commission_rate: float = 0.001, slippage_rate: float = 0.0005):
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

    def run(self, ohlcv: OHLCVData, strategy: BaseStrategy,
            initial_capital: float = 10000.0,
            stop_loss_pct: float = 0.0,
            take_profit_pct: float = 0.0) -> Tuple[List[Trade], List[float], List[int]]:
        """
        Run backtest on OHLCV data with given strategy.

        Args:
            ohlcv: Historical OHLCV data
            strategy: Strategy instance
            initial_capital: Starting capital in USD
            stop_loss_pct: Stop-loss percentage (0 = disabled). e.g. 5.0 = 5%
            take_profit_pct: Take-profit percentage (0 = disabled). e.g. 10.0 = 10%

        Returns:
            (trades, equity_curve, equity_timestamps)
        """
        capital = initial_capital
        position: Optional[Trade] = None
        trades: List[Trade] = []
        equity_curve: List[float] = []
        equity_timestamps: List[int] = []

        for i in range(len(ohlcv.candles)):
            candle = ohlcv.candles[i]

            # 1. Check SL/TP FIRST (before signal generation)
            if position is not None and (stop_loss_pct > 0 or take_profit_pct > 0):
                sl_tp_result = self._check_sl_tp(
                    position, candle, stop_loss_pct, take_profit_pct
                )
                if sl_tp_result is not None:
                    exit_type, exit_price = sl_tp_result
                    capital = self._close_position(
                        position, candle, exit_price, exit_type,
                        f"{exit_type} at ${exit_price:,.0f}"
                    )
                    trades.append(position)
                    position = None

            # 2. Generate signal
            signal = strategy.generate_signal(ohlcv, i)

            # 3. Process signal
            if signal is not None and position is None:
                # No position — can open LONG or SHORT
                if signal.signal_type == "BUY":
                    position, capital = self._open_long(candle, capital, signal)
                elif signal.signal_type == "SHORT":
                    position, capital = self._open_short(candle, capital, signal)

            elif signal is not None and position is not None:
                if position.side == "LONG":
                    if signal.signal_type == "SELL":
                        # Close LONG
                        capital = self._close_position(
                            position, candle,
                            candle.close * (1 - self.slippage_rate),
                            "SIGNAL", signal.reason
                        )
                        trades.append(position)
                        position = None
                    elif signal.signal_type == "SHORT":
                        # Close LONG then open SHORT
                        capital = self._close_position(
                            position, candle,
                            candle.close * (1 - self.slippage_rate),
                            "SIGNAL", "Reversing to SHORT"
                        )
                        trades.append(position)
                        position = None
                        position, capital = self._open_short(candle, capital, signal)

                elif position.side == "SHORT":
                    if signal.signal_type in ("COVER", "BUY"):
                        # Close SHORT
                        capital = self._close_position(
                            position, candle,
                            candle.close * (1 + self.slippage_rate),
                            "SIGNAL", signal.reason
                        )
                        trades.append(position)
                        position = None
                        # If BUY, also open LONG after closing SHORT
                        if signal.signal_type == "BUY":
                            position, capital = self._open_long(candle, capital, signal)

            # 4. Calculate current equity
            if position is not None:
                if position.side == "LONG":
                    equity = position.quantity * candle.close
                else:  # SHORT
                    equity = capital + (position.entry_price - candle.close) * position.quantity
            else:
                equity = capital
            equity_curve.append(equity)
            equity_timestamps.append(candle.timestamp)

        # Force close any open position at last candle
        if position is not None:
            last_candle = ohlcv.candles[-1]
            if position.side == "LONG":
                exit_price = last_candle.close * (1 - self.slippage_rate)
            else:  # SHORT
                exit_price = last_candle.close * (1 + self.slippage_rate)
            capital = self._close_position(
                position, last_candle, exit_price,
                "FORCED_CLOSE", "End of backtest period"
            )
            trades.append(position)
            equity_curve[-1] = capital

        return trades, equity_curve, equity_timestamps

    # ------------------------------------------------------------------
    # Position management helpers
    # ------------------------------------------------------------------

    def _open_long(self, candle: Candle, capital: float,
                   signal: TradeSignal) -> Tuple[Trade, float]:
        """Open a LONG position. Returns (trade, remaining_capital)."""
        fill_price = candle.close * (1 + self.slippage_rate)
        commission = capital * self.commission_rate
        available = capital - commission
        quantity = available / fill_price

        position = Trade(
            entry_time=candle.timestamp,
            entry_price=fill_price,
            quantity=quantity,
            side="LONG",
            entry_reason=signal.reason,
        )
        return position, 0.0  # All capital in position

    def _open_short(self, candle: Candle, capital: float,
                    signal: TradeSignal) -> Tuple[Trade, float]:
        """
        Open a SHORT position. Returns (trade, remaining_capital).

        SHORT model (1x, no leverage):
        - "Sell borrowed asset" at fill_price
        - Capital stays as collateral/margin
        - PnL tracked as (entry_price - current_price) * quantity
        - Commission deducted from capital at entry
        """
        fill_price = candle.close * (1 - self.slippage_rate)
        commission = capital * self.commission_rate
        available = capital - commission
        quantity = available / fill_price

        position = Trade(
            entry_time=candle.timestamp,
            entry_price=fill_price,
            quantity=quantity,
            side="SHORT",
            entry_reason=signal.reason,
        )
        # Capital remains (it's our margin), minus entry commission
        return position, capital - commission

    def _close_position(self, position: Trade, candle: Candle,
                        exit_price: float, exit_type: str,
                        exit_reason: str) -> float:
        """
        Close a position (LONG or SHORT). Returns new capital.

        Mutates the position object in-place (sets exit fields).
        """
        if position.side == "LONG":
            proceeds = position.quantity * exit_price
            commission = proceeds * self.commission_rate
            capital = proceeds - commission
            position.profit_loss = capital - (position.quantity * position.entry_price)
            position.return_pct = (exit_price / position.entry_price - 1) * 100
        else:  # SHORT
            # Buy back the borrowed asset
            buy_cost = position.quantity * exit_price
            commission = buy_cost * self.commission_rate
            # PnL = (entry - exit) * qty - commission
            pnl = (position.entry_price - exit_price) * position.quantity - commission
            position.profit_loss = pnl
            position.return_pct = (position.entry_price / exit_price - 1) * 100
            # Capital = margin + pnl
            # Note: capital was already passed as the margin amount
            # We need to reconstruct: entry_value + pnl
            entry_value = position.quantity * position.entry_price
            capital = entry_value + pnl

        position.exit_time = candle.timestamp
        position.exit_price = exit_price
        position.exit_type = exit_type
        position.status = "CLOSED"
        position.exit_reason = exit_reason

        return capital

    def _check_sl_tp(self, position: Trade, candle: Candle,
                     stop_loss_pct: float,
                     take_profit_pct: float) -> Optional[Tuple[str, float]]:
        """
        Check if stop-loss or take-profit is hit on this candle.

        Returns (exit_type, exit_price) or None.
        SL takes priority when both trigger in same candle (conservative).
        """
        entry = position.entry_price
        sl_hit = False
        tp_hit = False
        sl_price = 0.0
        tp_price = 0.0

        if position.side == "LONG":
            if stop_loss_pct > 0:
                sl_price = entry * (1 - stop_loss_pct / 100)
                sl_hit = candle.low <= sl_price
            if take_profit_pct > 0:
                tp_price = entry * (1 + take_profit_pct / 100)
                tp_hit = candle.high >= tp_price
        else:  # SHORT
            if stop_loss_pct > 0:
                sl_price = entry * (1 + stop_loss_pct / 100)
                sl_hit = candle.high >= sl_price
            if take_profit_pct > 0:
                tp_price = entry * (1 - take_profit_pct / 100)
                tp_hit = candle.low <= tp_price

        # SL takes priority (conservative)
        if sl_hit:
            return ("STOP_LOSS", sl_price)
        if tp_hit:
            return ("TAKE_PROFIT", tp_price)
        return None
