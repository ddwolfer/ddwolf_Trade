"""Tests for leverage-related model changes."""
import pytest
from models import BacktestConfig, Trade, TradeSignal


class TestBacktestConfigLeverage:
    def test_default_max_leverage(self):
        config = BacktestConfig()
        assert config.max_leverage == 10.0

    def test_default_leverage_mode(self):
        config = BacktestConfig()
        assert config.leverage_mode == "dynamic"

    def test_default_fixed_leverage(self):
        config = BacktestConfig()
        assert config.fixed_leverage == 1.0

    def test_default_funding_rate(self):
        config = BacktestConfig()
        assert config.funding_rate == 0.0001

    def test_default_maintenance_margin_rate(self):
        config = BacktestConfig()
        assert config.maintenance_margin_rate == 0.005

    def test_custom_leverage_config(self):
        config = BacktestConfig(
            max_leverage=5.0,
            leverage_mode="fixed",
            fixed_leverage=3.0,
            funding_rate=0.0002,
            maintenance_margin_rate=0.01,
        )
        assert config.max_leverage == 5.0
        assert config.leverage_mode == "fixed"
        assert config.fixed_leverage == 3.0
        assert config.funding_rate == 0.0002
        assert config.maintenance_margin_rate == 0.01


class TestTradeLeverage:
    def test_default_leverage_fields(self):
        trade = Trade(entry_time=1000, entry_price=50000.0)
        assert trade.leverage == 1.0
        assert trade.margin_used == 0.0
        assert trade.liquidation_price == 0.0
        assert trade.funding_paid == 0.0

    def test_custom_leverage_fields(self):
        trade = Trade(
            entry_time=1000, entry_price=50000.0,
            leverage=5.0, margin_used=2000.0,
            liquidation_price=40000.0, funding_paid=10.5,
        )
        assert trade.leverage == 5.0
        assert trade.margin_used == 2000.0
        assert trade.liquidation_price == 40000.0
        assert trade.funding_paid == 10.5

    def test_to_dict_includes_leverage(self):
        trade = Trade(entry_time=1000000000000, entry_price=50000.0, leverage=3.0)
        d = trade.to_dict()
        assert d["leverage"] == 3.0
        assert "margin_used" in d
        assert "liquidation_price" in d
        assert "funding_paid" in d


class TestTradeSignalLeverage:
    def test_default_leverage_none(self):
        sig = TradeSignal(timestamp=1000, signal_type="BUY", price=50000.0)
        assert sig.leverage is None

    def test_custom_leverage(self):
        sig = TradeSignal(timestamp=1000, signal_type="BUY", price=50000.0, leverage=5.0)
        assert sig.leverage == 5.0
