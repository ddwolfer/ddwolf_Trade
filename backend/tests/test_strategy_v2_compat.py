"""Tests for BaseStrategy v2 interface backward compatibility."""
import pytest
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal, MarketContext, Candle
from strategies.base_strategy import BaseStrategy


class OldStrategy(BaseStrategy):
    """v1 strategy -- only implements generate_signal."""
    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {"name": "Old", "description": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index) -> Optional[TradeSignal]:
        return TradeSignal(timestamp=0, signal_type="BUY", price=100, reason="test")


class NewStrategy(BaseStrategy):
    """v2 strategy -- overrides generate_signal_v2 to use MarketContext."""
    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {"name": "New", "description": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index) -> Optional[TradeSignal]:
        return None  # v1 returns nothing

    def generate_signal_v2(self, ohlcv, index, context: MarketContext) -> Optional[TradeSignal]:
        if context.orderbook is not None:
            return TradeSignal(timestamp=0, signal_type="BUY", price=100, reason="OB signal")
        return None


class TestV2Compatibility:
    def test_old_strategy_v2_delegates(self):
        """Old strategies' generate_signal_v2 should delegate to generate_signal."""
        s = OldStrategy({})
        ctx = MarketContext()
        signal = s.generate_signal_v2(None, 0, ctx)
        assert signal is not None
        assert signal.signal_type == "BUY"

    def test_old_strategy_uses_market_context_false(self):
        s = OldStrategy({})
        assert s.uses_market_context is False

    def test_new_strategy_uses_market_context_true(self):
        s = NewStrategy({})
        assert s.uses_market_context is True

    def test_new_strategy_with_ob(self):
        from models import OrderBook
        s = NewStrategy({})
        ob = OrderBook("BTC", 0, [], [])
        ctx = MarketContext(orderbook=ob)
        signal = s.generate_signal_v2(None, 0, ctx)
        assert signal is not None
        assert signal.reason == "OB signal"

    def test_new_strategy_without_ob(self):
        s = NewStrategy({})
        ctx = MarketContext()
        signal = s.generate_signal_v2(None, 0, ctx)
        assert signal is None
