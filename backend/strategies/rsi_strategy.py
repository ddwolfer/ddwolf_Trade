from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class RSIStrategy(BaseStrategy):
    """RSI overbought/oversold strategy."""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "RSI",
            "description": "Buy when RSI drops below oversold level, sell when RSI rises above overbought level.",
            "category": "mean_reversion",
            "parameters": {
                "period": {"type": "int", "default": 14, "min": 5, "max": 50, "description": "RSI calculation period"},
                "overbought": {"type": "float", "default": 70.0, "min": 55, "max": 95, "description": "Overbought threshold (sell signal)"},
                "oversold": {"type": "float", "default": 30.0, "min": 5, "max": 45, "description": "Oversold threshold (buy signal)"},
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        period = self.params["period"]
        if index < period + 1:
            return None

        rsi_values = self.cache_indicator(
            f"rsi_{period}",
            lambda: ind.rsi(ohlcv.closes(), period)
        )

        val = rsi_values[index]
        if val is None:
            return None

        candle = ohlcv.candles[index]
        if val <= self.params["oversold"]:
            return TradeSignal(candle.timestamp, "BUY", candle.close, f"RSI={val:.1f} <= {self.params['oversold']}")
        elif val >= self.params["overbought"]:
            return TradeSignal(candle.timestamp, "SELL", candle.close, f"RSI={val:.1f} >= {self.params['overbought']}")
        return None
