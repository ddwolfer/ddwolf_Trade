"""Data models for live/paper trading sessions.

These models track orders, positions, account state, and session
configuration for the live trading module. Follows the same dataclass
pattern used in backend/models/__init__.py.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


@dataclass
class LiveOrder:
    """Represents a single trading order in a live/paper session."""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    session_id: str = ""
    symbol: str = ""
    side: str = "BUY"  # "BUY" or "SELL"
    order_type: str = "MARKET"  # "MARKET" or "LIMIT"
    quantity: float = 0.0
    price: float = 0.0
    status: str = "NEW"  # "NEW", "FILLED", "CANCELLED", "REJECTED"
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    leverage: float = 1.0
    created_time: int = 0  # ms
    filled_time: int = 0  # ms
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.created_time:
            d["created_time_str"] = datetime.fromtimestamp(
                self.created_time / 1000
            ).strftime("%Y-%m-%d %H:%M:%S")
        if self.filled_time:
            d["filled_time_str"] = datetime.fromtimestamp(
                self.filled_time / 1000
            ).strftime("%Y-%m-%d %H:%M:%S")
        return d


@dataclass
class Position:
    """Represents an open or closed trading position."""
    position_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    session_id: str = ""
    symbol: str = ""
    side: str = "LONG"  # "LONG" or "SHORT"
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_time: int = 0  # ms
    exit_price: float = 0.0
    exit_time: int = 0  # ms
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    status: str = "OPEN"  # "OPEN" or "CLOSED"
    leverage: float = 1.0
    margin_used: float = 0.0
    liquidation_price: float = 0.0
    funding_paid: float = 0.0
    entry_order_id: str = ""
    exit_order_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.entry_time:
            d["entry_time_str"] = datetime.fromtimestamp(
                self.entry_time / 1000
            ).strftime("%Y-%m-%d %H:%M:%S")
        if self.exit_time:
            d["exit_time_str"] = datetime.fromtimestamp(
                self.exit_time / 1000
            ).strftime("%Y-%m-%d %H:%M:%S")
        return d


@dataclass
class AccountState:
    """Snapshot of account balances at a point in time."""
    session_id: str = ""
    total_equity: float = 0.0
    available_cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: int = 0  # ms

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.timestamp:
            d["timestamp_str"] = datetime.fromtimestamp(
                self.timestamp / 1000
            ).strftime("%Y-%m-%d %H:%M:%S")
        return d


@dataclass
class TradingSessionConfig:
    """Configuration for a live/paper trading session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    strategy_name: str = "RSI"
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    initial_capital: float = 10000.0
    commission_rate: float = 0.001  # 0.1%
    slippage_rate: float = 0.0005  # 0.05%
    data_start_date: str = "2024-01-01"
    data_end_date: str = "2025-01-01"
    tick_interval_seconds: float = 1.0
    mode: str = "simulated"  # "simulated" or "paper" or "live"
    # Leverage / contract settings
    max_leverage: float = 10.0
    leverage_mode: str = "dynamic"         # "dynamic" or "fixed"
    fixed_leverage: float = 1.0
    funding_rate: float = 0.0001           # Per 8h
    maintenance_margin_rate: float = 0.005  # 0.5%
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
