"""
Leverage Assessment Service — AI-powered dynamic leverage evaluation.

Evaluates market conditions before each trade to determine optimal leverage:
- Volatility (ATR/close): low vol → safer for high leverage (40% weight)
- Trend strength (ADX): strong trend → higher leverage (35% weight)
- EMA alignment: triple alignment → high score (25% weight)

Returns leverage rounded to nearest 0.5x for practical use.
"""
import math
from typing import Optional
from models import OHLCVData
from services import indicator_service as ind


class LeverageAssessor:
    """Evaluates market conditions to suggest leverage multiplier."""

    def assess(self, ohlcv: OHLCVData, index: int, side: str,
               max_leverage: float = 10.0) -> float:
        """
        Assess optimal leverage for a trade at the given candle index.

        Args:
            ohlcv: OHLCV data
            index: Current candle index
            side: "LONG" or "SHORT"
            max_leverage: Hard cap on leverage

        Returns:
            Suggested leverage (1.0 ~ max_leverage), rounded to 0.5
        """
        if index < 50:
            return 1.0  # Not enough data for reliable assessment

        closes = ohlcv.closes()
        highs = ohlcv.highs()
        lows = ohlcv.lows()

        vol_score = self._volatility_score(highs, lows, closes, index)
        adx_score = self._adx_score(highs, lows, closes, index)
        ema_score = self._ema_alignment_score(closes, index, side)

        composite = vol_score * 0.4 + adx_score * 0.35 + ema_score * 0.25
        composite = max(0.0, min(1.0, composite))

        raw_leverage = 1.0 + (max_leverage - 1.0) * composite
        # Round to nearest 0.5
        leverage = round(raw_leverage * 2) / 2
        return max(1.0, min(max_leverage, leverage))

    def resolve_leverage(
        self,
        signal_leverage: Optional[float],
        assessed_leverage: float,
        leverage_mode: str,
        fixed_leverage: float,
        max_leverage: float,
    ) -> float:
        """
        Resolve final leverage considering signal override and mode.

        Priority:
        1. TradeSignal.leverage (if set) — capped at max_leverage
        2. leverage_mode="fixed" → fixed_leverage
        3. leverage_mode="dynamic" → assessed_leverage
        """
        if signal_leverage is not None:
            return min(signal_leverage, max_leverage)
        if leverage_mode == "fixed":
            return min(fixed_leverage, max_leverage)
        return min(assessed_leverage, max_leverage)

    def _volatility_score(self, highs: list, lows: list, closes: list,
                          index: int, period: int = 14) -> float:
        """Low volatility = high score (safe for leverage)."""
        atr_values = ind.atr(highs, lows, closes, period)
        atr_val = atr_values[index] if index < len(atr_values) else None
        if atr_val is None or closes[index] == 0:
            return 0.0

        # ATR as % of price
        atr_pct = atr_val / closes[index]
        # Typical crypto ATR%: 1%~8%. Map to score:
        # < 1% → 1.0 (very low vol), > 6% → 0.0 (very high vol)
        score = 1.0 - (atr_pct - 0.01) / 0.05
        return max(0.0, min(1.0, score))

    def _adx_score(self, highs: list, lows: list, closes: list,
                   index: int, period: int = 14) -> float:
        """Strong trend (high ADX) = high score."""
        adx_values = ind.adx(highs, lows, closes, period)
        adx_val = adx_values[index] if index < len(adx_values) else None
        if adx_val is None:
            return 0.0

        # ADX < 15 → 0.0 (no trend), > 40 → 1.0 (very strong trend)
        score = (adx_val - 15) / 25
        return max(0.0, min(1.0, score))

    def _ema_alignment_score(self, closes: list, index: int, side: str,
                             fast: int = 20, mid: int = 50,
                             slow: int = 200) -> float:
        """Triple EMA alignment with trade direction = high score."""
        ema_fast = ind.ema(closes, fast)
        ema_mid = ind.ema(closes, mid)
        ema_slow = ind.ema(closes, slow)

        f = ema_fast[index] if index < len(ema_fast) else None
        m = ema_mid[index] if index < len(ema_mid) else None
        s = ema_slow[index] if index < len(ema_slow) else None

        if f is None or m is None or s is None:
            return 0.0

        if side == "LONG":
            # Perfect: f > m > s
            if f > m > s:
                return 1.0
            elif f > m or f > s:
                return 0.5
            else:
                return 0.1  # EMAs against LONG direction
        else:  # SHORT
            # Perfect: f < m < s
            if f < m < s:
                return 1.0
            elif f < m or f < s:
                return 0.5
            else:
                return 0.1  # EMAs against SHORT direction
