"""Tests for Binance Depth WebSocket Feed."""
import json
import pytest
from models import OrderBook, OrderBookLevel
from live.feeds.binance_depth_feed import BinanceDepthFeed


def _depth_msg(bids=None, asks=None, symbol="BTCUSDT", timestamp=1700000000000):
    """Helper to create a Binance depthUpdate WebSocket message."""
    if bids is None:
        bids = [["42000.00", "10.500"], ["41900.00", "20.000"]]
    if asks is None:
        asks = [["42100.00", "15.300"], ["42200.00", "25.000"]]
    return json.dumps({
        "e": "depthUpdate",
        "E": timestamp,
        "s": symbol,
        "U": 1000,
        "u": 1001,
        "b": bids,
        "a": asks,
    })


class TestDepthMessageParsing:
    """Tests for parsing Binance depth WebSocket messages."""

    def test_parse_valid_depth(self):
        """Parse a standard depthUpdate message with bids and asks."""
        feed = BinanceDepthFeed("BTCUSDT")
        msg = _depth_msg()
        ob = feed._parse_depth_message(json.loads(msg))
        assert ob is not None
        assert ob.symbol == "BTCUSDT"
        assert len(ob.bids) == 2
        assert ob.bids[0].price == 42000.0
        assert ob.bids[0].quantity == 10.5
        assert len(ob.asks) == 2
        assert ob.asks[0].price == 42100.0

    def test_parse_empty_depth(self):
        """Parse a depth message with empty bid/ask lists."""
        feed = BinanceDepthFeed("BTCUSDT")
        msg = json.loads(_depth_msg(bids=[], asks=[]))
        ob = feed._parse_depth_message(msg)
        assert ob is not None
        assert len(ob.bids) == 0

    def test_parse_invalid_message(self):
        """Non-depth messages (e.g. trade events) should return None."""
        feed = BinanceDepthFeed("BTCUSDT")
        ob = feed._parse_depth_message({"e": "trade"})
        assert ob is None

    def test_get_orderbook_returns_latest(self):
        """get_orderbook() returns the most recent parsed OrderBook."""
        feed = BinanceDepthFeed("BTCUSDT")
        msg = json.loads(_depth_msg())
        feed._latest_ob = feed._parse_depth_message(msg)
        ob = feed.get_orderbook()
        assert ob is not None
        assert ob.best_bid == 42000.0

    def test_get_orderbook_none_before_data(self):
        """get_orderbook() returns None when no data has been received."""
        feed = BinanceDepthFeed("BTCUSDT")
        assert feed.get_orderbook() is None


class TestDepthFeedConstruction:
    """Tests for BinanceDepthFeed initialization and configuration."""

    def test_default_construction(self):
        """Feed initializes with correct defaults."""
        feed = BinanceDepthFeed("BTCUSDT")
        assert feed._symbol == "btcusdt"
        assert feed._levels == 20
        assert feed._latest_ob is None
        assert feed._connected is False

    def test_custom_levels(self):
        """Feed accepts custom depth levels."""
        feed = BinanceDepthFeed("ETHUSDT", levels=10)
        assert feed._levels == 10
        assert "depth10" in feed._ws_url

    def test_ws_url_format(self):
        """WebSocket URL is correctly formatted."""
        feed = BinanceDepthFeed("BTCUSDT", levels=20)
        assert feed._ws_url == "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms"


class TestDepthCallback:
    """Tests for the on_depth_update callback mechanism."""

    def test_on_message_triggers_callback(self):
        """_on_message parses data and invokes the on_depth_update callback."""
        received = []

        def cb(ob: OrderBook):
            received.append(ob)

        feed = BinanceDepthFeed("BTCUSDT", on_depth_update=cb)
        feed._on_message(None, _depth_msg())
        assert len(received) == 1
        assert received[0].symbol == "BTCUSDT"
        assert received[0].best_bid == 42000.0

    def test_on_message_invalid_json_ignored(self):
        """Invalid JSON messages are silently ignored."""
        feed = BinanceDepthFeed("BTCUSDT")
        # Should not raise
        feed._on_message(None, "not valid json {{{")
        assert feed.get_orderbook() is None

    def test_callback_error_does_not_crash(self):
        """Exceptions in the callback are caught and logged, not propagated."""
        def bad_cb(ob):
            raise RuntimeError("callback boom")

        feed = BinanceDepthFeed("BTCUSDT", on_depth_update=bad_cb)
        # Should not raise
        feed._on_message(None, _depth_msg())
        # OrderBook should still be updated despite callback error
        assert feed.get_orderbook() is not None


class TestDepthFeedThreadSafety:
    """Tests for thread-safe access to the order book."""

    def test_concurrent_updates_and_reads(self):
        """Multiple updates followed by a read returns the latest data."""
        feed = BinanceDepthFeed("BTCUSDT")
        # Simulate two sequential updates with different prices
        msg1 = _depth_msg(bids=[["40000.00", "5.0"]], asks=[["40100.00", "5.0"]],
                          timestamp=1700000000000)
        msg2 = _depth_msg(bids=[["41000.00", "8.0"]], asks=[["41100.00", "8.0"]],
                          timestamp=1700000001000)
        feed._on_message(None, msg1)
        feed._on_message(None, msg2)
        ob = feed.get_orderbook()
        assert ob is not None
        assert ob.best_bid == 41000.0
        assert ob.timestamp == 1700000001000


class TestPartialDepthStream:
    """Tests for parsing Binance partial book depth stream format."""

    def test_parse_partial_depth_snapshot(self):
        """Parse partial depth stream message (has 'lastUpdateId' instead of 'e')."""
        feed = BinanceDepthFeed("BTCUSDT")
        # Partial depth stream format differs from depthUpdate
        partial_msg = {
            "lastUpdateId": 12345,
            "bids": [["42000.00", "10.0"], ["41900.00", "20.0"]],
            "asks": [["42100.00", "15.0"], ["42200.00", "25.0"]],
        }
        ob = feed._parse_depth_message(partial_msg)
        assert ob is not None
        assert len(ob.bids) == 2
        assert ob.bids[0].price == 42000.0
        assert len(ob.asks) == 2
        assert ob.asks[0].price == 42100.0
