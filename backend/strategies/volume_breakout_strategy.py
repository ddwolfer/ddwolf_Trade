from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry


@StrategyRegistry.register
class VolumeBreakoutStrategy(BaseStrategy):
    """Volume-confirmed breakout strategy.

    Only enters on breakouts accompanied by above-average volume,
    filtering out false breakouts that lack participation.
    This is the only strategy that uses volume data.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Volume Breakout",
            "description": "Buy when price breaks above N-period high with volume surge. Sell when price breaks below N-period low.",
            "category": "momentum",
            "parameters": {
                "lookback": {
                    "type": "int", "default": 10, "min": 5, "max": 50,
                    "description": "Lookback period for high/low and average volume"
                },
                "vol_multiplier": {
                    "type": "float", "default": 2.5, "min": 1.0, "max": 5.0,
                    "description": "Volume must exceed avg volume by this multiplier to confirm breakout"
                },
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
        avg_volume = sum(c.volume for c in prev_candles) / lookback

        vol_threshold = avg_volume * self.params["vol_multiplier"]

        # BUY: price breaks above N-period high + volume confirmation
        if candle.close > highest and candle.volume > vol_threshold:
            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"Volume Breakout: price {candle.close:.2f} > {lookback}p high {highest:.2f}, "
                f"vol {candle.volume:.1f} > {vol_threshold:.1f}"
            )

        # SELL: price breaks below N-period low (no volume requirement for exits)
        if candle.close < lowest:
            return TradeSignal(
                candle.timestamp, "SELL", candle.close,
                f"Breakdown: price {candle.close:.2f} < {lookback}p low {lowest:.2f}"
            )

        return None
