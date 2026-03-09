"""
Technical Indicator Service
All indicators calculated with pure numpy/pandas - no external TA library needed.
"""
import numpy as np
from typing import List, Tuple, Optional


def sma(data: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    result = [None] * len(data)
    arr = np.array(data, dtype=float)
    for i in range(period - 1, len(arr)):
        result[i] = float(np.mean(arr[i - period + 1:i + 1]))
    return result


def ema(data: List[float], period: int) -> List[Optional[float]]:
    """Exponential Moving Average."""
    result = [None] * len(data)
    if len(data) < period:
        return result
    arr = np.array(data, dtype=float)
    multiplier = 2.0 / (period + 1)
    # Start with SMA
    result[period - 1] = float(np.mean(arr[:period]))
    for i in range(period, len(arr)):
        result[i] = arr[i] * multiplier + result[i - 1] * (1 - multiplier)
    return result


def rsi(data: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index."""
    result = [None] * len(data)
    if len(data) < period + 1:
        return result

    arr = np.array(data, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def macd(data: List[float], fast: int = 12, slow: int = 26,
         signal_period: int = 9) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    MACD: Moving Average Convergence Divergence.
    Returns: (macd_line, signal_line, histogram)
    """
    fast_ema = ema(data, fast)
    slow_ema = ema(data, slow)

    macd_line = [None] * len(data)
    for i in range(len(data)):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]

    # Signal line = EMA of MACD line
    macd_values = [v if v is not None else 0.0 for v in macd_line]
    signal_line = [None] * len(data)

    # Find first valid MACD index
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is not None:
        valid_macd = [macd_line[i] for i in range(first_valid, len(data)) if macd_line[i] is not None]
        if len(valid_macd) >= signal_period:
            sig = ema(valid_macd, signal_period)
            offset = first_valid
            for i, v in enumerate(sig):
                if v is not None and offset + i < len(data):
                    signal_line[offset + i] = v

    histogram = [None] * len(data)
    for i in range(len(data)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


def bollinger_bands(data: List[float], period: int = 20,
                    std_dev: float = 2.0) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    Bollinger Bands.
    Returns: (upper_band, middle_band, lower_band)
    """
    middle = sma(data, period)
    upper = [None] * len(data)
    lower = [None] * len(data)
    arr = np.array(data, dtype=float)

    for i in range(period - 1, len(arr)):
        std = float(np.std(arr[i - period + 1:i + 1]))
        if middle[i] is not None:
            upper[i] = middle[i] + std_dev * std
            lower[i] = middle[i] - std_dev * std

    return upper, middle, lower


def atr(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[Optional[float]]:
    """Average True Range."""
    result = [None] * len(closes)
    if len(closes) < 2:
        return result

    true_ranges = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return result

    # First ATR is SMA
    result[period - 1] = float(np.mean(true_ranges[:period]))
    for i in range(period, len(true_ranges)):
        result[i] = (result[i - 1] * (period - 1) + true_ranges[i]) / period

    return result


def adx(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[Optional[float]]:
    """
    Average Directional Index — measures trend strength (0–100).
    ADX > 25 indicates a strong trend, < 20 indicates weak/no trend.
    """
    n = len(closes)
    result = [None] * n
    if n < 2 * period:
        return result

    # Step 1: Calculate +DM, -DM, TR
    plus_dm = []
    minus_dm = []
    true_ranges = []

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        plus_dm.append(pdm)
        minus_dm.append(mdm)

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    # Step 2: Smooth with Wilder's method (initial = sum of first `period` values)
    if len(true_ranges) < period:
        return result

    smooth_plus_dm = float(sum(plus_dm[:period]))
    smooth_minus_dm = float(sum(minus_dm[:period]))
    smooth_tr = float(sum(true_ranges[:period]))

    # Step 3: Calculate +DI, -DI, DX series
    dx_values = []

    # Compute initial DX from the initial smoothed values
    def _compute_dx(s_plus_dm: float, s_minus_dm: float, s_tr: float) -> float:
        if s_tr == 0:
            return 0.0
        plus_di = (s_plus_dm / s_tr) * 100
        minus_di = (s_minus_dm / s_tr) * 100
        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0.0
        return abs(plus_di - minus_di) / di_sum * 100

    dx_values.append(_compute_dx(smooth_plus_dm, smooth_minus_dm, smooth_tr))

    for i in range(period, len(true_ranges)):
        smooth_plus_dm = smooth_plus_dm - (smooth_plus_dm / period) + plus_dm[i]
        smooth_minus_dm = smooth_minus_dm - (smooth_minus_dm / period) + minus_dm[i]
        smooth_tr = smooth_tr - (smooth_tr / period) + true_ranges[i]
        dx_values.append(_compute_dx(smooth_plus_dm, smooth_minus_dm, smooth_tr))

    # Step 4: ADX = smoothed average of DX
    if len(dx_values) < period:
        return result

    adx_val = float(np.mean(dx_values[:period]))
    # First ADX at index: period (initial smooth uses candles 1..period) + period-1 (ADX smooth) = 2*period - 1
    first_idx = 2 * period - 1
    if first_idx < n:
        result[first_idx] = adx_val

    for i in range(period, len(dx_values)):
        adx_val = (adx_val * (period - 1) + dx_values[i]) / period
        idx = first_idx + (i - period + 1)
        if idx < n:
            result[idx] = adx_val

    return result


def stochastic(highs: List[float], lows: List[float], closes: List[float],
               k_period: int = 14, d_period: int = 3) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Stochastic Oscillator. Returns (%K, %D)."""
    k_values = [None] * len(closes)

    for i in range(k_period - 1, len(closes)):
        h = max(highs[i - k_period + 1:i + 1])
        l = min(lows[i - k_period + 1:i + 1])
        if h != l:
            k_values[i] = ((closes[i] - l) / (h - l)) * 100
        else:
            k_values[i] = 50.0

    # %D = SMA of %K
    d_values = [None] * len(closes)
    valid_k = [(i, v) for i, v in enumerate(k_values) if v is not None]
    if len(valid_k) >= d_period:
        for j in range(d_period - 1, len(valid_k)):
            idx = valid_k[j][0]
            vals = [valid_k[j - d_period + 1 + k][1] for k in range(d_period)]
            d_values[idx] = float(np.mean(vals))

    return k_values, d_values


def supertrend(highs: List[float], lows: List[float], closes: List[float],
               atr_period: int = 10, multiplier: float = 3.0) -> Tuple[List[Optional[float]], List[int]]:
    """
    SuperTrend indicator.
    Returns: (supertrend_values, direction)
      - supertrend_values: the SuperTrend line price
      - direction: 1 = bullish (uptrend), -1 = bearish (downtrend)
    """
    n = len(closes)
    atr_values = atr(highs, lows, closes, atr_period)

    st_values = [None] * n
    direction = [0] * n
    upper_band = [0.0] * n
    lower_band = [0.0] * n

    for i in range(atr_period, n):
        if atr_values[i] is None:
            continue

        hl2 = (highs[i] + lows[i]) / 2.0
        upper_band[i] = hl2 + multiplier * atr_values[i]
        lower_band[i] = hl2 - multiplier * atr_values[i]

        if i == atr_period:
            direction[i] = 1 if closes[i] > upper_band[i] else -1
            st_values[i] = lower_band[i] if direction[i] == 1 else upper_band[i]
            continue

        # Ratchet bands: only tighten, never widen against the trend
        if lower_band[i] < lower_band[i - 1] and closes[i - 1] > lower_band[i - 1]:
            lower_band[i] = lower_band[i - 1]
        if upper_band[i] > upper_band[i - 1] and closes[i - 1] < upper_band[i - 1]:
            upper_band[i] = upper_band[i - 1]

        # Determine direction
        if direction[i - 1] == 1:
            if closes[i] < lower_band[i]:
                direction[i] = -1
                st_values[i] = upper_band[i]
            else:
                direction[i] = 1
                st_values[i] = lower_band[i]
        else:
            if closes[i] > upper_band[i]:
                direction[i] = 1
                st_values[i] = lower_band[i]
            else:
                direction[i] = -1
                st_values[i] = upper_band[i]

    return st_values, direction
