from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class ConfluenceStrategy(BaseStrategy):
    """RSI + MACD multi-indicator confluence strategy.

    Requires both RSI zone confirmation AND MACD momentum shift
    to trigger signals, dramatically reducing false signals.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "RSI+MACD Confluence",
            "description": "Buy when RSI is oversold AND MACD histogram turns bullish. Sell when RSI is overbought AND MACD turns bearish.",
            "category": "composite",
            "parameters": {
                "rsi_period": {
                    "type": "int", "default": 14, "min": 5, "max": 50,
                    "description": "RSI calculation period"
                },
                "overbought": {
                    "type": "float", "default": 65.0, "min": 55, "max": 85,
                    "description": "RSI overbought threshold"
                },
                "oversold": {
                    "type": "float", "default": 35.0, "min": 15, "max": 45,
                    "description": "RSI oversold threshold"
                },
                "macd_fast": {
                    "type": "int", "default": 12, "min": 5, "max": 30,
                    "description": "MACD fast EMA period"
                },
                "macd_slow": {
                    "type": "int", "default": 26, "min": 15, "max": 50,
                    "description": "MACD slow EMA period"
                },
                "macd_signal": {
                    "type": "int", "default": 9, "min": 3, "max": 20,
                    "description": "MACD signal line period"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        macd_slow = self.params["macd_slow"]
        rsi_period = self.params["rsi_period"]
        min_period = max(macd_slow + self.params["macd_signal"], rsi_period) + 2

        if index < min_period:
            return None

        # Cache indicators
        rsi_values = self.cache_indicator(
            f"rsi_{rsi_period}",
            lambda: ind.rsi(ohlcv.closes(), rsi_period)
        )
        macd_key = f"macd_{self.params['macd_fast']}_{macd_slow}_{self.params['macd_signal']}"
        macd_result = self.cache_indicator(
            macd_key,
            lambda: ind.macd(ohlcv.closes(), self.params["macd_fast"],
                           macd_slow, self.params["macd_signal"])
        )
        _, _, histogram = macd_result

        rsi_val = rsi_values[index]
        hist_curr = histogram[index]
        hist_prev = histogram[index - 1]

        if rsi_val is None or hist_curr is None or hist_prev is None:
            return None

        candle = ohlcv.candles[index]

        # BUY: RSI in oversold zone + MACD histogram turning bullish
        if rsi_val <= self.params["oversold"] and hist_curr > hist_prev and hist_prev < 0:
            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"Confluence BUY: RSI={rsi_val:.1f} <= {self.params['oversold']}, MACD hist turning up"
            )

        # SELL: RSI in overbought zone + MACD histogram turning bearish
        if rsi_val >= self.params["overbought"] and hist_curr < hist_prev and hist_prev > 0:
            return TradeSignal(
                candle.timestamp, "SELL", candle.close,
                f"Confluence SELL: RSI={rsi_val:.1f} >= {self.params['overbought']}, MACD hist turning down"
            )

        return None
