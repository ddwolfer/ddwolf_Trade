"""Tests for PaperTradingAdapter leverage support."""
import pytest
import time
from models import Candle
from live.adapters.paper_adapter import PaperTradingAdapter


def _adapter(capital=10000, commission=0, slippage=0):
    return PaperTradingAdapter("test", initial_capital=capital,
                                commission_rate=commission, slippage_rate=slippage)


class TestLeveragedOrder:
    def test_buy_with_leverage_increases_quantity(self):
        """3x leverage should give 3x the quantity of 1x."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        order = a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                              "test", leverage=3.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        assert pos is not None
        assert pos.leverage == 3.0
        # quantity = (1000 * 3) / 100 = 30
        assert pos.quantity == pytest.approx(30.0, rel=0.01)
        assert pos.margin_used == pytest.approx(1000.0, rel=0.01)
        assert pos.liquidation_price > 0

    def test_short_with_leverage(self):
        """SHORT with leverage should set leverage fields."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        order = a.place_order("BTC", "SHORT_OPEN", "MARKET", 0, 100.0,
                              "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        assert pos.leverage == 5.0
        assert pos.side == "SHORT"
        assert pos.liquidation_price > 100.0  # SHORT liq is above entry

    def test_1x_leverage_no_liquidation_price(self):
        """1x leverage should have liquidation_price = 0."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0, "test", leverage=1.0)
        pos = a.get_position("BTC")
        assert pos.liquidation_price == 0.0


class TestLiquidationCheck:
    def test_long_liquidation_triggered(self):
        """LONG position should be liquidated when price drops to liq level."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        liq_price = pos.liquidation_price

        candle = Candle(timestamp=1000, open=85, high=90,
                        low=liq_price - 1, close=82, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is True
        assert a.get_position("BTC") is None  # Position closed
        assert a._cash == 0.0  # Lost all margin

    def test_short_liquidation_triggered(self):
        """SHORT position should be liquidated when price rises to liq level."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "SHORT_OPEN", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        liq_price = pos.liquidation_price

        candle = Candle(timestamp=1000, open=115, high=liq_price + 1,
                        low=110, close=118, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is True
        assert a.get_position("BTC") is None

    def test_no_liquidation_when_safe(self):
        """No liquidation when price is far from liq level."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)

        candle = Candle(timestamp=1000, open=98, high=102, low=95, close=99, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is False
        assert a.get_position("BTC") is not None

    def test_no_liquidation_at_1x(self):
        """1x leverage should never trigger liquidation."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0, "test", leverage=1.0)

        candle = Candle(timestamp=1000, open=50, high=55, low=10, close=20, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is False


class TestFundingRate:
    def test_apply_funding_deducts_from_cash(self):
        """Funding rate should deduct cost from cash."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        # qty = 50, price = 100, rate = 0.0001 -> cost = 50 * 100 * 0.0001 = 0.5
        cost = a.apply_funding("BTC", 100.0, 0.0001)
        assert cost == pytest.approx(0.5, rel=0.01)
        pos_after = a.get_position("BTC")
        assert pos_after.funding_paid == pytest.approx(0.5, rel=0.01)
