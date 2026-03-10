"""
Scalp Sniper Strategy — 1m Micro-Swing with Volatility-Gated Entry.

Uses 1m resolution for precise entry timing, but holds for hours like a
swing trade. Only enters on extreme conditions PLUS high volatility to
ensure moves are large enough to overcome transaction costs.

The key insight: on 1m, you can't scalp because tx costs > avg move.
Instead, use 1m for entry PRECISION (catching exact bottoms/tops in
volatile moments), but think like a swing trader (hold 4-8 hours).

Entry: High ATR + Strong trend + RSI extreme + momentum confirmation
Exit: RSI profit-take at opposite extreme, trend reversal, or time stop
Direction: Dual (BUY/SELL + SHORT/COVER)

Signals: BUY/SELL (long) + SHORT/COVER (short)
"""
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class ScalpSniperStrategy(BaseStrategy):
    """1m Micro-Swing: volatility-gated extreme entry, smart exits.

    Enters only on rare, high-confidence setups:
    1. ATR above average (high volatility = bigger moves)
    2. Strong EMA trend (fast above/below slow)
    3. RSI at extreme level + bounce confirmation

    Exits via:
    - RSI profit-take at opposite extreme
    - Trend reversal (EMA cross back)
    - Time stop after max_hold candles
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Scalp Sniper",
            "description": "1m micro-swing: ATR+RSI extreme entry, smart exits (RSI profit-take, trend reversal, time stop).",
            "category": "scalping",
            "parameters": {
                "ema_fast": {
                    "type": "int", "default": 50, "min": 10, "max": 200,
                    "description": "Fast EMA for trend confirmation"
                },
                "ema_slow": {
                    "type": "int", "default": 200, "min": 50, "max": 500,
                    "description": "Slow EMA for macro trend direction"
                },
                "rsi_period": {
                    "type": "int", "default": 14, "min": 5, "max": 30,
                    "description": "RSI calculation period"
                },
                "rsi_entry_long": {
                    "type": "float", "default": 20.0, "min": 10.0, "max": 35.0,
                    "description": "RSI must have been below this to trigger long entry"
                },
                "rsi_entry_short": {
                    "type": "float", "default": 80.0, "min": 65.0, "max": 90.0,
                    "description": "RSI must have been above this to trigger short entry"
                },
                "rsi_confirm_long": {
                    "type": "float", "default": 35.0, "min": 20.0, "max": 50.0,
                    "description": "RSI must cross above this to confirm long entry"
                },
                "rsi_confirm_short": {
                    "type": "float", "default": 65.0, "min": 50.0, "max": 80.0,
                    "description": "RSI must cross below this to confirm short entry"
                },
                "rsi_exit_long": {
                    "type": "float", "default": 70.0, "min": 60.0, "max": 85.0,
                    "description": "RSI profit-take level for longs"
                },
                "rsi_exit_short": {
                    "type": "float", "default": 30.0, "min": 15.0, "max": 40.0,
                    "description": "RSI profit-take level for shorts"
                },
                "lookback": {
                    "type": "int", "default": 20, "min": 5, "max": 60,
                    "description": "Candles to look back for RSI extreme"
                },
                "atr_period": {
                    "type": "int", "default": 60, "min": 14, "max": 120,
                    "description": "ATR period for volatility measurement"
                },
                "atr_avg_period": {
                    "type": "int", "default": 240, "min": 60, "max": 720,
                    "description": "Period for averaging ATR (baseline volatility)"
                },
                "atr_mult": {
                    "type": "float", "default": 1.2, "min": 0.0, "max": 3.0,
                    "description": "ATR must be above avg*mult to allow entry (0=disabled)"
                },
                "cooldown": {
                    "type": "int", "default": 60, "min": 10, "max": 300,
                    "description": "Minimum candles between entries"
                },
                "max_hold": {
                    "type": "int", "default": 360, "min": 60, "max": 1440,
                    "description": "Max candles to hold (360 = 6 hours on 1m)"
                },
                "min_hold": {
                    "type": "int", "default": 30, "min": 5, "max": 120,
                    "description": "Minimum candles before allowing exit signals"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        ema_fast_p = self.params["ema_fast"]
        ema_slow_p = self.params["ema_slow"]
        rsi_period = self.params["rsi_period"]
        lookback = self.params["lookback"]
        cooldown = self.params["cooldown"]
        atr_period = self.params["atr_period"]
        atr_avg_period = self.params["atr_avg_period"]

        warmup = max(ema_slow_p, rsi_period + lookback, atr_avg_period) + 2
        if index < warmup:
            return None

        # --- Cache indicators ---
        closes = ohlcv.closes()
        highs = ohlcv.highs()
        lows = ohlcv.lows()

        ema_fast_vals = self.cache_indicator(
            f"ema_{ema_fast_p}", lambda: ind.ema(closes, ema_fast_p)
        )
        ema_slow_vals = self.cache_indicator(
            f"ema_{ema_slow_p}", lambda: ind.ema(closes, ema_slow_p)
        )
        rsi_vals = self.cache_indicator(
            f"rsi_{rsi_period}", lambda: ind.rsi(closes, rsi_period)
        )
        atr_vals = self.cache_indicator(
            f"atr_{atr_period}", lambda: ind.atr(highs, lows, closes, atr_period)
        )

        if (ema_fast_vals[index] is None or ema_slow_vals[index] is None
                or rsi_vals[index] is None or atr_vals[index] is None):
            return None

        # --- State tracking ---
        # [0] = last entry index, [1] = signal type ('BUY'/'SHORT'/'')
        state = self.cache_indicator("_state", lambda: [0, ''])
        last_entry_idx = state[0]
        last_signal_type = state[1]
        max_hold = self.params["max_hold"]
        min_hold = self.params["min_hold"]

        candle = ohlcv.candles[index]
        price = candle.close
        ema_f = ema_fast_vals[index]
        ema_s = ema_slow_vals[index]
        rsi_now = rsi_vals[index]
        bars_held = index - last_entry_idx

        # === EXIT LOGIC (only when in position) ===
        if last_signal_type in ('BUY', 'SHORT'):
            # --- Time stop ---
            if bars_held >= max_hold:
                exit_type = "SELL" if last_signal_type == 'BUY' else "COVER"
                state[1] = ''
                return TradeSignal(
                    timestamp=candle.timestamp,
                    signal_type=exit_type,
                    price=price,
                    reason=f"Sniper time stop: held {bars_held} candles"
                )

            # --- Smart exits (only after min_hold) ---
            if bars_held >= min_hold:
                rsi_exit_long = self.params["rsi_exit_long"]
                rsi_exit_short = self.params["rsi_exit_short"]

                # RSI profit-take for longs
                if last_signal_type == 'BUY' and rsi_now >= rsi_exit_long:
                    state[1] = ''
                    return TradeSignal(
                        timestamp=candle.timestamp,
                        signal_type="SELL",
                        price=price,
                        reason=f"Sniper profit-take: RSI={rsi_now:.1f} >= {rsi_exit_long}"
                    )

                # RSI profit-take for shorts
                if last_signal_type == 'SHORT' and rsi_now <= rsi_exit_short:
                    state[1] = ''
                    return TradeSignal(
                        timestamp=candle.timestamp,
                        signal_type="COVER",
                        price=price,
                        reason=f"Sniper profit-take: RSI={rsi_now:.1f} <= {rsi_exit_short}"
                    )

                # Trend reversal exit (EMA cross back)
                if last_signal_type == 'BUY' and ema_f < ema_s:
                    state[1] = ''
                    return TradeSignal(
                        timestamp=candle.timestamp,
                        signal_type="SELL",
                        price=price,
                        reason=f"Sniper trend reversal: EMA crossed down"
                    )

                if last_signal_type == 'SHORT' and ema_f > ema_s:
                    state[1] = ''
                    return TradeSignal(
                        timestamp=candle.timestamp,
                        signal_type="COVER",
                        price=price,
                        reason=f"Sniper trend reversal: EMA crossed up"
                    )

            # While in position, don't generate new entries
            return None

        # --- Cooldown: don't re-enter too soon ---
        if bars_held < cooldown:
            return None

        # === VOLATILITY GATE ===
        atr_now = atr_vals[index]
        # Calculate average ATR over atr_avg_period
        atr_sum = 0.0
        atr_count = 0
        for j in range(max(0, index - atr_avg_period), index):
            if atr_vals[j] is not None:
                atr_sum += atr_vals[j]
                atr_count += 1
        if atr_count == 0:
            return None
        atr_avg = atr_sum / atr_count
        atr_mult = self.params["atr_mult"]

        if atr_now < atr_avg * atr_mult:
            return None  # Low volatility — skip

        rsi_entry_long = self.params["rsi_entry_long"]
        rsi_entry_short = self.params["rsi_entry_short"]
        rsi_confirm_long = self.params["rsi_confirm_long"]
        rsi_confirm_short = self.params["rsi_confirm_short"]

        # --- Trend ---
        uptrend = ema_f > ema_s
        downtrend = ema_f < ema_s

        # --- Check RSI extreme within lookback ---
        was_oversold = False
        was_overbought = False
        for j in range(max(0, index - lookback), index):
            if rsi_vals[j] is not None:
                if rsi_vals[j] <= rsi_entry_long:
                    was_oversold = True
                if rsi_vals[j] >= rsi_entry_short:
                    was_overbought = True

        # === LONG ENTRY ===
        if (uptrend
                and was_oversold
                and rsi_now >= rsi_confirm_long
                and rsi_now < 55):
            state[0] = index
            state[1] = 'BUY'
            return TradeSignal(
                timestamp=candle.timestamp,
                signal_type="BUY",
                price=price,
                reason=f"Sniper BUY: uptrend + RSI bounce + ATR={atr_now:.0f}>{atr_avg:.0f}"
            )

        # === SHORT ENTRY ===
        if (downtrend
                and was_overbought
                and rsi_now <= rsi_confirm_short
                and rsi_now > 45):
            state[0] = index
            state[1] = 'SHORT'
            return TradeSignal(
                timestamp=candle.timestamp,
                signal_type="SHORT",
                price=price,
                reason=f"Sniper SHORT: downtrend + RSI drop + ATR={atr_now:.0f}>{atr_avg:.0f}"
            )

        return None
