"""Tests for Order Book indicator calculations."""
import pytest
from models import OrderBook, OrderBookLevel
from services.orderbook_indicators import (
    bid_ask_imbalance, depth_ratio, wall_detection,
    spread_bps, weighted_mid_price, cumulative_delta,
)


@pytest.fixture
def balanced_ob():
    return OrderBook("BTCUSDT", 0,
        bids=[OrderBookLevel(100, 10), OrderBookLevel(99, 10), OrderBookLevel(98, 10)],
        asks=[OrderBookLevel(101, 10), OrderBookLevel(102, 10), OrderBookLevel(103, 10)],
    )


@pytest.fixture
def buy_heavy_ob():
    return OrderBook("BTCUSDT", 0,
        bids=[OrderBookLevel(100, 50), OrderBookLevel(99, 30), OrderBookLevel(98, 20)],
        asks=[OrderBookLevel(101, 5), OrderBookLevel(102, 5), OrderBookLevel(103, 5)],
    )


@pytest.fixture
def sell_heavy_ob():
    return OrderBook("BTCUSDT", 0,
        bids=[OrderBookLevel(100, 5), OrderBookLevel(99, 5)],
        asks=[OrderBookLevel(101, 50), OrderBookLevel(102, 30)],
    )


class TestBidAskImbalance:
    def test_balanced(self, balanced_ob):
        result = bid_ask_imbalance(balanced_ob, levels=3)
        assert abs(result) < 0.01  # ~0

    def test_buy_heavy(self, buy_heavy_ob):
        result = bid_ask_imbalance(buy_heavy_ob, levels=3)
        assert result > 0.5  # Strong buy pressure

    def test_sell_heavy(self, sell_heavy_ob):
        result = bid_ask_imbalance(sell_heavy_ob, levels=2)
        assert result < -0.5  # Strong sell pressure

    def test_empty_ob(self):
        ob = OrderBook("X", 0, [], [])
        assert bid_ask_imbalance(ob) == 0.0


class TestDepthRatio:
    def test_balanced(self, balanced_ob):
        assert abs(depth_ratio(balanced_ob, levels=3) - 1.0) < 0.01

    def test_buy_heavy(self, buy_heavy_ob):
        assert depth_ratio(buy_heavy_ob, levels=3) > 5.0


class TestWallDetection:
    def test_detects_buy_wall(self, buy_heavy_ob):
        walls = wall_detection(buy_heavy_ob, mult=3.0)
        assert len(walls["bid_walls"]) > 0
        assert walls["bid_walls"][0]["price"] == 100

    def test_no_walls_balanced(self, balanced_ob):
        walls = wall_detection(balanced_ob, mult=3.0)
        assert len(walls["bid_walls"]) == 0
        assert len(walls["ask_walls"]) == 0


class TestSpreadBps:
    def test_spread(self, balanced_ob):
        result = spread_bps(balanced_ob)
        expected = (101 - 100) / 100.5 * 10000
        assert abs(result - expected) < 1


class TestWeightedMidPrice:
    def test_balanced(self, balanced_ob):
        result = weighted_mid_price(balanced_ob)
        assert 100 < result < 101

    def test_buy_heavy_pulls_up(self, buy_heavy_ob):
        # More bid volume -> mid shifts toward ask
        result = weighted_mid_price(buy_heavy_ob)
        assert result > 100.5


class TestCumulativeDelta:
    def test_buy_heavy(self, buy_heavy_ob):
        result = cumulative_delta(buy_heavy_ob, price_range_pct=5.0)
        assert result > 0  # More bids than asks

    def test_sell_heavy(self, sell_heavy_ob):
        result = cumulative_delta(sell_heavy_ob, price_range_pct=5.0)
        assert result < 0
