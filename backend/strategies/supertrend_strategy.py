from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class SuperTrendStrategy(BaseStrategy):
    """ATR-based SuperTrend trend-following strategy.

    Uses ATR to dynamically calculate trend bands.
    Enters when trend flips bullish, exits when trend flips bearish.
    Excels in trending markets, underperforms in choppy/ranging markets.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "SuperTrend",
            "description": "Buy when SuperTrend flips bullish (price breaks above upper band), sell when it flips bearish.",
            "category": "momentum",
            "parameters": {
                "atr_period": {
                    "type": "int", "default": 10, "min": 5, "max": 50,
                    "description": "ATR calculation period"
                },
                "multiplier": {
                    "type": "float", "default": 2.5, "min": 1.0, "max": 5.0,
                    "description": "ATR multiplier for band width"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        atr_period = self.params["atr_period"]
        if index < atr_period + 2:
            return None

        st_key = f"supertrend_{atr_period}_{self.params['multiplier']}"
        st_result = self.cache_indicator(
            st_key,
            lambda: ind.supertrend(
                ohlcv.highs(), ohlcv.lows(), ohlcv.closes(),
                atr_period, self.params["multiplier"]
            )
        )
        _, direction = st_result

        curr_dir = direction[index]
        prev_dir = direction[index - 1]

        if curr_dir == 0 or prev_dir == 0:
            return None

        candle = ohlcv.candles[index]

        # BUY: trend flips from bearish to bullish
        if curr_dir == 1 and prev_dir == -1:
            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"SuperTrend flipped BULLISH (ATR={atr_period}, mult={self.params['multiplier']})"
            )

        # SELL: trend flips from bullish to bearish
        if curr_dir == -1 and prev_dir == 1:
            return TradeSignal(
                candle.timestamp, "SELL", candle.close,
                f"SuperTrend flipped BEARISH (ATR={atr_period}, mult={self.params['multiplier']})"
            )

        return None
