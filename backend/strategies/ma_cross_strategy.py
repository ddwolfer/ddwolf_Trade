from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class MACrossStrategy(BaseStrategy):
    """Moving Average Crossover strategy."""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "MA Cross",
            "description": "Buy when fast MA crosses above slow MA (golden cross), sell when it crosses below (death cross).",
            "category": "momentum",
            "parameters": {
                "fast_period": {"type": "int", "default": 10, "min": 3, "max": 50, "description": "Fast moving average period"},
                "slow_period": {"type": "int", "default": 30, "min": 10, "max": 200, "description": "Slow moving average period"},
                "ma_type": {"type": "str", "default": "EMA", "min": "EMA", "max": "SMA", "description": "MA type: EMA or SMA"},
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        slow = self.params["slow_period"]
        if index < slow + 1:
            return None

        ma_fn = ind.ema if self.params.get("ma_type", "EMA") == "EMA" else ind.sma
        fast_ma = self.cache_indicator(
            f"fast_ma_{self.params['fast_period']}",
            lambda: ma_fn(ohlcv.closes(), self.params["fast_period"])
        )
        slow_ma = self.cache_indicator(
            f"slow_ma_{slow}",
            lambda: ma_fn(ohlcv.closes(), slow)
        )

        if any(v is None for v in [fast_ma[index], fast_ma[index-1], slow_ma[index], slow_ma[index-1]]):
            return None

        candle = ohlcv.candles[index]
        prev_diff = fast_ma[index - 1] - slow_ma[index - 1]
        curr_diff = fast_ma[index] - slow_ma[index]

        # Golden cross
        if prev_diff <= 0 and curr_diff > 0:
            return TradeSignal(candle.timestamp, "BUY", candle.close, "Golden cross (fast MA > slow MA)")
        # Death cross
        elif prev_diff >= 0 and curr_diff < 0:
            return TradeSignal(candle.timestamp, "SELL", candle.close, "Death cross (fast MA < slow MA)")
        return None
