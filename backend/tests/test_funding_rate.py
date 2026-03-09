"""Tests for funding rate simulation."""
import pytest
from models import Candle, Trade
from services.strategy_engine import StrategyEngine


def _make_candle(i, price):
    return Candle(
        timestamp=i * 3600000,  # 1h intervals
        open=price, high=price + 1, low=price - 1,
        close=price, volume=1000,
    )


class TestFundingApplication:
    def test_funding_interval_1h(self):
        """1h candles: funding every 8 candles."""
        engine = StrategyEngine()
        assert engine._funding_candle_interval("1h") == 8

    def test_funding_interval_4h(self):
        """4h candles: funding every 2 candles."""
        engine = StrategyEngine()
        assert engine._funding_candle_interval("4h") == 2

    def test_funding_interval_1d(self):
        """1d candles: funding every 1 candle (prorated)."""
        engine = StrategyEngine()
        assert engine._funding_candle_interval("1d") == 1

    def test_funding_prorate_factor_1d(self):
        """Daily candles should apply 3x the per-8h rate."""
        engine = StrategyEngine()
        assert engine._funding_prorate_factor("1d") == 3.0

    def test_funding_prorate_factor_4h(self):
        """4h candles: no proration needed."""
        engine = StrategyEngine()
        assert engine._funding_prorate_factor("4h") == 1.0

    def test_apply_funding_deducts_cost(self):
        """Funding deducts from position's funding_paid tracker."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, quantity=10.0,
            side="LONG", leverage=5.0, funding_paid=0.0,
        )
        candle = _make_candle(8, 100)  # price=100
        funding_rate = 0.0001  # 0.01%

        cost = engine._calculate_funding_cost(position, candle, funding_rate, 1.0)
        # cost = quantity * close * rate = 10 * 100 * 0.0001 = 0.1
        assert cost == pytest.approx(0.1, rel=0.01)

    def test_funding_accumulates(self):
        """Multiple funding events accumulate."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, quantity=10.0,
            side="LONG", leverage=5.0, funding_paid=0.5,
        )
        candle = _make_candle(16, 100)
        cost = engine._calculate_funding_cost(position, candle, 0.0001, 1.0)
        new_total = position.funding_paid + cost
        assert new_total == pytest.approx(0.6, rel=0.01)
