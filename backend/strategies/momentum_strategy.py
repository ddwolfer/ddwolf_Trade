from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry


@StrategyRegistry.register
class MomentumStrategy(BaseStrategy):
    """Price breakout / momentum strategy."""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Momentum Breakout",
            "description": "Buy when price breaks above N-period high, sell when price breaks below N-period low.",
            "category": "momentum",
            "parameters": {
                "lookback": {"type": "int", "default": 20, "min": 5, "max": 100, "description": "Lookback period for high/low"},
                "breakout_pct": {"type": "float", "default": 0.0, "min": 0.0, "max": 5.0, "description": "Breakout threshold in % (0 = exact breakout)"},
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        lookback = self.params["lookback"]
        if index < lookback + 1:
            return None

        candle = ohlcv.candles[index]
        prev_candles = ohlcv.candles[index - lookback:index]

        highest = max(c.high for c in prev_candles)
        lowest = min(c.low for c in prev_candles)
        threshold = 1 + self.params["breakout_pct"] / 100.0

        # Breakout above resistance
        if candle.close > highest * threshold:
            return TradeSignal(candle.timestamp, "BUY", candle.close,
                             f"Breakout above {lookback}-period high {highest:.2f}")
        # Breakdown below support
        elif candle.close < lowest / threshold:
            return TradeSignal(candle.timestamp, "SELL", candle.close,
                             f"Breakdown below {lookback}-period low {lowest:.2f}")
        return None
