"""
Session Manager - manages multiple concurrent paper trading sessions.

Provides the interface that API routes call. Handles lifecycle
(deploy, stop, query) of LiveTradingEngine instances, backed by
SQLite persistence via TradingPersistence.
"""
import threading
from typing import Dict, List, Optional, Any

from live.models import TradingSessionConfig
from live.engine import LiveTradingEngine
from live.adapters.paper_adapter import PaperTradingAdapter
from live.persistence import TradingPersistence


class SessionManager:
    """
    Manages all active paper trading sessions.
    Created once at server startup.
    """

    def __init__(self, db_path: str = "") -> None:
        """
        Args:
            db_path: Optional custom DB path (for testing).
                     Empty string uses default /tmp/paper_trading.db
        """
        if db_path:
            self._persistence = TradingPersistence(db_path=db_path)
        else:
            self._persistence = TradingPersistence()
        self._engines: Dict[str, LiveTradingEngine] = {}
        self._adapters: Dict[str, PaperTradingAdapter] = {}
        self._lock = threading.Lock()

        # On init, mark any previously "running" sessions as "interrupted"
        self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        """Mark sessions that were 'running' when server died as 'interrupted'."""
        sessions = self._persistence.get_all_sessions()
        for s in sessions:
            if s.get("state") == "running":
                self._persistence.save_session_state(s["session_id"], "interrupted")

    def recover_interrupted(self) -> int:
        """Public method to mark any 'running' sessions as 'interrupted'.

        Intended to be called from app.py on server startup.
        Returns the number of sessions that were recovered.
        """
        sessions = self._persistence.get_all_sessions()
        count = 0
        for s in sessions:
            if s.get("state") == "running":
                self._persistence.save_session_state(s["session_id"], "interrupted")
                count += 1
        return count

    def deploy(self, config: TradingSessionConfig) -> Dict[str, Any]:
        """Start a new paper trading session.

        Args:
            config: Session configuration including strategy, symbol, etc.

        Returns:
            Status dict from the newly started engine.

        Raises:
            ValueError: If a session with the same ID already exists.
        """
        with self._lock:
            if config.session_id in self._engines:
                raise ValueError(f"Session {config.session_id} already exists")

            adapter = PaperTradingAdapter(
                session_id=config.session_id,
                initial_capital=config.initial_capital,
                commission_rate=config.commission_rate,
                slippage_rate=config.slippage_rate,
            )

            engine = LiveTradingEngine(config, adapter, self._persistence)
            self._persistence.save_session(config)
            self._engines[config.session_id] = engine
            self._adapters[config.session_id] = adapter

        engine.start()
        return engine.status()

    def stop_session(self, session_id: str) -> Dict[str, Any]:
        """Stop a running session.

        Args:
            session_id: The ID of the session to stop.

        Returns:
            Status dict after stopping.

        Raises:
            ValueError: If session is not found among active engines.
        """
        with self._lock:
            engine = self._engines.get(session_id)
            if not engine:
                raise ValueError(f"Session {session_id} not found")
        engine.stop()
        return engine.status()

    def get_status(self, session_id: str) -> Dict[str, Any]:
        """Get status of a session (active or historical).

        Args:
            session_id: The ID of the session.

        Returns:
            Status dict with session state, account info, etc.

        Raises:
            ValueError: If session is not found anywhere.
        """
        with self._lock:
            engine = self._engines.get(session_id)
        if engine:
            return engine.status()

        # Check DB for historical sessions
        session = self._persistence.get_session(session_id)
        if session:
            return {
                "session_id": session_id,
                "state": session.get("state", "unknown"),
                "config": session.get("config", {}),
                "candles_processed": 0,
                "signals_generated": 0,
                "account": {},
                "open_positions": [],
            }
        raise ValueError(f"Session {session_id} not found")

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions (active from memory + historical from DB).

        Returns:
            List of status dicts for all known sessions.
        """
        result: List[Dict[str, Any]] = []

        # Active sessions
        with self._lock:
            active_ids: set = set()
            for sid, engine in self._engines.items():
                status = engine.status()
                result.append(status)
                active_ids.add(sid)

        # Historical from DB (not currently active)
        db_sessions = self._persistence.get_all_sessions()
        for s in db_sessions:
            if s["session_id"] not in active_ids:
                result.append({
                    "session_id": s["session_id"],
                    "state": s.get("state", "unknown"),
                    "config": s.get("config", {}),
                    "candles_processed": 0,
                    "signals_generated": 0,
                    "account": {},
                    "open_positions": [],
                })
        return result

    def get_orders(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all orders for a session.

        Args:
            session_id: The ID of the session.

        Returns:
            List of order dicts.
        """
        orders = self._persistence.get_session_orders(session_id)
        return [o.to_dict() for o in orders]

    def get_positions(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all positions for a session (open + closed).

        Args:
            session_id: The ID of the session.

        Returns:
            List of position dicts.
        """
        positions = self._persistence.get_session_positions(session_id)
        return [p.to_dict() for p in positions]

    def get_equity_curve(self, session_id: str) -> Dict[str, Any]:
        """Get equity curve data for charting.

        Args:
            session_id: The ID of the session.

        Returns:
            Dict with equity_curve, timestamps, and cash_curve arrays.
        """
        snapshots = self._persistence.get_equity_curve(session_id)
        return {
            "session_id": session_id,
            "equity_curve": [s.total_equity for s in snapshots],
            "timestamps": [s.timestamp for s in snapshots],
            "cash_curve": [s.available_cash for s in snapshots],
        }

    def close_all_positions(self, session_id: str) -> List[Dict[str, Any]]:
        """Emergency close all positions for a session.

        Args:
            session_id: The ID of the session.

        Returns:
            List of close-order dicts.

        Raises:
            ValueError: If session is not found or not active.
        """
        with self._lock:
            adapter = self._adapters.get(session_id)
        if not adapter:
            raise ValueError(f"Session {session_id} not found or not active")
        orders = adapter.close_all_positions("Emergency close via API")
        for order in orders:
            self._persistence.save_order(order)
        return [o.to_dict() for o in orders]
