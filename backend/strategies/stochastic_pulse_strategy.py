"""
Stochastic Pulse — Dual-oscillator mean-reversion for 5m scalping.

Uses Stochastic %K level + RSI level as double confirmation.
Designed for short timeframes (1m~15m) where quick pullbacks
in an uptrend offer buying opportunities.

Entry (BUY) — BOTH conditions:
  1. Stochastic %K < oversold level  (momentum dip)
  2. RSI < rsi_entry                 (confirms dip)

Exit (SELL) — ANY condition:
  1. Stochastic %K > overbought level (momentum recovered)
  2. RSI > rsi_exit                   (overbought zone)

Optional EMA trend filter (set use_trend_filter=1 to enable).
"""
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class StochasticPulseStrategy(BaseStrategy):
    """Dual-oscillator (Stochastic + RSI) mean-reversion for short-timeframe scalping."""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Stochastic Pulse",
            "description": "Dual-oscillator mean-reversion using Stochastic + RSI for 5m scalping.",
            "category": "mean_reversion",
            "parameters": {
                "stoch_k": {"type": "int", "default": 10, "min": 5, "max": 30,
                            "description": "Stochastic %K period"},
                "stoch_d": {"type": "int", "default": 3, "min": 2, "max": 10,
                            "description": "Stochastic %D smoothing period"},
                "stoch_oversold": {"type": "float", "default": 20.0, "min": 10, "max": 45,
                                   "description": "Stochastic oversold threshold for entry"},
                "stoch_overbought": {"type": "float", "default": 85.0, "min": 55, "max": 95,
                                     "description": "Stochastic overbought threshold for exit"},
                "rsi_period": {"type": "int", "default": 10, "min": 5, "max": 30,
                               "description": "RSI calculation period"},
                "rsi_entry": {"type": "float", "default": 35.0, "min": 20, "max": 55,
                              "description": "RSI must be below this to enter"},
                "rsi_exit": {"type": "float", "default": 75.0, "min": 50, "max": 85,
                             "description": "RSI above this triggers exit"},
                "use_trend_filter": {"type": "int", "default": 1, "min": 0, "max": 1,
                                     "description": "Enable EMA trend filter (0=off, 1=on)"},
                "trend_period": {"type": "int", "default": 200, "min": 50, "max": 500,
                                 "description": "EMA period for trend filter (if enabled)"},
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        stoch_k = self.params["stoch_k"]
        stoch_d = self.params["stoch_d"]
        rsi_period = self.params["rsi_period"]
        use_trend = self.params["use_trend_filter"]
        trend_period = self.params["trend_period"]

        # Warmup
        min_period = max(stoch_k + stoch_d, rsi_period + 1)
        if use_trend:
            min_period = max(min_period, trend_period + 1)
        if index < min_period:
            return None

        candle = ohlcv.candles[index]

        # Cache indicators (lambdas capture ohlcv — called only once)
        k_vals, d_vals = self.cache_indicator(
            f"stoch_{stoch_k}_{stoch_d}",
            lambda: ind.stochastic(ohlcv.highs(), ohlcv.lows(), ohlcv.closes(), stoch_k, stoch_d)
        )
        rsi_vals = self.cache_indicator(
            f"rsi_{rsi_period}",
            lambda: ind.rsi(ohlcv.closes(), rsi_period)
        )

        k_curr = k_vals[index]
        rsi_curr = rsi_vals[index]
        if k_curr is None or rsi_curr is None:
            return None

        stoch_oversold = self.params["stoch_oversold"]
        stoch_overbought = self.params["stoch_overbought"]
        rsi_entry = self.params["rsi_entry"]
        rsi_exit = self.params["rsi_exit"]

        # --- EXIT (SELL) — any condition ---
        if k_curr > stoch_overbought:
            return TradeSignal(candle.timestamp, "SELL", candle.close,
                               f"Stoch %K={k_curr:.0f}>{stoch_overbought:.0f}")
        if rsi_curr > rsi_exit:
            return TradeSignal(candle.timestamp, "SELL", candle.close,
                               f"RSI={rsi_curr:.1f}>{rsi_exit:.0f}")

        # --- ENTRY (BUY) — both conditions ---
        if k_curr < stoch_oversold and rsi_curr < rsi_entry:
            # Optional trend filter
            if use_trend:
                ema_vals = self.cache_indicator(
                    f"ema_{trend_period}",
                    lambda: ind.ema(ohlcv.closes(), trend_period)
                )
                ema_curr = ema_vals[index]
                if ema_curr is None or candle.close <= ema_curr:
                    return None

            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"Stoch={k_curr:.0f}<{stoch_oversold:.0f}, RSI={rsi_curr:.1f}<{rsi_entry:.0f}"
            )

        return None
