"""
Bear Hunter Strategy — SHORT-focused mean-reversion strategy for bearish regimes.

Identifies overbought bounces within downtrends and opens SHORT positions,
profiting when price reverts back down. Uses EMA trend filter for entry only;
exits are RSI-driven to avoid premature cover on regime whipsaws.

Signals: SHORT (open short) / COVER (close short)
"""
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class BearHunterStrategy(BaseStrategy):
    """SHORT-focused strategy for bearish/ranging markets.

    Regime detection: EMA(fast) < EMA(slow) = bearish regime (entry filter only).
    Entry: SHORT when bearish regime AND RSI > overbought.
    Exit: COVER when RSI < oversold OR RSI crosses below midline from above.
    Regime only gates entries, not exits — avoids premature cover on EMA whipsaws.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Bear Hunter",
            "description": "SHORT overbought bounces in bearish regimes (EMA trend filter + RSI entry/exit).",
            "category": "mean_reversion",
            "parameters": {
                "ema_fast": {
                    "type": "int", "default": 20, "min": 5, "max": 50,
                    "description": "Fast EMA period for regime detection"
                },
                "ema_slow": {
                    "type": "int", "default": 50, "min": 20, "max": 200,
                    "description": "Slow EMA period for regime detection"
                },
                "rsi_period": {
                    "type": "int", "default": 14, "min": 5, "max": 30,
                    "description": "RSI calculation period"
                },
                "rsi_overbought": {
                    "type": "float", "default": 65.0, "min": 55.0, "max": 85.0,
                    "description": "RSI level to trigger SHORT entry"
                },
                "rsi_oversold": {
                    "type": "float", "default": 30.0, "min": 15.0, "max": 45.0,
                    "description": "RSI level to trigger COVER exit"
                },
                "rsi_midline": {
                    "type": "float", "default": 45.0, "min": 35.0, "max": 55.0,
                    "description": "RSI midline — COVER when RSI crosses below this"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        ema_fast_p = self.params["ema_fast"]
        ema_slow_p = self.params["ema_slow"]
        rsi_period = self.params["rsi_period"]
        rsi_ob = self.params["rsi_overbought"]
        rsi_os = self.params["rsi_oversold"]
        rsi_mid = self.params["rsi_midline"]

        # Need enough data for slowest indicator
        warmup = max(ema_slow_p, rsi_period) + 2
        if index < warmup:
            return None

        # --- Cache indicators ---
        closes = ohlcv.closes()

        ema_fast_vals = self.cache_indicator(
            f"ema_{ema_fast_p}", lambda: ind.ema(closes, ema_fast_p)
        )
        ema_slow_vals = self.cache_indicator(
            f"ema_{ema_slow_p}", lambda: ind.ema(closes, ema_slow_p)
        )
        rsi_vals = self.cache_indicator(
            f"rsi_{rsi_period}", lambda: ind.rsi(closes, rsi_period)
        )

        # Validate indicator values exist
        if (ema_fast_vals[index] is None or ema_slow_vals[index] is None
                or rsi_vals[index] is None or rsi_vals[index - 1] is None):
            return None

        candle = ohlcv.candles[index]
        ema_f = ema_fast_vals[index]
        ema_s = ema_slow_vals[index]
        rsi_now = rsi_vals[index]
        rsi_prev = rsi_vals[index - 1]

        # --- Regime detection (entry filter only) ---
        is_bearish = ema_f < ema_s

        # --- Entry: SHORT when overbought in bearish regime ---
        if is_bearish and rsi_now > rsi_ob:
            return TradeSignal(
                timestamp=candle.timestamp,
                signal_type="SHORT",
                price=candle.close,
                reason=(
                    f"Bear regime (EMA{ema_fast_p}<EMA{ema_slow_p}), "
                    f"RSI={rsi_now:.1f}>{rsi_ob}"
                )
            )

        # --- Exit: COVER on oversold OR RSI crossing below midline ---
        if rsi_now < rsi_os:
            return TradeSignal(
                timestamp=candle.timestamp,
                signal_type="COVER",
                price=candle.close,
                reason=f"Oversold RSI={rsi_now:.1f}<{rsi_os}"
            )

        # RSI crossed below midline (momentum fading, take profits)
        if rsi_prev >= rsi_mid and rsi_now < rsi_mid:
            return TradeSignal(
                timestamp=candle.timestamp,
                signal_type="COVER",
                price=candle.close,
                reason=f"RSI crossed below midline {rsi_mid} ({rsi_prev:.1f}->{rsi_now:.1f})"
            )

        return None
