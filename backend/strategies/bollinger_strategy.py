from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class BollingerStrategy(BaseStrategy):
    """Bollinger Bands mean reversion strategy."""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Bollinger Bands",
            "description": "Buy when price touches lower band (oversold), sell when price touches upper band (overbought).",
            "category": "mean_reversion",
            "parameters": {
                "period": {"type": "int", "default": 20, "min": 10, "max": 50, "description": "SMA period for middle band"},
                "std_dev": {"type": "float", "default": 2.0, "min": 1.0, "max": 3.5, "description": "Standard deviation multiplier"},
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        period = self.params["period"]
        if index < period:
            return None

        key = f"bb_{period}_{self.params['std_dev']}"
        upper, middle, lower = self.cache_indicator(
            key,
            lambda: ind.bollinger_bands(ohlcv.closes(), period, self.params["std_dev"])
        )

        if lower[index] is None or upper[index] is None:
            return None

        candle = ohlcv.candles[index]
        if candle.close <= lower[index]:
            return TradeSignal(candle.timestamp, "BUY", candle.close,
                             f"Price {candle.close:.2f} <= Lower BB {lower[index]:.2f}")
        elif candle.close >= upper[index]:
            return TradeSignal(candle.timestamp, "SELL", candle.close,
                             f"Price {candle.close:.2f} >= Upper BB {upper[index]:.2f}")
        return None
