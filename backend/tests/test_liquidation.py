"""Tests for Binance-style liquidation mechanics."""
import pytest
from models import Candle, OHLCVData, Trade, TradeSignal
from services.strategy_engine import StrategyEngine


def _make_candle(i, price, low=None, high=None):
    return Candle(
        timestamp=i * 3600000,
        open=price, high=high or price + 10,
        low=low or price - 10, close=price, volume=1000,
    )


class TestLiquidationPrice:
    def test_check_liquidation_returns_none_when_safe(self):
        """No liquidation when price is far from liq price."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="LONG",
            leverage=5.0, liquidation_price=80.0,
        )
        candle = _make_candle(1, 95, low=85)
        result = engine._check_liquidation(position, candle)
        assert result is None

    def test_long_liquidation_triggered(self):
        """LONG liquidation triggers when candle.low <= liquidation_price."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="LONG",
            leverage=5.0, liquidation_price=80.5,
        )
        candle = _make_candle(1, 82, low=79)  # low breaches 80.5
        result = engine._check_liquidation(position, candle)
        assert result == 80.5

    def test_short_liquidation_triggered(self):
        """SHORT liquidation triggers when candle.high >= liquidation_price."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="SHORT",
            leverage=5.0, liquidation_price=120.0,
        )
        candle = _make_candle(1, 118, high=121)  # high breaches 120
        result = engine._check_liquidation(position, candle)
        assert result == 120.0

    def test_no_liquidation_at_1x(self):
        """At 1x leverage, there's no liquidation."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="LONG",
            leverage=1.0, liquidation_price=0.0,
        )
        candle = _make_candle(1, 50, low=10)  # huge drop but 1x
        result = engine._check_liquidation(position, candle)
        assert result is None

    def test_no_liquidation_when_liq_price_zero(self):
        """No liquidation when liquidation_price is 0."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="LONG",
            leverage=5.0, liquidation_price=0.0,
        )
        candle = _make_candle(1, 50, low=10)
        result = engine._check_liquidation(position, candle)
        assert result is None
