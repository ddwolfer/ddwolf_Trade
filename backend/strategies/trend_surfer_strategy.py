"""
Trend Surfer Strategy — dual-direction trend-following.

Core idea: Ride trends in BOTH directions.
- Bull market: LONG when SuperTrend flips bullish + EMA confirms
- Bear market: SHORT when SuperTrend flips bearish + EMA confirms

Uses SuperTrend for direction detection and EMA crossover for confirmation.
Designed to capture large trending moves, complementing the mean-reversion
Bear Hunter strategy.
"""
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class TrendSurferStrategy(BaseStrategy):
    """Dual-direction trend-following strategy.

    Entry (LONG): SuperTrend flips bullish AND EMA(fast) > EMA(slow)
    Entry (SHORT): SuperTrend flips bearish AND EMA(fast) < EMA(slow)
    Exit: SuperTrend reversal generates opposite signal, engine handles
          closing current position and opening new one automatically.

    Best used with engine-level ATR trailing stop for profit protection.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Trend Surfer",
            "description": "Dual-direction trend-following: LONG on bullish SuperTrend + EMA, SHORT on bearish. Rides trends both ways.",
            "category": "trend_following",
            "parameters": {
                "atr_period": {
                    "type": "int", "default": 10, "min": 5, "max": 50,
                    "description": "SuperTrend ATR period"
                },
                "multiplier": {
                    "type": "float", "default": 3.0, "min": 1.0, "max": 5.0,
                    "description": "SuperTrend band multiplier"
                },
                "ema_fast": {
                    "type": "int", "default": 20, "min": 5, "max": 100,
                    "description": "Fast EMA period for trend confirmation"
                },
                "ema_slow": {
                    "type": "int", "default": 50, "min": 20, "max": 200,
                    "description": "Slow EMA period for trend confirmation"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        atr_period = self.params["atr_period"]
        multiplier = self.params["multiplier"]
        ema_fast_period = self.params["ema_fast"]
        ema_slow_period = self.params["ema_slow"]

        # Need enough data for all indicators
        min_period = max(ema_slow_period, atr_period) + 2
        if index < min_period:
            return None

        closes = ohlcv.closes()
        candle = ohlcv.candles[index]

        # --- Cache indicators ---
        st_key = f"supertrend_{atr_period}_{multiplier}"
        st_result = self.cache_indicator(
            st_key,
            lambda: ind.supertrend(
                ohlcv.highs(), ohlcv.lows(), closes,
                atr_period, multiplier
            )
        )
        _, direction = st_result

        fast_ema = self.cache_indicator(
            f"ema_{ema_fast_period}",
            lambda: ind.ema(closes, ema_fast_period)
        )
        slow_ema = self.cache_indicator(
            f"ema_{ema_slow_period}",
            lambda: ind.ema(closes, ema_slow_period)
        )

        # --- Check data availability ---
        curr_dir = direction[index]
        prev_dir = direction[index - 1]

        if curr_dir == 0 or prev_dir == 0:
            return None

        if fast_ema[index] is None or slow_ema[index] is None:
            return None

        curr_fast = fast_ema[index]
        curr_slow = slow_ema[index]
        price = candle.close

        # --- BUY SIGNAL ---
        # SuperTrend flips bullish AND EMA confirms uptrend
        st_flipped_bullish = (curr_dir == 1 and prev_dir == -1)
        ema_bullish = (curr_fast > curr_slow)

        if st_flipped_bullish and ema_bullish:
            return TradeSignal(
                candle.timestamp, "BUY", price,
                f"Trend Surfer BUY: SuperTrend flipped bullish, "
                f"EMA{ema_fast_period} ({curr_fast:,.0f}) > "
                f"EMA{ema_slow_period} ({curr_slow:,.0f})"
            )

        # --- SHORT SIGNAL ---
        # SuperTrend flips bearish AND EMA confirms downtrend
        st_flipped_bearish = (curr_dir == -1 and prev_dir == 1)
        ema_bearish = (curr_fast < curr_slow)

        if st_flipped_bearish and ema_bearish:
            return TradeSignal(
                candle.timestamp, "SHORT", price,
                f"Trend Surfer SHORT: SuperTrend flipped bearish, "
                f"EMA{ema_fast_period} ({curr_fast:,.0f}) < "
                f"EMA{ema_slow_period} ({curr_slow:,.0f})"
            )

        # --- EXIT SIGNALS (SuperTrend reversal without EMA confirmation) ---
        # If SuperTrend flips but EMA doesn't confirm, just exit current position
        if st_flipped_bullish and not ema_bullish:
            # SuperTrend turned bullish but EMA still bearish → cover SHORT
            return TradeSignal(
                candle.timestamp, "COVER", price,
                f"Trend Surfer COVER: SuperTrend flipped bullish "
                f"(EMA not confirmed, closing SHORT only)"
            )

        if st_flipped_bearish and not ema_bearish:
            # SuperTrend turned bearish but EMA still bullish → sell LONG
            return TradeSignal(
                candle.timestamp, "SELL", price,
                f"Trend Surfer SELL: SuperTrend flipped bearish "
                f"(EMA not confirmed, closing LONG only)"
            )

        return None
