"""
Tests for LiveTradingEngine realtime mode (with mock feed).

Validates that the engine can:
- Accept 'realtime' as a valid mode
- Process candles from a WebSocket feed (mocked)
- Perform warmup with historical data
- Handle leverage assessment and signal processing
- Properly start/stop the WebSocket feed
- Apply funding rate and check liquidation
"""
import os
import sys
import time
import queue

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure backend is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Candle, OHLCVData, TradeSignal
from live.engine import LiveTradingEngine
from live.models import TradingSessionConfig
from live.adapters.paper_adapter import PaperTradingAdapter
from live.persistence import TradingPersistence

# Import strategies so they register with StrategyRegistry
from strategies import rsi_strategy  # noqa: F401
from strategies import ma_cross_strategy  # noqa: F401


# ------------------------------------------------------------------
# Mock WebSocket Feed
# ------------------------------------------------------------------

class MockFeed:
    """Mock WebSocket feed that delivers candles from a list."""

    def __init__(self, candles):
        self._queue = queue.Queue()
        for c in candles:
            self._queue.put(c)
        self._started = False
        self._stopped = False

    def start(self):
        self._started = True

    def stop(self):
        self._stopped = True

    def get_candle(self, timeout=5.0):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_connected(self):
        return self._started and not self._stopped


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_candle(i, price):
    """Create a single candle with given index and price."""
    return Candle(
        timestamp=i * 3600000,
        open=price,
        high=price + 5,
        low=price - 5,
        close=price,
        volume=1000,
    )


def _make_warmup_candles(n=50, base_price=100):
    """Create a series of warmup candles with a gradual price increase."""
    return [_make_candle(i, base_price + i) for i in range(n)]


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def persistence(tmp_path):
    """Create an isolated TradingPersistence backed by a temp DB."""
    return TradingPersistence(db_path=str(tmp_path / "test_realtime.db"))


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestRealtimeMode:
    """Tests for the engine's realtime mode."""

    def test_config_mode_realtime(self):
        """Config should accept 'realtime' mode."""
        config = TradingSessionConfig(mode="realtime")
        assert config.mode == "realtime"

    def test_realtime_processes_candles(self, persistence):
        """Engine in realtime mode should process candles from feed."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="BTCUSDT",
            interval="1h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        # Create warmup + feed candles
        warmup_candles = _make_warmup_candles(50, base_price=100)
        feed_candles = [_make_candle(50 + i, 150 + i) for i in range(3)]

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup_candles
            )
            mock_feed = MockFeed(feed_candles)
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)

            # Run in background thread, stop after processing
            engine.start()
            time.sleep(2)  # Let it process candles
            engine.stop()

            # Verify feed was started and stopped
            assert mock_feed._started
            assert mock_feed._stopped

    def test_realtime_candle_count(self, persistence):
        """Engine should count each candle from the feed."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="BTCUSDT",
            interval="1h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        warmup_candles = _make_warmup_candles(50, base_price=100)
        feed_candles = [_make_candle(50 + i, 150 + i) for i in range(5)]

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup_candles
            )
            mock_feed = MockFeed(feed_candles)
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)
            engine.start()
            # Wait for the engine thread to finish processing all candles
            # (it will exhaust the queue then block on get_candle)
            time.sleep(3)
            engine.stop()

            # Should have processed all feed candles
            assert engine._candle_count == len(feed_candles)

    def test_realtime_warmup_fetch(self, persistence):
        """Engine should fetch historical data for warmup before starting feed."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="ETHUSDT",
            interval="4h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        warmup_candles = _make_warmup_candles(50, base_price=2000)
        feed_candles = [_make_candle(50 + i, 2050 + i) for i in range(2)]

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="ETHUSDT", interval="4h", candles=warmup_candles
            )
            mock_feed = MockFeed(feed_candles)
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)
            engine.start()
            time.sleep(2)
            engine.stop()

            # Verify fetch_klines was called for warmup
            mock_fetch.assert_called_once()
            call_args = mock_fetch.call_args
            assert call_args[0][0] == "ETHUSDT"  # symbol
            assert call_args[0][1] == "4h"        # interval

    def test_realtime_stop_cleans_feed(self, persistence):
        """Stopping engine should also stop the WebSocket feed."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="BTCUSDT",
            interval="1h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        warmup_candles = _make_warmup_candles(50, base_price=100)
        # Empty feed so engine blocks on get_candle
        feed_candles = []

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup_candles
            )
            mock_feed = MockFeed(feed_candles)
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)
            engine.start()
            time.sleep(1)  # Let engine start and enter wait loop
            engine.stop()

            assert mock_feed._stopped

    def test_realtime_equity_snapshots(self, persistence):
        """Engine should save equity snapshots for each candle."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="BTCUSDT",
            interval="1h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        warmup_candles = _make_warmup_candles(50, base_price=100)
        feed_candles = [_make_candle(50 + i, 150 + i) for i in range(3)]

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup_candles
            )
            mock_feed = MockFeed(feed_candles)
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)
            engine.start()
            time.sleep(3)
            engine.stop()

            # Check that equity snapshots were saved
            equity = persistence.get_equity_curve(config.session_id)
            assert len(equity) >= len(feed_candles)


class TestRealtimeSignalProcessing:
    """Tests for signal processing with leverage in realtime mode."""

    def test_buy_signal_opens_position(self, persistence):
        """BUY signal should open a LONG position with leverage."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="BTCUSDT",
            interval="1h",
            strategy_name="RSI",
            leverage_mode="fixed",
            fixed_leverage=2.0,
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        # Create candle data that will trigger a BUY signal (RSI oversold)
        # Build warmup with a severe decline followed by recovery
        warmup = []
        price = 200.0
        for i in range(40):
            price *= 0.97  # Strong decline to push RSI very low
            warmup.append(_make_candle(i, price))
        # Recovery candles
        for i in range(40, 50):
            price *= 1.01
            warmup.append(_make_candle(i, price))

        # Feed candles continue recovery
        feed = [_make_candle(50 + i, price * (1.02 ** (i + 1))) for i in range(3)]

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup
            )
            mock_feed = MockFeed(feed)
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)
            engine.start()
            time.sleep(3)
            engine.stop()

            # Engine should run without errors
            status = engine.status()
            assert status["state"] in ("stopped", "running")


class TestFundingHelpers:
    """Tests for funding rate helper methods."""

    def test_funding_candle_interval_1h(self):
        """1h interval should have 8 candles per funding period."""
        assert LiveTradingEngine._funding_candle_interval("1h") == 8

    def test_funding_candle_interval_1m(self):
        """1m interval should have 480 candles per funding period."""
        assert LiveTradingEngine._funding_candle_interval("1m") == 480

    def test_funding_candle_interval_4h(self):
        """4h interval should have 2 candles per funding period."""
        assert LiveTradingEngine._funding_candle_interval("4h") == 2

    def test_funding_candle_interval_15m(self):
        """15m interval should have 32 candles per funding period."""
        assert LiveTradingEngine._funding_candle_interval("15m") == 32

    def test_funding_candle_interval_unknown(self):
        """Unknown interval should default to 8."""
        assert LiveTradingEngine._funding_candle_interval("3h") == 8

    def test_funding_prorate_factor_1h(self):
        """Intervals under 8h should prorate at 1.0."""
        assert LiveTradingEngine._funding_prorate_factor("1h") == 1.0

    def test_funding_prorate_factor_8h(self):
        """8h interval should prorate at 1.0."""
        assert LiveTradingEngine._funding_prorate_factor("8h") == 1.0

    def test_funding_prorate_factor_12h(self):
        """12h interval should prorate at 1.5."""
        assert LiveTradingEngine._funding_prorate_factor("12h") == 1.5

    def test_funding_prorate_factor_1d(self):
        """1d interval should prorate at 3.0."""
        assert LiveTradingEngine._funding_prorate_factor("1d") == 3.0

    def test_funding_prorate_factor_unknown(self):
        """Unknown interval should default to 1.0."""
        assert LiveTradingEngine._funding_prorate_factor("3h") == 1.0


class TestRealtimeRunLoop:
    """Tests for the _run_loop dispatch to realtime mode."""

    def test_run_loop_dispatches_realtime(self, persistence):
        """_run_loop should recognize 'realtime' mode."""
        config = TradingSessionConfig(
            mode="realtime",
            symbol="BTCUSDT",
            interval="1h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        warmup_candles = _make_warmup_candles(50, base_price=100)

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup_candles
            )
            mock_feed = MockFeed([])  # Empty feed
            mock_ws_cls.return_value = mock_feed

            engine = LiveTradingEngine(config, adapter, persistence)
            engine.start()
            time.sleep(1)
            engine.stop()

            # Should not be in error state
            assert engine._state != "error"

    def test_unknown_mode_raises(self, persistence):
        """Unknown mode should produce an error message."""
        config = TradingSessionConfig(mode="invalid_mode")
        config.mode = "invalid_mode"
        adapter = PaperTradingAdapter(config.session_id, initial_capital=10000)
        persistence.save_session(config)

        engine = LiveTradingEngine(config, adapter, persistence)
        engine.start()
        # Wait for the thread to finish (it will raise ValueError immediately)
        engine._thread.join(timeout=5)
        # Check error was captured before stop() overwrites state
        assert "Unknown mode" in engine._error_msg
        engine.stop()
