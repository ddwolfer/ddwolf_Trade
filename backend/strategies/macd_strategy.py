from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class MACDStrategy(BaseStrategy):
    """MACD crossover strategy."""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "MACD",
            "description": "Buy when MACD crosses above signal line, sell when it crosses below.",
            "category": "momentum",
            "parameters": {
                "fast_period": {"type": "int", "default": 12, "min": 5, "max": 30, "description": "Fast EMA period"},
                "slow_period": {"type": "int", "default": 26, "min": 15, "max": 50, "description": "Slow EMA period"},
                "signal_period": {"type": "int", "default": 9, "min": 3, "max": 20, "description": "Signal line period"},
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        slow = self.params["slow_period"]
        if index < slow + self.params["signal_period"] + 1:
            return None

        key = f"macd_{self.params['fast_period']}_{slow}_{self.params['signal_period']}"
        macd_line, signal_line, histogram = self.cache_indicator(
            key,
            lambda: ind.macd(ohlcv.closes(), self.params["fast_period"], slow, self.params["signal_period"])
        )

        if histogram[index] is None or histogram[index - 1] is None:
            return None

        candle = ohlcv.candles[index]
        # Crossover: histogram goes from negative to positive
        if histogram[index - 1] < 0 and histogram[index] >= 0:
            return TradeSignal(candle.timestamp, "BUY", candle.close, "MACD bullish crossover")
        # Crossunder: histogram goes from positive to negative
        elif histogram[index - 1] > 0 and histogram[index] <= 0:
            return TradeSignal(candle.timestamp, "SELL", candle.close, "MACD bearish crossover")
        return None
