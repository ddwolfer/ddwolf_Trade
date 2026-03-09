"""
Exchange Adapter abstract base class.
All exchange adapters (Paper, Binance, etc.) implement this interface.
"""
from abc import ABC, abstractmethod
from typing import Optional, List
from live.models import LiveOrder, Position, AccountState


class ExchangeAdapter(ABC):
    """
    Unified interface for order execution.

    Strategies and the LiveTradingEngine interact ONLY through this
    interface. Swapping Paper for Binance requires zero strategy changes.
    """

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,          # "BUY" or "SELL"
        order_type: str,     # "MARKET" for Phase 1-2
        quantity: float,
        price: float = 0.0,  # ignored for MARKET
        reason: str = "",
        leverage: float = 1.0,
        maintenance_margin_rate: float = 0.005,
    ) -> LiveOrder:
        """Submit an order. Returns the order with status set."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if cancelled."""
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[LiveOrder]:
        """Get current state of an order."""
        pass

    @abstractmethod
    def get_open_orders(self, symbol: str = "") -> List[LiveOrder]:
        """Get all open (unfilled) orders, optionally filtered by symbol."""
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current open position for a symbol, or None."""
        pass

    @abstractmethod
    def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        pass

    @abstractmethod
    def get_account_state(self) -> AccountState:
        """Get current account snapshot (equity, cash, PnL)."""
        pass

    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """Get current market price for a symbol."""
        pass

    @abstractmethod
    def close_all_positions(self, reason: str = "Manual close") -> List[LiveOrder]:
        """Emergency: close all open positions at market."""
        pass

    def set_current_price(self, symbol: str, price: float) -> None:
        """Update current market price. Called by engine, not abstract."""
        pass
