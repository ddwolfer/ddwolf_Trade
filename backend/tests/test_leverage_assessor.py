"""Tests for LeverageAssessor — AI dynamic leverage evaluation."""
import pytest
from models import Candle, OHLCVData, TradeSignal
from services.leverage_service import LeverageAssessor


def _make_trending_ohlcv(n=60, start=100, step=2.0, vol=1.0):
    """Create steady uptrend OHLCV data."""
    candles = []
    for i in range(n):
        price = start + i * step
        candles.append(Candle(
            timestamp=1000 * i,
            open=price - vol * 0.3,
            high=price + vol,
            low=price - vol,
            close=price + vol * 0.3,
            volume=1000,
        ))
    return OHLCVData(symbol="BTCUSDT", interval="4h", candles=candles)


def _make_choppy_ohlcv(n=60, base=100, swing=5.0):
    """Create choppy sideways OHLCV data."""
    candles = []
    for i in range(n):
        if i % 2 == 0:
            c = base + swing * 0.3
        else:
            c = base - swing * 0.3
        candles.append(Candle(
            timestamp=1000 * i,
            open=base,
            high=base + swing,
            low=base - swing,
            close=c,
            volume=1000,
        ))
    return OHLCVData(symbol="BTCUSDT", interval="4h", candles=candles)


class TestLeverageAssessorBounds:
    def test_returns_float(self):
        ohlcv = _make_trending_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=10.0)
        assert isinstance(result, float)

    def test_minimum_leverage_is_one(self):
        ohlcv = _make_choppy_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=10.0)
        assert result >= 1.0

    def test_maximum_leverage_respected(self):
        ohlcv = _make_trending_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=5.0)
        assert result <= 5.0

    def test_leverage_is_integer_or_half(self):
        """Leverage should be rounded to nearest 0.5 for practical use."""
        ohlcv = _make_trending_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=10.0)
        assert result * 2 == int(result * 2), f"Leverage {result} not rounded to 0.5"


class TestLeverageAssessorScoring:
    def test_strong_trend_higher_than_choppy(self):
        """Strong trend should get higher leverage than choppy market."""
        assessor = LeverageAssessor()
        trending = _make_trending_ohlcv(n=80, step=3.0)
        choppy = _make_choppy_ohlcv(n=80, swing=8.0)
        lev_trend = assessor.assess(trending, len(trending.candles) - 1, "LONG", 10.0)
        lev_choppy = assessor.assess(choppy, len(choppy.candles) - 1, "LONG", 10.0)
        assert lev_trend > lev_choppy, f"Trend {lev_trend} should > choppy {lev_choppy}"

    def test_insufficient_data_returns_one(self):
        """Not enough data for indicators → safest leverage (1x)."""
        candles = [Candle(timestamp=i * 1000, open=100, high=101, low=99,
                          close=100, volume=1000) for i in range(5)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, 4, "LONG", 10.0)
        assert result == 1.0


class TestLeverageOverride:
    def test_signal_leverage_used_when_set(self):
        """When TradeSignal has leverage, Assessor is bypassed."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=5.0,
            assessed_leverage=8.0,
            leverage_mode="dynamic",
            fixed_leverage=1.0,
            max_leverage=10.0,
        )
        assert result == 5.0

    def test_signal_leverage_capped_at_max(self):
        """Signal leverage exceeding max gets capped."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=15.0,
            assessed_leverage=8.0,
            leverage_mode="dynamic",
            fixed_leverage=1.0,
            max_leverage=10.0,
        )
        assert result == 10.0

    def test_fixed_mode_uses_fixed_leverage(self):
        """leverage_mode='fixed' uses fixed_leverage value."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=None,
            assessed_leverage=8.0,
            leverage_mode="fixed",
            fixed_leverage=3.0,
            max_leverage=10.0,
        )
        assert result == 3.0

    def test_dynamic_mode_uses_assessed(self):
        """leverage_mode='dynamic' with no signal override uses assessed value."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=None,
            assessed_leverage=7.5,
            leverage_mode="dynamic",
            fixed_leverage=1.0,
            max_leverage=10.0,
        )
        assert result == 7.5
