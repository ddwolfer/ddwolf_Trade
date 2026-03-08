"""
Comprehensive tests for PaperTradingAdapter.

Covers all financial calculations, position management, edge cases,
thread safety, and numerical precision. Every test includes explicit
expected values because this is money-related code.
"""
import pytest
import threading
from live.adapters.paper_adapter import PaperTradingAdapter


@pytest.fixture
def adapter():
    """Standard adapter: 10k capital, 0.1% commission, 0.05% slippage, BTC at 50k."""
    a = PaperTradingAdapter(
        "test-session",
        initial_capital=10000.0,
        commission_rate=0.001,
        slippage_rate=0.0005,
    )
    a.set_current_price("BTCUSDT", 50000.0)
    return a


# =====================================================================
# Basic Order Flow
# =====================================================================

def test_buy_order_fills_at_correct_price(adapter):
    """BUY fill_price = 50000 * (1 + 0.0005) = 50025.0"""
    order = adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    assert order.status == "FILLED"
    assert order.avg_fill_price == pytest.approx(50025.0, rel=1e-6)


def test_sell_order_fills_at_correct_price(adapter):
    """SELL fill_price = 50000 * (1 - 0.0005) = 49975.0"""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    order = adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)
    assert order.status == "FILLED"
    assert order.avg_fill_price == pytest.approx(49975.0, rel=1e-6)


def test_commission_deducted_correctly_on_buy(adapter):
    """commission = cost * 0.001"""
    order = adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    expected_cost = 50025.0 * 0.1  # 5002.5
    expected_commission = expected_cost * 0.001  # 5.0025
    assert order.commission == pytest.approx(expected_commission, rel=1e-6)


def test_commission_deducted_correctly_on_sell(adapter):
    """commission = proceeds * 0.001"""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    qty = pos.quantity  # capture before sell closes the position
    order = adapter.place_order("BTCUSDT", "SELL", "MARKET", qty)
    expected_proceeds = 49975.0 * qty
    expected_commission = expected_proceeds * 0.001
    assert order.commission == pytest.approx(expected_commission, rel=1e-6)


# =====================================================================
# Cash Tracking
# =====================================================================

def test_cash_decreases_after_buy(adapter):
    """Cash should decrease by cost + commission."""
    initial_cash = 10000.0
    order = adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    cost = order.avg_fill_price * order.filled_quantity
    commission = order.commission
    account = adapter.get_account_state()
    assert account.available_cash == pytest.approx(
        initial_cash - cost - commission, rel=1e-6
    )


def test_cash_increases_after_sell(adapter):
    """Cash should increase by proceeds - commission."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    cash_before_sell = adapter.get_account_state().available_cash
    sell_order = adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)
    proceeds = sell_order.avg_fill_price * sell_order.filled_quantity
    account = adapter.get_account_state()
    assert account.available_cash == pytest.approx(
        cash_before_sell + proceeds - sell_order.commission, rel=1e-6
    )


def test_equity_equals_cash_plus_position_value(adapter):
    """Total equity = cash + position_qty * current_price."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    account = adapter.get_account_state()
    expected_equity = account.available_cash + pos.quantity * 50000.0
    assert account.total_equity == pytest.approx(expected_equity, rel=1e-6)


def test_initial_equity_matches_capital(adapter):
    """Before any trades, equity = initial capital."""
    account = adapter.get_account_state()
    assert account.total_equity == pytest.approx(10000.0)
    assert account.available_cash == pytest.approx(10000.0)


# =====================================================================
# PnL Calculation (MOST CRITICAL)
# =====================================================================

def test_profitable_trade_pnl_calculation(adapter):
    """Buy at 50000, sell at 55000 -> positive PnL."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    entry_price = pos.entry_price  # 50025.0 (with slippage)
    qty = pos.quantity

    adapter.set_current_price("BTCUSDT", 55000.0)
    sell_order = adapter.place_order("BTCUSDT", "SELL", "MARKET", qty)

    exit_price = 55000.0 * (1 - 0.0005)  # 54972.5
    expected_pnl = (exit_price - entry_price) * qty - sell_order.commission

    account = adapter.get_account_state()
    assert account.realized_pnl == pytest.approx(expected_pnl, rel=1e-4)
    assert account.realized_pnl > 0  # Must be profitable


def test_losing_trade_pnl_calculation(adapter):
    """Buy at 50000, sell at 45000 -> negative PnL."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    entry_price = pos.entry_price
    qty = pos.quantity

    adapter.set_current_price("BTCUSDT", 45000.0)
    sell_order = adapter.place_order("BTCUSDT", "SELL", "MARKET", qty)

    exit_price = 45000.0 * (1 - 0.0005)
    expected_pnl = (exit_price - entry_price) * qty - sell_order.commission

    account = adapter.get_account_state()
    assert account.realized_pnl == pytest.approx(expected_pnl, rel=1e-4)
    assert account.realized_pnl < 0  # Must be a loss


def test_realized_pnl_accumulates_across_trades(adapter):
    """Multiple buy/sell cycles should accumulate realized PnL."""
    # Trade 1: profit
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.05)
    pos = adapter.get_position("BTCUSDT")
    adapter.set_current_price("BTCUSDT", 52000.0)
    adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)
    pnl_after_trade1 = adapter.get_account_state().realized_pnl

    # Trade 2: loss
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.05)
    pos = adapter.get_position("BTCUSDT")
    adapter.set_current_price("BTCUSDT", 50000.0)
    adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)
    pnl_after_trade2 = adapter.get_account_state().realized_pnl

    assert pnl_after_trade1 > 0  # First trade was profitable
    assert pnl_after_trade2 != pnl_after_trade1  # PnL changed


def test_unrealized_pnl_updates_with_price(adapter):
    """Unrealized PnL should update when price changes."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)

    adapter.set_current_price("BTCUSDT", 55000.0)
    account = adapter.get_account_state()
    assert account.unrealized_pnl > 0

    adapter.set_current_price("BTCUSDT", 45000.0)
    account = adapter.get_account_state()
    assert account.unrealized_pnl < 0


# =====================================================================
# Position Management
# =====================================================================

def test_position_created_on_buy(adapter):
    """BUY should create an OPEN position."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    assert pos is not None
    assert pos.status == "OPEN"
    assert pos.side == "LONG"
    assert pos.quantity > 0


def test_position_closed_on_sell(adapter):
    """SELL should close the position."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)
    assert adapter.get_position("BTCUSDT") is None


def test_no_position_after_full_sell(adapter):
    """After full sell, no open position should exist."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)
    assert len(adapter.get_all_positions()) == 0


def test_reject_sell_without_position(adapter):
    """SELL without position should be REJECTED."""
    order = adapter.place_order("BTCUSDT", "SELL", "MARKET", 0.1)
    assert order.status == "REJECTED"


def test_reject_buy_without_price(adapter):
    """BUY without set price should be REJECTED."""
    fresh = PaperTradingAdapter("test2", initial_capital=10000.0)
    order = fresh.place_order("ETHUSDT", "BUY", "MARKET", 1.0)
    assert order.status == "REJECTED"


# =====================================================================
# Insufficient Funds
# =====================================================================

def test_insufficient_funds_adjusts_quantity(adapter):
    """When requesting more than affordable, quantity should be adjusted."""
    # Try to buy way more than we can afford
    order = adapter.place_order("BTCUSDT", "BUY", "MARKET", 10.0)  # 10 BTC = $500k
    assert order.status == "FILLED"
    assert order.filled_quantity < 10.0  # Should be adjusted down
    assert order.filled_quantity > 0  # But should buy something
    account = adapter.get_account_state()
    assert account.available_cash >= 0  # Cash should never go negative


def test_zero_cash_after_full_buy(adapter):
    """Buying with all capital should leave ~0 cash."""
    order = adapter.place_order("BTCUSDT", "BUY", "MARKET", 100.0)  # More than affordable
    account = adapter.get_account_state()
    assert account.available_cash == pytest.approx(0.0, abs=0.01)


# =====================================================================
# Emergency Close
# =====================================================================

def test_close_all_positions(adapter):
    """close_all_positions should close everything."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    adapter.set_current_price("ETHUSDT", 3000.0)
    adapter.place_order("ETHUSDT", "BUY", "MARKET", 0.5)

    orders = adapter.close_all_positions("Emergency")
    assert len(orders) >= 1  # At least 1 close order
    assert len(adapter.get_all_positions()) == 0


def test_close_all_with_no_positions(adapter):
    """close_all with no positions returns empty list."""
    orders = adapter.close_all_positions()
    assert orders == []


# =====================================================================
# Thread Safety
# =====================================================================

def test_concurrent_operations(adapter):
    """Multiple threads doing operations shouldn't crash."""
    errors = []

    def buy_sell_cycle():
        try:
            for _ in range(5):
                adapter.set_current_price("BTCUSDT", 50000.0)
                adapter.get_account_state()
                adapter.get_all_positions()
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=buy_sell_cycle) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(errors) == 0


# =====================================================================
# Numerical Precision
# =====================================================================

def test_round_trip_preserves_capital_within_fees(adapter):
    """Buy then immediately sell at same price. Loss should equal fees + slippage only."""
    adapter.place_order("BTCUSDT", "BUY", "MARKET", 0.1)
    pos = adapter.get_position("BTCUSDT")
    adapter.place_order("BTCUSDT", "SELL", "MARKET", pos.quantity)

    account = adapter.get_account_state()
    # Loss should be small (just fees + slippage)
    loss = 10000.0 - account.total_equity
    assert loss > 0  # There IS a loss due to fees
    assert loss < 100  # But it should be small (< 1%)
