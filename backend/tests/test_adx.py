"""Tests for ADX (Average Directional Index) indicator."""
import pytest
from services import indicator_service as ind


class TestADX:
    def test_returns_correct_length(self):
        highs = [10 + i * 0.5 for i in range(30)]
        lows = [9 + i * 0.5 for i in range(30)]
        closes = [9.5 + i * 0.5 for i in range(30)]
        result = ind.adx(highs, lows, closes, period=14)
        assert len(result) == 30

    def test_early_values_are_none(self):
        highs = [10 + i * 0.5 for i in range(30)]
        lows = [9 + i * 0.5 for i in range(30)]
        closes = [9.5 + i * 0.5 for i in range(30)]
        result = ind.adx(highs, lows, closes, period=14)
        for i in range(2 * 14 - 2):
            assert result[i] is None

    def test_strong_uptrend_high_adx(self):
        n = 60
        highs = [100 + i * 2.0 for i in range(n)]
        lows = [99 + i * 2.0 for i in range(n)]
        closes = [99.5 + i * 2.0 for i in range(n)]
        result = ind.adx(highs, lows, closes, period=14)
        last = result[-1]
        assert last is not None
        assert last > 25, f"ADX={last}, expected > 25 for strong uptrend"

    def test_choppy_market_low_adx(self):
        n = 60
        highs, lows, closes = [], [], []
        for i in range(n):
            if i % 2 == 0:
                highs.append(101)
                lows.append(99)
                closes.append(100.5)
            else:
                highs.append(101)
                lows.append(99)
                closes.append(99.5)
        result = ind.adx(highs, lows, closes, period=14)
        last = result[-1]
        assert last is not None
        assert last < 25, f"ADX={last}, expected < 25 for choppy market"

    def test_adx_range_0_to_100(self):
        n = 60
        highs = [100 + i * 1.0 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [99.5 + i * 1.0 for i in range(n)]
        result = ind.adx(highs, lows, closes, period=14)
        for v in result:
            if v is not None:
                assert 0 <= v <= 100, f"ADX={v} out of range"

    def test_insufficient_data(self):
        result = ind.adx([10, 11], [9, 10], [9.5, 10.5], period=14)
        assert all(v is None for v in result)
