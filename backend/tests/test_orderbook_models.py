"""Tests for OrderBook and MarketContext data models."""
import pytest
from models import OrderBookLevel, OrderBook, MarketContext


class TestOrderBookLevel:
    def test_create_level(self):
        level = OrderBookLevel(price=42000.0, quantity=1.5)
        assert level.price == 42000.0
        assert level.quantity == 1.5


class TestOrderBook:
    @pytest.fixture
    def sample_ob(self):
        return OrderBook(
            symbol="BTCUSDT",
            timestamp=1700000000000,
            bids=[
                OrderBookLevel(42000.0, 10.0),
                OrderBookLevel(41900.0, 20.0),
                OrderBookLevel(41800.0, 5.0),
            ],
            asks=[
                OrderBookLevel(42100.0, 15.0),
                OrderBookLevel(42200.0, 8.0),
                OrderBookLevel(42300.0, 12.0),
            ],
        )

    def test_best_bid(self, sample_ob):
        assert sample_ob.best_bid == 42000.0

    def test_best_ask(self, sample_ob):
        assert sample_ob.best_ask == 42100.0

    def test_mid_price(self, sample_ob):
        assert sample_ob.mid_price == 42050.0

    def test_spread_pct(self, sample_ob):
        expected = (42100.0 - 42000.0) / 42050.0 * 100
        assert abs(sample_ob.spread_pct - expected) < 0.001

    def test_to_dict(self, sample_ob):
        d = sample_ob.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert len(d["bids"]) == 3
        assert d["bids"][0]["price"] == 42000.0

    def test_empty_bids(self):
        ob = OrderBook("BTCUSDT", 0, [], [OrderBookLevel(100, 1)])
        assert ob.best_bid == 0.0
        assert ob.mid_price == 100.0

    def test_empty_asks(self):
        ob = OrderBook("BTCUSDT", 0, [OrderBookLevel(100, 1)], [])
        assert ob.best_ask == 0.0


class TestMarketContext:
    def test_empty_context(self):
        ctx = MarketContext()
        assert ctx.orderbook is None
        assert ctx.recent_trades is None

    def test_with_orderbook(self):
        ob = OrderBook("BTCUSDT", 0, [], [])
        ctx = MarketContext(orderbook=ob)
        assert ctx.orderbook.symbol == "BTCUSDT"
