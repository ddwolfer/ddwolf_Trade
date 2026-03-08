"""
Tests for the SessionManager.

Uses unittest.mock.patch to mock fetch_klines, keeping tests fast
and deterministic without any network calls. Follows the same
mocking pattern as test_engine.py.
"""
import os
import sys
import time

import pytest
from unittest.mock import patch

# Ensure backend is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import OHLCVData, Candle

# Import strategies so they register with StrategyRegistry
from strategies import rsi_strategy  # noqa: F401
from strategies import ma_cross_strategy  # noqa: F401

from live.session_manager import SessionManager
from live.models import TradingSessionConfig
from live.persistence import TradingPersistence


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_test_ohlcv(n_candles: int = 50, base_price: float = 50000.0,
                    symbol: str = "BTCUSDT") -> OHLCVData:
    """Create deterministic test OHLCV data.

    First half: price goes up +0.5% per candle.
    Second half: price goes down -0.5% per candle.
    """
    candles = []
    price = base_price
    start_ts = int(time.time() * 1000) - n_candles * 3600 * 1000

    for i in range(n_candles):
        if i < n_candles // 2:
            price *= 1.005
        else:
            price *= 0.995

        candles.append(Candle(
            timestamp=start_ts + i * 3600 * 1000,
            open=price * 0.999,
            high=price * 1.002,
            low=price * 0.998,
            close=price,
            volume=100.0 + i * 10,
        ))
    return OHLCVData(symbol=symbol, interval="1h", candles=candles)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def manager(tmp_path):
    """Create an isolated SessionManager backed by a temp DB."""
    return SessionManager(db_path=str(tmp_path / "test_sessions.db"))


@pytest.fixture
def test_ohlcv():
    """Standard 50-candle test dataset."""
    return make_test_ohlcv(50)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_deploy_creates_and_starts_session(manager, test_ohlcv):
    """deploy() should create a session and set state to running."""
    config = TradingSessionConfig(strategy_name="RSI", tick_interval_seconds=0)
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        status = manager.deploy(config)
    assert status["session_id"] == config.session_id
    assert status["state"] == "running"
    # Wait for the simulated run to complete
    time.sleep(1)


def test_deploy_duplicate_session_raises_error(manager, test_ohlcv):
    """deploy() with the same session_id should raise ValueError."""
    config = TradingSessionConfig(strategy_name="RSI", tick_interval_seconds=0)
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
    with pytest.raises(ValueError, match="already exists"):
        with patch("live.engine.fetch_klines", return_value=test_ohlcv):
            manager.deploy(config)


def test_stop_session(manager, test_ohlcv):
    """stop_session() should transition state to stopped."""
    config = TradingSessionConfig(
        strategy_name="RSI", tick_interval_seconds=0.05
    )
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
        time.sleep(0.2)
        status = manager.stop_session(config.session_id)
    assert status["state"] == "stopped"


def test_list_sessions(manager, test_ohlcv):
    """list_sessions() should include deployed sessions."""
    config = TradingSessionConfig(strategy_name="RSI", tick_interval_seconds=0)
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
        time.sleep(1)
    sessions = manager.list_sessions()
    assert len(sessions) >= 1
    assert any(s["session_id"] == config.session_id for s in sessions)


def test_get_status(manager, test_ohlcv):
    """get_status() should return account and candle info."""
    config = TradingSessionConfig(strategy_name="RSI", tick_interval_seconds=0)
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
        time.sleep(1)
    status = manager.get_status(config.session_id)
    assert "account" in status
    assert "candles_processed" in status


def test_get_orders_for_session(manager, test_ohlcv):
    """get_orders() should return a list of order dicts."""
    config = TradingSessionConfig(
        strategy_name="RSI",
        tick_interval_seconds=0,
        strategy_params={"period": 5, "oversold": 40, "overbought": 60},
    )
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
        time.sleep(1)
    orders = manager.get_orders(config.session_id)
    assert isinstance(orders, list)


def test_get_equity_curve(manager, test_ohlcv):
    """get_equity_curve() should return arrays of matching length."""
    config = TradingSessionConfig(strategy_name="RSI", tick_interval_seconds=0)
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
        time.sleep(1)
    curve = manager.get_equity_curve(config.session_id)
    assert "equity_curve" in curve
    assert "timestamps" in curve
    assert len(curve["equity_curve"]) == 50


def test_interrupted_sessions_on_init(tmp_path, test_ohlcv):
    """Simulate server restart: sessions in 'running' state should become 'interrupted'."""
    db_path = str(tmp_path / "restart_test.db")

    # Create a session marked as "running" directly in DB
    persistence = TradingPersistence(db_path=db_path)
    config = TradingSessionConfig(strategy_name="RSI")
    persistence.save_session(config, state="running")

    # Create a new SessionManager (simulates server restart)
    manager = SessionManager(db_path=db_path)

    # The session should now be "interrupted"
    sessions = manager.list_sessions()
    found = [s for s in sessions if s["session_id"] == config.session_id]
    assert len(found) == 1
    assert found[0]["state"] == "interrupted"


def test_stop_nonexistent_session_raises_error(manager):
    """stop_session() with unknown ID should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        manager.stop_session("nonexistent-id")


def test_get_status_nonexistent_session_raises_error(manager):
    """get_status() with unknown ID should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        manager.get_status("nonexistent-id")


def test_get_positions_for_session(manager, test_ohlcv):
    """get_positions() should return a list of position dicts."""
    config = TradingSessionConfig(
        strategy_name="RSI",
        tick_interval_seconds=0,
        strategy_params={"period": 5, "oversold": 40, "overbought": 60},
    )
    with patch("live.engine.fetch_klines", return_value=test_ohlcv):
        manager.deploy(config)
        time.sleep(1)
    positions = manager.get_positions(config.session_id)
    assert isinstance(positions, list)
