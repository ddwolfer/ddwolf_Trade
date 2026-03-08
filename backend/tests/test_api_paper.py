"""API integration tests for paper trading endpoints.

Starts a test HTTP server in a background thread and exercises all 8
paper-trading routes through real HTTP requests. Uses unittest.mock.patch
to avoid network calls to Binance.
"""
import json
import os
import sys
import time
import threading
import http.client
import tempfile

import pytest
from unittest.mock import patch
from http.server import HTTPServer

# Ensure backend is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import OHLCVData, Candle

# Import strategies to trigger registration
from strategies import rsi_strategy  # noqa: F401


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_test_ohlcv(n_candles: int = 30, base_price: float = 50000.0) -> OHLCVData:
    """Create deterministic test OHLCV data with an up-then-down price pattern."""
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
            volume=100.0,
        ))
    return OHLCVData(symbol="BTCUSDT", interval="1h", candles=candles)


def api_get(port: int, path: str):
    """Send a GET request and return (status_code, parsed_json_body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())
    status = resp.status
    conn.close()
    return status, body


def api_post(port: int, path: str, data=None):
    """Send a POST request and return (status_code, parsed_json_body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = json.dumps(data or {})
    conn.request("POST", path, body=payload,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())
    status = resp.status
    conn.close()
    return status, body


# ------------------------------------------------------------------
# Module-scoped test server fixture
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_server():
    """Start a test HTTP server on a random port with an isolated DB.

    The server is module-scoped so that sessions created in earlier tests
    are visible to later tests.
    """
    # Use a temp DB so tests don't pollute the real paper_trading.db
    tmp_db = os.path.join(tempfile.gettempdir(), f"test_paper_{os.getpid()}.db")

    import app

    # Replace the module-level SessionManager with one backed by the temp DB
    from live.session_manager import SessionManager
    original_manager = app._session_manager
    app._session_manager = SessionManager(db_path=tmp_db)

    server = HTTPServer(("127.0.0.1", 0), app.BacktestHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield port

    server.shutdown()
    app._session_manager = original_manager

    # Clean up temp DB
    try:
        os.remove(tmp_db)
    except OSError:
        pass


# ------------------------------------------------------------------
# Tests — GET /api/paper (list)
# ------------------------------------------------------------------

def test_list_paper_sessions_empty(test_server):
    """GET /api/paper should return an empty sessions list initially."""
    status, body = api_get(test_server, "/api/paper")
    assert status == 200
    assert "sessions" in body
    assert isinstance(body["sessions"], list)


# ------------------------------------------------------------------
# Tests — POST /api/paper/deploy
# ------------------------------------------------------------------

def test_deploy_paper_session(test_server):
    """POST /api/paper/deploy should start a session and return running state."""
    ohlcv = make_test_ohlcv(30)
    with patch("live.engine.fetch_klines", return_value=ohlcv):
        status, body = api_post(test_server, "/api/paper/deploy", {
            "symbol": "BTCUSDT",
            "strategy_name": "RSI",
            "mode": "simulated",
            "tick_interval_seconds": 0,
        })
    assert status == 200
    assert "session_id" in body
    assert body["state"] == "running"
    # Wait for the simulated engine run to complete
    time.sleep(2)


def test_deploy_invalid_strategy(test_server):
    """POST /api/paper/deploy with invalid strategy should return 400."""
    status, body = api_post(test_server, "/api/paper/deploy", {
        "strategy_name": "NONEXISTENT_STRATEGY_XYZ",
        "tick_interval_seconds": 0,
    })
    assert status == 400
    assert "error" in body


# ------------------------------------------------------------------
# Tests — GET /api/paper (list after deploy)
# ------------------------------------------------------------------

def test_list_paper_sessions_after_deploy(test_server):
    """GET /api/paper should include previously deployed sessions."""
    status, body = api_get(test_server, "/api/paper")
    assert status == 200
    assert len(body["sessions"]) >= 1


# ------------------------------------------------------------------
# Tests — GET /api/paper/{id} (session status)
# ------------------------------------------------------------------

def test_get_nonexistent_session(test_server):
    """GET /api/paper/nonexistent-id should return 404."""
    status, body = api_get(test_server, "/api/paper/nonexistent-id")
    assert status == 404
    assert "error" in body


def test_get_session_status(test_server):
    """GET /api/paper/{id} should return session details for a known session."""
    # First list to find a valid session id
    _, list_body = api_get(test_server, "/api/paper")
    assert len(list_body["sessions"]) >= 1
    session_id = list_body["sessions"][0]["session_id"]

    status, body = api_get(test_server, f"/api/paper/{session_id}")
    assert status == 200
    assert body["session_id"] == session_id
    assert "state" in body


# ------------------------------------------------------------------
# Tests — GET /api/paper/{id}/orders
# ------------------------------------------------------------------

def test_get_session_orders(test_server):
    """GET /api/paper/{id}/orders should return a list of orders."""
    _, list_body = api_get(test_server, "/api/paper")
    session_id = list_body["sessions"][0]["session_id"]

    status, body = api_get(test_server, f"/api/paper/{session_id}/orders")
    assert status == 200
    assert "orders" in body
    assert isinstance(body["orders"], list)


# ------------------------------------------------------------------
# Tests — GET /api/paper/{id}/positions
# ------------------------------------------------------------------

def test_get_session_positions(test_server):
    """GET /api/paper/{id}/positions should return a list of positions."""
    _, list_body = api_get(test_server, "/api/paper")
    session_id = list_body["sessions"][0]["session_id"]

    status, body = api_get(test_server, f"/api/paper/{session_id}/positions")
    assert status == 200
    assert "positions" in body
    assert isinstance(body["positions"], list)


# ------------------------------------------------------------------
# Tests — GET /api/paper/{id}/equity
# ------------------------------------------------------------------

def test_get_session_equity(test_server):
    """GET /api/paper/{id}/equity should return equity curve data."""
    _, list_body = api_get(test_server, "/api/paper")
    session_id = list_body["sessions"][0]["session_id"]

    status, body = api_get(test_server, f"/api/paper/{session_id}/equity")
    assert status == 200
    assert "equity_curve" in body
    assert "timestamps" in body
    assert "cash_curve" in body
    assert body["session_id"] == session_id


# ------------------------------------------------------------------
# Tests — POST /api/paper/{id}/stop
# ------------------------------------------------------------------

def test_stop_session(test_server):
    """POST /api/paper/{id}/stop should stop a running session."""
    # Deploy a new session to stop
    ohlcv = make_test_ohlcv(30)
    with patch("live.engine.fetch_klines", return_value=ohlcv):
        _, deploy_body = api_post(test_server, "/api/paper/deploy", {
            "symbol": "BTCUSDT",
            "strategy_name": "RSI",
            "mode": "simulated",
            "tick_interval_seconds": 0.05,
        })
    session_id = deploy_body["session_id"]
    time.sleep(0.3)

    status, body = api_post(test_server, f"/api/paper/{session_id}/stop")
    assert status == 200
    assert body["state"] == "stopped"


def test_stop_nonexistent_session(test_server):
    """POST /api/paper/nonexistent-id/stop should return 404."""
    status, body = api_post(test_server, "/api/paper/nonexistent-id/stop")
    assert status == 404
    assert "error" in body


# ------------------------------------------------------------------
# Tests — POST /api/paper/{id}/close-all
# ------------------------------------------------------------------

def test_close_all_nonexistent_session(test_server):
    """POST /api/paper/nonexistent-id/close-all should return 404."""
    status, body = api_post(test_server, "/api/paper/nonexistent-id/close-all")
    assert status == 404
    assert "error" in body


# ------------------------------------------------------------------
# Tests — Trailing slash handling
# ------------------------------------------------------------------

def test_list_paper_sessions_trailing_slash(test_server):
    """GET /api/paper/ (with trailing slash) should also work."""
    status, body = api_get(test_server, "/api/paper/")
    assert status == 200
    assert "sessions" in body
