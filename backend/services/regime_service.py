"""
Market Regime Detection Service.
Analyzes multiple timeframes to determine bull/bear market conditions.
Uses EMA trend, SuperTrend direction, and MACD regime as voting indicators.
"""
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from services.data_service import fetch_klines
from services import indicator_service as ind


# Timeframe weights for overall regime calculation
TIMEFRAME_WEIGHTS = {
    "1m": 0.5,
    "3m": 0.5,
    "5m": 0.5,
    "15m": 0.75,
    "30m": 0.75,
    "1h": 1,
    "2h": 1.5,
    "4h": 2,
    "6h": 2.5,
    "8h": 2.5,
    "12h": 2.5,
    "1d": 3,
    "3d": 3.5,
    "1w": 4,
}

# Approximate number of hours per interval, used to compute candles_back -> days
_INTERVAL_HOURS = {
    "1m": 1 / 60,
    "3m": 3 / 60,
    "5m": 5 / 60,
    "15m": 0.25,
    "30m": 0.5,
    "1h": 1,
    "2h": 2,
    "4h": 4,
    "6h": 6,
    "8h": 8,
    "12h": 12,
    "1d": 24,
    "3d": 72,
    "1w": 168,
}


def _candles_back_to_start_date(interval: str, candles_back: int = 200) -> str:
    """
    Calculate a start_date string that covers approximately `candles_back`
    candles for the given interval, with a small buffer.
    """
    hours = _INTERVAL_HOURS.get(interval, 1)
    total_hours = hours * candles_back * 1.1  # 10% buffer
    start = datetime.utcnow() - timedelta(hours=total_hours)
    return start.strftime("%Y-%m-%d")


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD, plus one day to include today's candles."""
    tomorrow = datetime.utcnow() + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")


def detect_single_timeframe(symbol: str, interval: str,
                            candles_back: int = 200) -> Dict[str, Any]:
    """
    Detect regime for a single timeframe.

    Computes three sub-indicators and combines them via majority voting:
      - EMA Trend: EMA(20) vs EMA(50) — last valid value comparison
      - SuperTrend Direction: last direction value from supertrend(10, 3.0)
      - MACD Regime: last histogram value > 0 means bullish

    Returns dict:
        {
            "regime": "bullish" | "bearish" | "neutral",
            "confidence": 0-100,
            "ema_trend": "bullish" | "bearish",
            "supertrend_dir": 1 | -1,
            "macd_regime": "bullish" | "bearish"
        }
    """
    start_date = _candles_back_to_start_date(interval, candles_back)
    end_date = _today_str()

    ohlcv = fetch_klines(symbol, interval, start_date, end_date)

    return _analyze_candles(ohlcv)


def _analyze_candles(ohlcv) -> Dict[str, Any]:
    """
    Core analysis logic on OHLCVData.  Separated from data fetching
    so it can be tested with synthetic data directly.
    """
    closes = ohlcv.closes()
    highs = ohlcv.highs()
    lows = ohlcv.lows()

    # --- EMA Trend ---
    ema20 = ind.ema(closes, 20)
    ema50 = ind.ema(closes, 50)

    # Find last index where both EMAs are valid
    ema_trend = "bullish"
    ema_diff_pct = 0.0
    for i in range(len(closes) - 1, -1, -1):
        if ema20[i] is not None and ema50[i] is not None:
            ema_diff_pct = (ema20[i] - ema50[i]) / ema50[i] * 100
            ema_trend = "bullish" if ema20[i] > ema50[i] else "bearish"
            break

    # --- SuperTrend Direction ---
    st_values, st_direction = ind.supertrend(highs, lows, closes, 10, 3.0)

    supertrend_dir = 0
    for i in range(len(st_direction) - 1, -1, -1):
        if st_direction[i] != 0:
            supertrend_dir = st_direction[i]
            break

    # --- MACD Regime ---
    # Use the MACD line value (fast EMA - slow EMA) for regime detection.
    # MACD line > 0 means fast EMA is above slow EMA = bullish regime.
    # MACD line < 0 means fast EMA is below slow EMA = bearish regime.
    # (The histogram measures momentum/acceleration, not regime direction.)
    macd_line, signal_line, histogram = ind.macd(closes)

    macd_regime = "bullish"
    macd_line_val = 0.0
    for i in range(len(macd_line) - 1, -1, -1):
        if macd_line[i] is not None:
            macd_line_val = macd_line[i]
            macd_regime = "bullish" if macd_line[i] > 0 else "bearish"
            break

    # --- Voting ---
    bullish_votes = 0
    bearish_votes = 0

    if ema_trend == "bullish":
        bullish_votes += 1
    else:
        bearish_votes += 1

    if supertrend_dir == 1:
        bullish_votes += 1
    elif supertrend_dir == -1:
        bearish_votes += 1

    if macd_regime == "bullish":
        bullish_votes += 1
    else:
        bearish_votes += 1

    # --- Confidence ---
    total_votes = bullish_votes + bearish_votes  # always 3

    if bullish_votes == 3 or bearish_votes == 3:
        # All 3 agree: base confidence 90 + strength bonus up to 10
        strength_bonus = min(10, abs(ema_diff_pct) * 2)
        confidence = 90 + strength_bonus
    elif bullish_votes == 2 or bearish_votes == 2:
        # 2/3 agree: base confidence 60 + strength bonus up to 20
        strength_bonus = min(20, abs(ema_diff_pct) * 3)
        confidence = 60 + strength_bonus
    else:
        # Split: neutral
        confidence = 40

    confidence = min(100, round(confidence, 1))

    # --- Determine regime ---
    if bullish_votes >= 3 or (bullish_votes == 2 and confidence >= 60):
        regime = "bullish"
    elif bearish_votes >= 3 or (bearish_votes == 2 and confidence >= 60):
        regime = "bearish"
    else:
        regime = "neutral"

    return {
        "regime": regime,
        "confidence": confidence,
        "ema_trend": ema_trend,
        "supertrend_dir": supertrend_dir if supertrend_dir != 0 else 1,
        "macd_regime": macd_regime,
    }


def detect_regime(symbol: str, timeframes: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Detect market regime across multiple timeframes.

    Args:
        symbol: Trading pair (e.g. "BTCUSDT")
        timeframes: List of interval strings. Default: ["1h", "4h", "1d"]

    Returns dict with structure:
        {
            "symbol": "BTCUSDT",
            "timestamp": 1709942400000,
            "timeframes": {
                "1h": { "regime", "confidence", "ema_trend", "supertrend_dir", "macd_regime" },
                "4h": { ... },
                "1d": { ... }
            },
            "overall": "bullish" | "bearish" | "neutral",
            "overall_confidence": 0-100,
            "recommendation": "long" | "short" | "neutral"
        }
    """
    if timeframes is None:
        timeframes = ["1h", "4h", "1d"]

    timestamp = int(time.time() * 1000)
    tf_results: Dict[str, Dict[str, Any]] = {}

    for tf in timeframes:
        tf_results[tf] = detect_single_timeframe(symbol, tf)

    # --- Overall regime: weighted vote ---
    bullish_weight = 0.0
    bearish_weight = 0.0
    total_weight = 0.0
    confidence_weighted_sum = 0.0

    for tf, result in tf_results.items():
        w = TIMEFRAME_WEIGHTS.get(tf, 1)
        total_weight += w
        confidence_weighted_sum += result["confidence"] * w

        if result["regime"] == "bullish":
            bullish_weight += w
        elif result["regime"] == "bearish":
            bearish_weight += w
        # neutral contributes to neither

    overall_confidence = round(confidence_weighted_sum / total_weight, 1) if total_weight > 0 else 50

    if bullish_weight > bearish_weight and bullish_weight > total_weight * 0.4:
        overall = "bullish"
    elif bearish_weight > bullish_weight and bearish_weight > total_weight * 0.4:
        overall = "bearish"
    else:
        overall = "neutral"

    # --- Recommendation ---
    if overall == "bullish":
        recommendation = "long"
    elif overall == "bearish":
        recommendation = "short"
    else:
        recommendation = "neutral"

    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "timeframes": tf_results,
        "overall": overall,
        "overall_confidence": overall_confidence,
        "recommendation": recommendation,
    }
