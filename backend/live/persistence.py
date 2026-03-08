"""
SQLite persistence for paper trading state.

DB file: configurable, defaults to /tmp/paper_trading.db
Separate from klines_cache.db to avoid schema conflicts.

Thread-safe via threading.local() for per-thread connections,
following the same pattern used in data_service.py.
"""
import sqlite3
import json
import os
import time
import threading
from typing import Optional, Dict, Any, List

from live.models import LiveOrder, Position, AccountState, TradingSessionConfig

DB_PATH = os.path.join("/tmp", "paper_trading.db")

_thread_local = threading.local()


class TradingPersistence:
    """SQLite persistence layer for paper trading sessions, orders, positions, and equity."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection with Row factory."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        """Create all tables and indexes if they do not exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'initialized',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL,
                price REAL,
                status TEXT NOT NULL,
                filled_quantity REAL,
                avg_fill_price REAL,
                commission REAL,
                created_time INTEGER,
                filled_time INTEGER,
                reason TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL,
                entry_price REAL,
                entry_time INTEGER,
                exit_price REAL,
                exit_time INTEGER,
                unrealized_pnl REAL,
                realized_pnl REAL,
                status TEXT NOT NULL,
                entry_order_id TEXT,
                exit_order_id TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                total_equity REAL,
                available_cash REAL,
                unrealized_pnl REAL,
                realized_pnl REAL,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_orders_session
                ON orders(session_id, created_time);
            CREATE INDEX IF NOT EXISTS idx_positions_session
                ON positions(session_id, status);
            CREATE INDEX IF NOT EXISTS idx_equity_session
                ON equity_snapshots(session_id, timestamp);
        """)
        conn.commit()

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def save_session(self, config: TradingSessionConfig, state: str = "initialized") -> None:
        """Insert or replace a trading session record."""
        conn = self._get_conn()
        now_ms = int(time.time() * 1000)
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, config_json, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (config.session_id, json.dumps(config.to_dict()), state, now_ms, now_ms),
        )
        conn.commit()

    def save_session_state(self, session_id: str, state: str) -> None:
        """Update a session's state (e.g. initialized -> running -> stopped)."""
        conn = self._get_conn()
        now_ms = int(time.time() * 1000)
        conn.execute(
            "UPDATE sessions SET state = ?, updated_at = ? WHERE session_id = ?",
            (state, now_ms, session_id),
        )
        conn.commit()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single session by ID, with config deserialized."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "config": json.loads(row["config_json"]),
            "state": row["state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Return all sessions ordered by creation time descending."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "config": json.loads(r["config_json"]),
                "state": r["state"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Order CRUD
    # ------------------------------------------------------------------

    def save_order(self, order: LiveOrder) -> None:
        """Insert or replace an order record."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO orders "
            "(order_id, session_id, symbol, side, order_type, quantity, price, "
            "status, filled_quantity, avg_fill_price, commission, "
            "created_time, filled_time, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.order_id,
                order.session_id,
                order.symbol,
                order.side,
                order.order_type,
                order.quantity,
                order.price,
                order.status,
                order.filled_quantity,
                order.avg_fill_price,
                order.commission,
                order.created_time,
                order.filled_time,
                order.reason,
            ),
        )
        conn.commit()

    def get_session_orders(self, session_id: str) -> List[LiveOrder]:
        """Return all orders for a session, ordered by created_time ascending."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM orders WHERE session_id = ? ORDER BY created_time",
            (session_id,),
        ).fetchall()
        return [self._row_to_order(r) for r in rows]

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> LiveOrder:
        """Reconstruct a LiveOrder dataclass from a DB row."""
        return LiveOrder(
            order_id=row["order_id"],
            session_id=row["session_id"],
            symbol=row["symbol"],
            side=row["side"],
            order_type=row["order_type"],
            quantity=row["quantity"] or 0.0,
            price=row["price"] or 0.0,
            status=row["status"],
            filled_quantity=row["filled_quantity"] or 0.0,
            avg_fill_price=row["avg_fill_price"] or 0.0,
            commission=row["commission"] or 0.0,
            created_time=row["created_time"] or 0,
            filled_time=row["filled_time"] or 0,
            reason=row["reason"] or "",
        )

    # ------------------------------------------------------------------
    # Position CRUD
    # ------------------------------------------------------------------

    def save_position(self, position: Position) -> None:
        """Insert or replace a position record."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO positions "
            "(position_id, session_id, symbol, side, quantity, entry_price, "
            "entry_time, exit_price, exit_time, unrealized_pnl, realized_pnl, "
            "status, entry_order_id, exit_order_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                position.position_id,
                position.session_id,
                position.symbol,
                position.side,
                position.quantity,
                position.entry_price,
                position.entry_time,
                position.exit_price,
                position.exit_time,
                position.unrealized_pnl,
                position.realized_pnl,
                position.status,
                position.entry_order_id,
                position.exit_order_id,
            ),
        )
        conn.commit()

    def get_session_positions(self, session_id: str, status: str = "") -> List[Position]:
        """Return positions for a session, optionally filtered by status."""
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM positions WHERE session_id = ? AND status = ? "
                "ORDER BY entry_time",
                (session_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM positions WHERE session_id = ? ORDER BY entry_time",
                (session_id,),
            ).fetchall()
        return [self._row_to_position(r) for r in rows]

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        """Reconstruct a Position dataclass from a DB row."""
        return Position(
            position_id=row["position_id"],
            session_id=row["session_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=row["quantity"] or 0.0,
            entry_price=row["entry_price"] or 0.0,
            entry_time=row["entry_time"] or 0,
            exit_price=row["exit_price"] or 0.0,
            exit_time=row["exit_time"] or 0,
            unrealized_pnl=row["unrealized_pnl"] or 0.0,
            realized_pnl=row["realized_pnl"] or 0.0,
            status=row["status"],
            entry_order_id=row["entry_order_id"] or "",
            exit_order_id=row["exit_order_id"] or "",
        )

    # ------------------------------------------------------------------
    # Equity snapshots
    # ------------------------------------------------------------------

    def save_equity_snapshot(self, account: AccountState) -> None:
        """Insert an equity snapshot (append-only, never replaces)."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO equity_snapshots "
            "(session_id, total_equity, available_cash, unrealized_pnl, "
            "realized_pnl, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                account.session_id,
                account.total_equity,
                account.available_cash,
                account.unrealized_pnl,
                account.realized_pnl,
                account.timestamp,
            ),
        )
        conn.commit()

    def get_equity_curve(self, session_id: str) -> List[AccountState]:
        """Return all equity snapshots for a session, ordered by timestamp."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM equity_snapshots WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [
            AccountState(
                session_id=r["session_id"],
                total_equity=r["total_equity"] or 0.0,
                available_cash=r["available_cash"] or 0.0,
                unrealized_pnl=r["unrealized_pnl"] or 0.0,
                realized_pnl=r["realized_pnl"] or 0.0,
                timestamp=r["timestamp"] or 0,
            )
            for r in rows
        ]
