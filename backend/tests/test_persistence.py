"""Tests for the SQLite paper-trading persistence layer."""
import os
import sys
import threading

import pytest

# Ensure backend/ is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from live.persistence import TradingPersistence
from live.models import (
    LiveOrder,
    Position,
    AccountState,
    TradingSessionConfig,
)


@pytest.fixture
def persistence(tmp_path):
    """Create an isolated TradingPersistence backed by a temp DB."""
    db_path = str(tmp_path / "test_trading.db")
    return TradingPersistence(db_path=db_path)


def _make_config(**overrides) -> TradingSessionConfig:
    """Helper to build a TradingSessionConfig with sensible defaults."""
    defaults = dict(
        session_id="sess-001",
        symbol="BTCUSDT",
        interval="1h",
        strategy_name="RSI",
        strategy_params={"period": 14, "overbought": 70},
        initial_capital=10_000.0,
    )
    defaults.update(overrides)
    return TradingSessionConfig(**defaults)


# ------------------------------------------------------------------
# Table creation
# ------------------------------------------------------------------

def test_create_tables_on_init(tmp_path):
    """DB file should exist and contain the four expected tables."""
    db_path = str(tmp_path / "init_test.db")
    TradingPersistence(db_path=db_path)

    assert os.path.exists(db_path)

    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "sessions" in tables
    assert "orders" in tables
    assert "positions" in tables
    assert "equity_snapshots" in tables


# ------------------------------------------------------------------
# Session CRUD
# ------------------------------------------------------------------

def test_save_and_get_session(persistence):
    """Saving then retrieving a session should round-trip all fields."""
    cfg = _make_config()
    persistence.save_session(cfg, state="initialized")

    result = persistence.get_session("sess-001")
    assert result is not None
    assert result["session_id"] == "sess-001"
    assert result["state"] == "initialized"
    assert result["config"]["symbol"] == "BTCUSDT"
    assert result["config"]["strategy_name"] == "RSI"
    assert result["config"]["strategy_params"] == {"period": 14, "overbought": 70}
    assert result["config"]["initial_capital"] == 10_000.0


def test_update_session_state(persistence):
    """Updating a session's state should be reflected on the next read."""
    cfg = _make_config()
    persistence.save_session(cfg, state="initialized")

    persistence.save_session_state("sess-001", "running")
    result = persistence.get_session("sess-001")
    assert result["state"] == "running"

    persistence.save_session_state("sess-001", "stopped")
    result = persistence.get_session("sess-001")
    assert result["state"] == "stopped"


# ------------------------------------------------------------------
# Order CRUD
# ------------------------------------------------------------------

def test_save_and_get_order(persistence):
    """Saving then retrieving an order should round-trip correctly."""
    cfg = _make_config()
    persistence.save_session(cfg)

    order = LiveOrder(
        order_id="ord-001",
        session_id="sess-001",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=0.5,
        price=42_000.0,
        status="FILLED",
        filled_quantity=0.5,
        avg_fill_price=42_010.0,
        commission=21.0,
        created_time=1_700_000_000_000,
        filled_time=1_700_000_001_000,
        reason="RSI oversold signal",
    )
    persistence.save_order(order)

    orders = persistence.get_session_orders("sess-001")
    assert len(orders) == 1
    o = orders[0]
    assert o.order_id == "ord-001"
    assert o.symbol == "BTCUSDT"
    assert o.side == "BUY"
    assert o.quantity == 0.5
    assert o.avg_fill_price == 42_010.0
    assert o.commission == 21.0
    assert o.reason == "RSI oversold signal"


def test_get_orders_ordered_by_time(persistence):
    """Orders should be returned in ascending created_time order."""
    cfg = _make_config()
    persistence.save_session(cfg)

    times = [1_700_000_003_000, 1_700_000_001_000, 1_700_000_002_000]
    for i, t in enumerate(times):
        persistence.save_order(
            LiveOrder(
                order_id=f"ord-{i}",
                session_id="sess-001",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                status="FILLED",
                created_time=t,
            )
        )

    orders = persistence.get_session_orders("sess-001")
    assert len(orders) == 3
    assert orders[0].created_time == 1_700_000_001_000
    assert orders[1].created_time == 1_700_000_002_000
    assert orders[2].created_time == 1_700_000_003_000


# ------------------------------------------------------------------
# Position CRUD
# ------------------------------------------------------------------

def test_save_and_get_position(persistence):
    """Saving then retrieving a position should round-trip correctly."""
    cfg = _make_config()
    persistence.save_session(cfg)

    pos = Position(
        position_id="pos-001",
        session_id="sess-001",
        symbol="BTCUSDT",
        side="LONG",
        quantity=0.5,
        entry_price=42_000.0,
        entry_time=1_700_000_000_000,
        exit_price=43_000.0,
        exit_time=1_700_000_100_000,
        unrealized_pnl=0.0,
        realized_pnl=500.0,
        status="CLOSED",
        entry_order_id="ord-001",
        exit_order_id="ord-002",
    )
    persistence.save_position(pos)

    positions = persistence.get_session_positions("sess-001")
    assert len(positions) == 1
    p = positions[0]
    assert p.position_id == "pos-001"
    assert p.side == "LONG"
    assert p.quantity == 0.5
    assert p.entry_price == 42_000.0
    assert p.realized_pnl == 500.0
    assert p.status == "CLOSED"
    assert p.entry_order_id == "ord-001"
    assert p.exit_order_id == "ord-002"


def test_get_positions_filter_by_status(persistence):
    """Filtering positions by status should return only matching rows."""
    cfg = _make_config()
    persistence.save_session(cfg)

    persistence.save_position(
        Position(
            position_id="pos-open",
            session_id="sess-001",
            symbol="BTCUSDT",
            side="LONG",
            status="OPEN",
            entry_time=1_700_000_000_000,
        )
    )
    persistence.save_position(
        Position(
            position_id="pos-closed",
            session_id="sess-001",
            symbol="BTCUSDT",
            side="LONG",
            status="CLOSED",
            entry_time=1_700_000_001_000,
        )
    )

    open_pos = persistence.get_session_positions("sess-001", status="OPEN")
    assert len(open_pos) == 1
    assert open_pos[0].position_id == "pos-open"

    closed_pos = persistence.get_session_positions("sess-001", status="CLOSED")
    assert len(closed_pos) == 1
    assert closed_pos[0].position_id == "pos-closed"

    all_pos = persistence.get_session_positions("sess-001")
    assert len(all_pos) == 2


# ------------------------------------------------------------------
# Equity snapshots
# ------------------------------------------------------------------

def test_save_and_get_equity_snapshots(persistence):
    """Equity snapshots should be returned in ascending timestamp order."""
    cfg = _make_config()
    persistence.save_session(cfg)

    for i in range(5):
        persistence.save_equity_snapshot(
            AccountState(
                session_id="sess-001",
                total_equity=10_000.0 + i * 100,
                available_cash=9_000.0 + i * 50,
                unrealized_pnl=float(i * 50),
                realized_pnl=float(i * 10),
                timestamp=1_700_000_000_000 + i * 60_000,
            )
        )

    curve = persistence.get_equity_curve("sess-001")
    assert len(curve) == 5
    # Should be chronologically ordered
    for i in range(len(curve) - 1):
        assert curve[i].timestamp < curve[i + 1].timestamp
    # Spot-check values
    assert curve[0].total_equity == 10_000.0
    assert curve[4].total_equity == 10_400.0
    assert curve[4].realized_pnl == 40.0


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

def test_empty_queries_return_empty_lists(persistence):
    """Querying a non-existent session should return empty results."""
    assert persistence.get_session("no-such-session") is None
    assert persistence.get_session_orders("no-such-session") == []
    assert persistence.get_session_positions("no-such-session") == []
    assert persistence.get_equity_curve("no-such-session") == []
    assert persistence.get_all_sessions() == []


def test_thread_safety_separate_connections(persistence):
    """Concurrent save/get operations from different threads should not crash."""
    cfg = _make_config()
    persistence.save_session(cfg)

    errors: list = []

    def worker(thread_idx: int) -> None:
        try:
            for i in range(20):
                oid = f"t{thread_idx}-ord-{i}"
                persistence.save_order(
                    LiveOrder(
                        order_id=oid,
                        session_id="sess-001",
                        symbol="BTCUSDT",
                        side="BUY",
                        order_type="MARKET",
                        status="FILLED",
                        created_time=1_700_000_000_000 + thread_idx * 1000 + i,
                    )
                )
            # Read back
            orders = persistence.get_session_orders("sess-001")
            assert len(orders) > 0
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
    # All 40 orders should be present
    orders = persistence.get_session_orders("sess-001")
    assert len(orders) == 40
