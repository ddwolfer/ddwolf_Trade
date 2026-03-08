"""
Trend Rider Strategy — designed to beat DCA/Buy & Hold in trending markets.

Core idea: Stay in the trade as long as the trend is intact.
Only exit when the trend truly reverses, minimizing whipsaws and fees.

Uses EMA crossover for trend direction + ATR trailing stop for exit protection.
"""
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class TrendRiderStrategy(BaseStrategy):
    """Trend-following strategy that rides trends and minimizes exits.

    Entry: Fast EMA crosses above Slow EMA (trend confirmed bullish).
    Exit: Price drops below ATR-based trailing stop OR Fast EMA crosses below Slow EMA.

    Designed to stay in positions longer than typical strategies,
    reducing fee drag and capturing full trend moves.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Trend Rider",
            "description": "Ride trends using EMA crossover entry + ATR trailing stop exit. Stays in trades longer to capture full moves.",
            "category": "trend_following",
            "parameters": {
                "fast_ema": {
                    "type": "int", "default": 34, "min": 5, "max": 100,
                    "description": "Fast EMA period for trend direction"
                },
                "slow_ema": {
                    "type": "int", "default": 55, "min": 20, "max": 200,
                    "description": "Slow EMA period for trend direction"
                },
                "atr_period": {
                    "type": "int", "default": 14, "min": 5, "max": 50,
                    "description": "ATR period for trailing stop calculation"
                },
                "atr_multiplier": {
                    "type": "float", "default": 4.0, "min": 1.0, "max": 6.0,
                    "description": "ATR multiplier for trailing stop distance (higher = wider stop = fewer exits)"
                },
                "trend_filter_ema": {
                    "type": "int", "default": 100, "min": 50, "max": 300,
                    "description": "Long-term EMA filter — only buy when price is above this"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        fast_period = self.params["fast_ema"]
        slow_period = self.params["slow_ema"]
        atr_period = self.params["atr_period"]
        atr_mult = self.params["atr_multiplier"]
        filter_period = self.params["trend_filter_ema"]

        # Need enough data for the longest indicator
        min_period = max(slow_period, filter_period, atr_period) + 2
        if index < min_period:
            return None

        closes = ohlcv.closes()
        candle = ohlcv.candles[index]

        # Cache indicators
        fast_ema = self.cache_indicator(
            f"ema_{fast_period}", lambda: ind.ema(closes, fast_period)
        )
        slow_ema = self.cache_indicator(
            f"ema_{slow_period}", lambda: ind.ema(closes, slow_period)
        )
        filter_ema = self.cache_indicator(
            f"ema_{filter_period}", lambda: ind.ema(closes, filter_period)
        )
        atr_values = self.cache_indicator(
            f"atr_{atr_period}",
            lambda: ind.atr(ohlcv.highs(), ohlcv.lows(), closes, atr_period)
        )

        # Check indicator availability
        if any(v is None for v in [
            fast_ema[index], fast_ema[index-1],
            slow_ema[index], slow_ema[index-1],
            filter_ema[index], atr_values[index]
        ]):
            return None

        curr_fast = fast_ema[index]
        prev_fast = fast_ema[index - 1]
        curr_slow = slow_ema[index]
        prev_slow = slow_ema[index - 1]
        curr_filter = filter_ema[index]
        curr_atr = atr_values[index]
        price = candle.close

        # === BUY SIGNAL ===
        # Fast EMA crosses above Slow EMA AND price is above long-term filter
        fast_crossed_above = prev_fast <= prev_slow and curr_fast > curr_slow
        price_above_filter = price > curr_filter

        if fast_crossed_above and price_above_filter:
            return TradeSignal(
                candle.timestamp, "BUY", price,
                f"Trend Rider BUY: EMA{fast_period} crossed above EMA{slow_period}, "
                f"price ${price:,.0f} > EMA{filter_period} ${curr_filter:,.0f}"
            )

        # === SELL SIGNAL ===
        # Option 1: Fast EMA crosses below Slow EMA (trend reversal)
        fast_crossed_below = prev_fast >= prev_slow and curr_fast < curr_slow

        # Option 2: ATR trailing stop hit — price drops more than ATR*mult below recent high
        # Calculate trailing stop: highest close in last slow_ema candles minus ATR * multiplier
        lookback = min(slow_period, index + 1)
        recent_high = max(closes[index - lookback + 1:index + 1])
        trailing_stop = recent_high - curr_atr * atr_mult

        stop_hit = price < trailing_stop

        if fast_crossed_below:
            return TradeSignal(
                candle.timestamp, "SELL", price,
                f"Trend Rider SELL: EMA{fast_period} crossed below EMA{slow_period} (trend reversal)"
            )

        if stop_hit:
            return TradeSignal(
                candle.timestamp, "SELL", price,
                f"Trend Rider SELL: ATR trailing stop hit "
                f"(price ${price:,.0f} < stop ${trailing_stop:,.0f}, "
                f"high ${recent_high:,.0f} - {atr_mult}*ATR ${curr_atr:,.0f})"
            )

        return None
