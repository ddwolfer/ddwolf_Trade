"""
Strategy Engine - executes strategies on historical data candle by candle.
"""
from typing import List, Tuple
from models import OHLCVData, Trade, TradeSignal
from strategies.base_strategy import BaseStrategy


class StrategyEngine:
    """Core backtesting engine. Simulates trading candle-by-candle."""

    def __init__(self, commission_rate: float = 0.001, slippage_rate: float = 0.0005):
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

    def run(self, ohlcv: OHLCVData, strategy: BaseStrategy,
            initial_capital: float = 10000.0) -> Tuple[List[Trade], List[float], List[int]]:
        """
        Run backtest on OHLCV data with given strategy.

        Returns:
            (trades, equity_curve, equity_timestamps)
        """
        capital = initial_capital
        position = None  # Current open trade
        trades: List[Trade] = []
        equity_curve: List[float] = []
        equity_timestamps: List[int] = []

        for i in range(len(ohlcv.candles)):
            candle = ohlcv.candles[i]
            signal = strategy.generate_signal(ohlcv, i)

            if signal is not None:
                if signal.signal_type == "BUY" and position is None:
                    # Open long position
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
                    capital = 0  # All in position

                elif signal.signal_type == "SELL" and position is not None:
                    # Close long position
                    fill_price = candle.close * (1 - self.slippage_rate)
                    proceeds = position.quantity * fill_price
                    commission = proceeds * self.commission_rate
                    capital = proceeds - commission

                    position.exit_time = candle.timestamp
                    position.exit_price = fill_price
                    position.profit_loss = capital - (position.quantity * position.entry_price)
                    position.return_pct = (fill_price / position.entry_price - 1) * 100
                    position.status = "CLOSED"
                    position.exit_reason = signal.reason

                    trades.append(position)
                    position = None

            # Calculate current equity
            if position is not None:
                current_value = position.quantity * candle.close
                equity_curve.append(current_value)
            else:
                equity_curve.append(capital)
            equity_timestamps.append(candle.timestamp)

        # Force close any open position at last candle
        if position is not None:
            last_candle = ohlcv.candles[-1]
            fill_price = last_candle.close * (1 - self.slippage_rate)
            proceeds = position.quantity * fill_price
            commission = proceeds * self.commission_rate
            capital = proceeds - commission

            position.exit_time = last_candle.timestamp
            position.exit_price = fill_price
            position.profit_loss = capital - (position.quantity * position.entry_price)
            position.return_pct = (fill_price / position.entry_price - 1) * 100
            position.status = "CLOSED"
            position.exit_reason = "End of backtest period"
            trades.append(position)
            equity_curve[-1] = capital

        return trades, equity_curve, equity_timestamps
