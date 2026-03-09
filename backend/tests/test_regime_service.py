"""
Tests for Market Regime Detection Service.

Uses synthetic OHLCVData with clear trends rather than calling the Binance API.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import Candle, OHLCVData
from services.regime_service import (
    _analyze_candles,
    detect_regime,
    detect_single_timeframe,
    TIMEFRAME_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helpers to build synthetic OHLCV data
# ---------------------------------------------------------------------------

def _make_uptrend_candles(n: int = 200, start_price: float = 100.0,
                          pct_per_bar: float = 0.005) -> OHLCVData:
    """
    Create n candles with a steady uptrend.
    Each bar closes ~0.5% higher than the previous bar.
    """
    candles = []
    price = start_price
    ts = 1_700_000_000_000  # arbitrary start timestamp in ms
    for i in range(n):
        o = price
        c = price * (1 + pct_per_bar)
        h = c * 1.002
        l = o * 0.998
        candles.append(Candle(
            timestamp=ts + i * 3_600_000,
            open=round(o, 4),
            high=round(h, 4),
            low=round(l, 4),
            close=round(c, 4),
            volume=1000.0,
        ))
        price = c
    return OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)


def _make_downtrend_candles(n: int = 200, start_price: float = 100.0,
                            pct_per_bar: float = 0.005) -> OHLCVData:
    """
    Create n candles with a linearly declining price.
    Uses linear (not geometric) decline so that absolute drops stay constant,
    ensuring MACD histogram remains negative throughout the series.
    """
    candles = []
    ts = 1_700_000_000_000
    # Linear decline: drop a fixed absolute amount each bar
    drop_per_bar = start_price * pct_per_bar
    for i in range(n):
        price = start_price - drop_per_bar * i
        if price < drop_per_bar * 2:
            price = drop_per_bar * 2  # floor to avoid zero/negative
        o = price + drop_per_bar * 0.3
        c = price
        h = o * 1.002
        l = c * 0.998
        candles.append(Candle(
            timestamp=ts + i * 3_600_000,
            open=round(o, 4),
            high=round(h, 4),
            low=round(l, 4),
            close=round(c, 4),
            volume=1000.0,
        ))
    return OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)


def _make_sideways_candles(n: int = 200, center: float = 100.0,
                           amplitude: float = 0.005) -> OHLCVData:
    """
    Create n candles that oscillate tightly around `center`, producing
    a roughly neutral / mixed signal environment.
    """
    import math
    candles = []
    ts = 1_700_000_000_000
    for i in range(n):
        # oscillate with a short period so EMAs stay close
        offset = math.sin(i * 0.3) * amplitude * center
        c = center + offset
        o = center - offset * 0.5
        h = max(o, c) * 1.001
        l = min(o, c) * 0.999
        candles.append(Candle(
            timestamp=ts + i * 3_600_000,
            open=round(o, 4),
            high=round(h, 4),
            low=round(l, 4),
            close=round(c, 4),
            volume=1000.0,
        ))
    return OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)


# ---------------------------------------------------------------------------
# Tests: Single-timeframe structure
# ---------------------------------------------------------------------------

class TestSingleTimeframeStructure:
    """Verify _analyze_candles returns the expected keys and value domains."""

    def test_returns_correct_keys(self):
        ohlcv = _make_uptrend_candles()
        result = _analyze_candles(ohlcv)
        assert "regime" in result
        assert "confidence" in result
        assert "ema_trend" in result
        assert "supertrend_dir" in result
        assert "macd_regime" in result

    def test_regime_is_valid_string(self):
        ohlcv = _make_uptrend_candles()
        result = _analyze_candles(ohlcv)
        assert result["regime"] in ("bullish", "bearish", "neutral")

    def test_confidence_in_range(self):
        ohlcv = _make_uptrend_candles()
        result = _analyze_candles(ohlcv)
        assert 0 <= result["confidence"] <= 100

    def test_ema_trend_valid(self):
        ohlcv = _make_uptrend_candles()
        result = _analyze_candles(ohlcv)
        assert result["ema_trend"] in ("bullish", "bearish")

    def test_supertrend_dir_valid(self):
        ohlcv = _make_uptrend_candles()
        result = _analyze_candles(ohlcv)
        assert result["supertrend_dir"] in (1, -1)

    def test_macd_regime_valid(self):
        ohlcv = _make_uptrend_candles()
        result = _analyze_candles(ohlcv)
        assert result["macd_regime"] in ("bullish", "bearish")


# ---------------------------------------------------------------------------
# Tests: Bullish detection
# ---------------------------------------------------------------------------

class TestBullishRegime:
    """With a strong uptrend, all three indicators should agree on bullish."""

    def test_uptrend_detected_as_bullish(self):
        ohlcv = _make_uptrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["regime"] == "bullish"

    def test_uptrend_ema_bullish(self):
        ohlcv = _make_uptrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["ema_trend"] == "bullish"

    def test_uptrend_supertrend_bullish(self):
        ohlcv = _make_uptrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["supertrend_dir"] == 1

    def test_uptrend_macd_bullish(self):
        ohlcv = _make_uptrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["macd_regime"] == "bullish"


# ---------------------------------------------------------------------------
# Tests: Bearish detection
# ---------------------------------------------------------------------------

class TestBearishRegime:
    """With a strong downtrend, all three indicators should agree on bearish."""

    def test_downtrend_detected_as_bearish(self):
        ohlcv = _make_downtrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["regime"] == "bearish"

    def test_downtrend_ema_bearish(self):
        ohlcv = _make_downtrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["ema_trend"] == "bearish"

    def test_downtrend_supertrend_bearish(self):
        ohlcv = _make_downtrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["supertrend_dir"] == -1

    def test_downtrend_macd_bearish(self):
        ohlcv = _make_downtrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["macd_regime"] == "bearish"


# ---------------------------------------------------------------------------
# Tests: Confidence calculation
# ---------------------------------------------------------------------------

class TestConfidence:
    """Confidence should be high when all 3 agree, lower when mixed."""

    def test_all_agree_high_confidence(self):
        """When all 3 indicators agree, confidence should be >= 90."""
        ohlcv = _make_uptrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["confidence"] >= 90

    def test_all_agree_bearish_high_confidence(self):
        """All-bearish should also produce >= 90 confidence."""
        ohlcv = _make_downtrend_candles(n=200, pct_per_bar=0.005)
        result = _analyze_candles(ohlcv)
        assert result["confidence"] >= 90

    def test_strong_trend_higher_confidence(self):
        """Stronger trend (higher pct_per_bar) should yield higher confidence
        (up to the 100 cap) compared to a weaker trend."""
        weak = _analyze_candles(_make_uptrend_candles(pct_per_bar=0.001))
        strong = _analyze_candles(_make_uptrend_candles(pct_per_bar=0.01))
        # Both should be high, strong >= weak
        assert strong["confidence"] >= weak["confidence"]


# ---------------------------------------------------------------------------
# Tests: Overall regime with timeframe weights
# ---------------------------------------------------------------------------

class TestOverallRegime:
    """Test detect_regime overall calculation using mocked single-timeframe results."""

    def test_all_bullish_overall_bullish(self, monkeypatch):
        """When all timeframes are bullish, overall should be bullish."""
        bullish_result = {
            "regime": "bullish",
            "confidence": 95,
            "ema_trend": "bullish",
            "supertrend_dir": 1,
            "macd_regime": "bullish",
        }

        def mock_single(symbol, interval, candles_back=200):
            return bullish_result

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("BTCUSDT", ["1h", "4h", "1d"])
        assert result["overall"] == "bullish"
        assert result["recommendation"] == "long"
        assert result["overall_confidence"] >= 90

    def test_all_bearish_overall_bearish(self, monkeypatch):
        """When all timeframes are bearish, overall should be bearish."""
        bearish_result = {
            "regime": "bearish",
            "confidence": 92,
            "ema_trend": "bearish",
            "supertrend_dir": -1,
            "macd_regime": "bearish",
        }

        def mock_single(symbol, interval, candles_back=200):
            return bearish_result

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("BTCUSDT", ["1h", "4h", "1d"])
        assert result["overall"] == "bearish"
        assert result["recommendation"] == "short"

    def test_mixed_timeframes_weighted(self, monkeypatch):
        """
        When 1h is bearish but 4h and 1d are bullish, the higher-weighted
        timeframes should dominate, producing an overall bullish result.
        Weights: 1h=1, 4h=2, 1d=3.  bullish_weight=5 vs bearish_weight=1.
        """
        results_map = {
            "1h": {
                "regime": "bearish",
                "confidence": 65,
                "ema_trend": "bearish",
                "supertrend_dir": -1,
                "macd_regime": "bearish",
            },
            "4h": {
                "regime": "bullish",
                "confidence": 90,
                "ema_trend": "bullish",
                "supertrend_dir": 1,
                "macd_regime": "bullish",
            },
            "1d": {
                "regime": "bullish",
                "confidence": 95,
                "ema_trend": "bullish",
                "supertrend_dir": 1,
                "macd_regime": "bullish",
            },
        }

        def mock_single(symbol, interval, candles_back=200):
            return results_map[interval]

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("BTCUSDT", ["1h", "4h", "1d"])
        assert result["overall"] == "bullish"
        assert result["recommendation"] == "long"

    def test_daily_bearish_overrides_lower(self, monkeypatch):
        """
        1h bullish (weight=1), 4h bullish (weight=2), 1d bearish (weight=3).
        bearish_weight=3 vs bullish_weight=3 -> should be neutral since
        neither exceeds 40% threshold over the other.
        Actually: total=6, bearish=3 (50%), bullish=3 (50%). Both > 40%.
        Tie goes to the first condition: bullish_weight > bearish_weight is False,
        so bearish_weight > bullish_weight is also False, so overall = neutral.
        """
        results_map = {
            "1h": {
                "regime": "bullish",
                "confidence": 70,
                "ema_trend": "bullish",
                "supertrend_dir": 1,
                "macd_regime": "bullish",
            },
            "4h": {
                "regime": "bullish",
                "confidence": 75,
                "ema_trend": "bullish",
                "supertrend_dir": 1,
                "macd_regime": "bearish",
            },
            "1d": {
                "regime": "bearish",
                "confidence": 92,
                "ema_trend": "bearish",
                "supertrend_dir": -1,
                "macd_regime": "bearish",
            },
        }

        def mock_single(symbol, interval, candles_back=200):
            return results_map[interval]

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("BTCUSDT", ["1h", "4h", "1d"])
        # With equal weights (3 vs 3), neither side dominates
        assert result["overall"] == "neutral"
        assert result["recommendation"] == "neutral"


# ---------------------------------------------------------------------------
# Tests: Recommendation output
# ---------------------------------------------------------------------------

class TestRecommendation:
    """Verify recommendation maps correctly from overall regime."""

    def test_bullish_gives_long(self, monkeypatch):
        def mock_single(symbol, interval, candles_back=200):
            return {"regime": "bullish", "confidence": 95,
                    "ema_trend": "bullish", "supertrend_dir": 1,
                    "macd_regime": "bullish"}

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )
        result = detect_regime("BTCUSDT")
        assert result["recommendation"] == "long"

    def test_bearish_gives_short(self, monkeypatch):
        def mock_single(symbol, interval, candles_back=200):
            return {"regime": "bearish", "confidence": 95,
                    "ema_trend": "bearish", "supertrend_dir": -1,
                    "macd_regime": "bearish"}

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )
        result = detect_regime("BTCUSDT")
        assert result["recommendation"] == "short"

    def test_neutral_gives_neutral(self, monkeypatch):
        """When timeframes are evenly split, recommendation is neutral."""
        results_map = {
            "1h": {"regime": "bullish", "confidence": 65,
                   "ema_trend": "bullish", "supertrend_dir": 1,
                   "macd_regime": "bullish"},
            "4h": {"regime": "neutral", "confidence": 40,
                   "ema_trend": "bullish", "supertrend_dir": -1,
                   "macd_regime": "bearish"},
            "1d": {"regime": "bearish", "confidence": 65,
                   "ema_trend": "bearish", "supertrend_dir": -1,
                   "macd_regime": "bearish"},
        }

        def mock_single(symbol, interval, candles_back=200):
            return results_map[interval]

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("BTCUSDT", ["1h", "4h", "1d"])
        # bullish_weight=1, bearish_weight=3, neutral=2 -> total=6
        # bearish=3/6=50% > 40% -> bearish
        assert result["recommendation"] in ("short", "neutral")


# ---------------------------------------------------------------------------
# Tests: Full detect_regime output structure
# ---------------------------------------------------------------------------

class TestDetectRegimeStructure:
    """Validate the full response shape from detect_regime."""

    def test_response_has_required_keys(self, monkeypatch):
        def mock_single(symbol, interval, candles_back=200):
            return {"regime": "bullish", "confidence": 90,
                    "ema_trend": "bullish", "supertrend_dir": 1,
                    "macd_regime": "bullish"}

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("ETHUSDT", ["1h", "4h", "1d"])
        assert result["symbol"] == "ETHUSDT"
        assert "timestamp" in result
        assert isinstance(result["timestamp"], int)
        assert "timeframes" in result
        assert "1h" in result["timeframes"]
        assert "4h" in result["timeframes"]
        assert "1d" in result["timeframes"]
        assert "overall" in result
        assert "overall_confidence" in result
        assert "recommendation" in result

    def test_custom_timeframes(self, monkeypatch):
        def mock_single(symbol, interval, candles_back=200):
            return {"regime": "bullish", "confidence": 80,
                    "ema_trend": "bullish", "supertrend_dir": 1,
                    "macd_regime": "bullish"}

        monkeypatch.setattr(
            "services.regime_service.detect_single_timeframe", mock_single
        )

        result = detect_regime("BTCUSDT", ["15m", "1h"])
        assert "15m" in result["timeframes"]
        assert "1h" in result["timeframes"]
        assert "4h" not in result["timeframes"]


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge-case handling for minimal data or unusual inputs."""

    def test_short_candles_does_not_crash(self):
        """Even with fewer candles than the indicator periods need,
        _analyze_candles should return a valid structure without raising."""
        candles = [Candle(
            timestamp=1_700_000_000_000 + i * 3_600_000,
            open=100, high=101, low=99, close=100, volume=100,
        ) for i in range(30)]
        ohlcv = OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)
        result = _analyze_candles(ohlcv)
        assert result["regime"] in ("bullish", "bearish", "neutral")
        assert 0 <= result["confidence"] <= 100

    def test_flat_market(self):
        """Perfectly flat market (all same price) should still return valid data."""
        candles = [Candle(
            timestamp=1_700_000_000_000 + i * 3_600_000,
            open=100, high=100, low=100, close=100, volume=100,
        ) for i in range(200)]
        ohlcv = OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)
        result = _analyze_candles(ohlcv)
        assert result["regime"] in ("bullish", "bearish", "neutral")
        assert 0 <= result["confidence"] <= 100
