"""Tests for BinanceWebSocketFeed — message parsing and queue behavior."""
import json
import pytest
import queue
from unittest.mock import MagicMock, patch
from models import Candle
from live.feeds.binance_ws_feed import BinanceWebSocketFeed


def _kline_msg(symbol="BTCUSDT", interval="1h", is_closed=True,
               t=1672531200000, o="42000", h="42500", l="41800",
               c="42300", v="1234.56"):
    """Build a Binance kline WebSocket message."""
    return json.dumps({
        "e": "kline",
        "E": t + 1000,
        "s": symbol,
        "k": {
            "t": t,
            "T": t + 3600000 - 1,
            "s": symbol,
            "i": interval,
            "o": o, "h": h, "l": l, "c": c,
            "v": v,
            "x": is_closed,
        }
    })


class TestMessageParsing:
    def test_parse_closed_kline(self):
        """Closed kline should produce a Candle."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        msg = _kline_msg(is_closed=True, c="42300")
        feed._on_message(None, msg)
        candle = feed.get_candle(timeout=1.0)
        assert candle is not None
        assert candle.close == 42300.0
        assert candle.high == 42500.0
        assert candle.low == 41800.0
        assert candle.volume == 1234.56

    def test_parse_open_kline_no_candle(self):
        """Non-closed kline should NOT produce a candle."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        msg = _kline_msg(is_closed=False)
        feed._on_message(None, msg)
        candle = feed.get_candle(timeout=0.1)
        assert candle is None

    def test_open_kline_calls_price_callback(self):
        """Non-closed kline should call on_price_update with close price."""
        callback = MagicMock()
        feed = BinanceWebSocketFeed("btcusdt", "1h", on_price_update=callback)
        msg = _kline_msg(is_closed=False, c="42100")
        feed._on_message(None, msg)
        callback.assert_called_once_with(42100.0)

    def test_closed_kline_also_calls_price_callback(self):
        """Closed kline should also update price."""
        callback = MagicMock()
        feed = BinanceWebSocketFeed("btcusdt", "1h", on_price_update=callback)
        msg = _kline_msg(is_closed=True, c="42300")
        feed._on_message(None, msg)
        callback.assert_called_once_with(42300.0)

    def test_invalid_message_ignored(self):
        """Non-kline messages should be silently ignored."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        feed._on_message(None, '{"e": "trade", "p": "42000"}')
        candle = feed.get_candle(timeout=0.1)
        assert candle is None

    def test_malformed_json_ignored(self):
        """Malformed JSON should not crash."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        feed._on_message(None, "not json at all")
        candle = feed.get_candle(timeout=0.1)
        assert candle is None


class TestQueueBehavior:
    def test_multiple_candles_queued_in_order(self):
        """Multiple closed klines should queue in order."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        feed._on_message(None, _kline_msg(c="100", t=1000))
        feed._on_message(None, _kline_msg(c="200", t=2000))
        feed._on_message(None, _kline_msg(c="300", t=3000))
        c1 = feed.get_candle(timeout=0.1)
        c2 = feed.get_candle(timeout=0.1)
        c3 = feed.get_candle(timeout=0.1)
        assert c1.close == 100.0
        assert c2.close == 200.0
        assert c3.close == 300.0

    def test_get_candle_timeout_returns_none(self):
        """Empty queue + timeout should return None."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        result = feed.get_candle(timeout=0.1)
        assert result is None


class TestConnectionState:
    def test_initial_state_not_connected(self):
        """Feed starts not connected."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        assert feed.is_connected() is False

    def test_ws_url_format(self):
        """WebSocket URL should follow Binance format."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        assert "btcusdt@kline_1h" in feed._ws_url

    def test_ws_url_different_interval(self):
        """WebSocket URL should include the interval."""
        feed = BinanceWebSocketFeed("ethusdt", "4h")
        assert "ethusdt@kline_4h" in feed._ws_url
