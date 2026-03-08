"""Unit tests for live trading data models."""
import pytest
from live.models import LiveOrder, Position, AccountState, TradingSessionConfig


class TestLiveOrder:
    """Tests for the LiveOrder dataclass."""

    def test_live_order_defaults(self):
        """Verify default values for a new LiveOrder."""
        order = LiveOrder()
        assert order.status == "NEW"
        assert order.order_type == "MARKET"
        assert order.side == "BUY"
        assert order.quantity == 0.0
        assert order.price == 0.0
        assert order.filled_quantity == 0.0
        assert order.avg_fill_price == 0.0
        assert order.commission == 0.0
        assert order.created_time == 0
        assert order.filled_time == 0
        assert order.reason == ""
        assert order.session_id == ""
        assert order.symbol == ""
        assert len(order.order_id) == 12

    def test_live_order_to_dict(self):
        """Verify to_dict serialization with human-readable timestamps."""
        order = LiveOrder(
            session_id="sess-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.5,
            price=50000.0,
            created_time=1704067200000,  # 2024-01-01 00:00:00 UTC
            filled_time=1704067260000,   # 2024-01-01 00:01:00 UTC
            status="FILLED",
            filled_quantity=0.5,
            avg_fill_price=50010.0,
            commission=25.005,
        )
        d = order.to_dict()
        assert d["session_id"] == "sess-001"
        assert d["symbol"] == "BTCUSDT"
        assert d["side"] == "BUY"
        assert d["quantity"] == 0.5
        assert d["status"] == "FILLED"
        assert "created_time_str" in d
        assert "filled_time_str" in d
        # Timestamps should be formatted as strings
        assert isinstance(d["created_time_str"], str)
        assert isinstance(d["filled_time_str"], str)

    def test_live_order_to_dict_no_timestamps(self):
        """Verify to_dict omits timestamp strings when timestamps are zero."""
        order = LiveOrder()
        d = order.to_dict()
        assert "created_time_str" not in d
        assert "filled_time_str" not in d

    def test_live_order_unique_ids(self):
        """Two orders should get different order_ids."""
        order1 = LiveOrder()
        order2 = LiveOrder()
        assert order1.order_id != order2.order_id


class TestPosition:
    """Tests for the Position dataclass."""

    def test_position_defaults(self):
        """Verify default values for a new Position."""
        pos = Position()
        assert pos.side == "LONG"
        assert pos.status == "OPEN"
        assert pos.quantity == 0.0
        assert pos.entry_price == 0.0
        assert pos.exit_price == 0.0
        assert pos.entry_time == 0
        assert pos.exit_time == 0
        assert pos.unrealized_pnl == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.entry_order_id == ""
        assert pos.exit_order_id == ""
        assert pos.session_id == ""
        assert pos.symbol == ""
        assert len(pos.position_id) == 12

    def test_position_to_dict(self):
        """Verify to_dict serialization with human-readable timestamps."""
        pos = Position(
            session_id="sess-001",
            symbol="ETHUSDT",
            side="LONG",
            quantity=10.0,
            entry_price=3000.0,
            entry_time=1704067200000,  # 2024-01-01 00:00:00 UTC
            exit_price=3100.0,
            exit_time=1704153600000,   # 2024-01-02 00:00:00 UTC
            realized_pnl=1000.0,
            status="CLOSED",
            entry_order_id="ord-001",
            exit_order_id="ord-002",
        )
        d = pos.to_dict()
        assert d["session_id"] == "sess-001"
        assert d["symbol"] == "ETHUSDT"
        assert d["side"] == "LONG"
        assert d["realized_pnl"] == 1000.0
        assert d["status"] == "CLOSED"
        assert "entry_time_str" in d
        assert "exit_time_str" in d
        assert isinstance(d["entry_time_str"], str)
        assert isinstance(d["exit_time_str"], str)

    def test_position_to_dict_no_exit_time(self):
        """Open position should not have exit_time_str."""
        pos = Position(entry_time=1704067200000)
        d = pos.to_dict()
        assert "entry_time_str" in d
        assert "exit_time_str" not in d


class TestAccountState:
    """Tests for the AccountState dataclass."""

    def test_account_state_defaults(self):
        """Verify all default values are zero/empty."""
        state = AccountState()
        assert state.session_id == ""
        assert state.total_equity == 0.0
        assert state.available_cash == 0.0
        assert state.unrealized_pnl == 0.0
        assert state.realized_pnl == 0.0
        assert state.timestamp == 0

    def test_account_state_to_dict(self):
        """Verify to_dict serialization with timestamp string."""
        state = AccountState(
            session_id="sess-001",
            total_equity=10500.0,
            available_cash=5000.0,
            unrealized_pnl=300.0,
            realized_pnl=200.0,
            timestamp=1704067200000,
        )
        d = state.to_dict()
        assert d["session_id"] == "sess-001"
        assert d["total_equity"] == 10500.0
        assert d["available_cash"] == 5000.0
        assert d["unrealized_pnl"] == 300.0
        assert d["realized_pnl"] == 200.0
        assert "timestamp_str" in d
        assert isinstance(d["timestamp_str"], str)

    def test_account_state_to_dict_no_timestamp(self):
        """Verify to_dict omits timestamp_str when timestamp is zero."""
        state = AccountState()
        d = state.to_dict()
        assert "timestamp_str" not in d


class TestTradingSessionConfig:
    """Tests for the TradingSessionConfig dataclass."""

    def test_trading_session_config_defaults(self):
        """Verify all default values match specification."""
        config = TradingSessionConfig()
        assert config.symbol == "BTCUSDT"
        assert config.interval == "1h"
        assert config.strategy_name == "RSI"
        assert config.strategy_params == {}
        assert config.initial_capital == 10000.0
        assert config.commission_rate == 0.001
        assert config.slippage_rate == 0.0005
        assert config.data_start_date == "2024-01-01"
        assert config.data_end_date == "2025-01-01"
        assert config.tick_interval_seconds == 1.0
        assert config.mode == "simulated"
        assert len(config.session_id) == 8

    def test_trading_session_config_to_dict(self):
        """Verify asdict-based serialization includes all fields."""
        config = TradingSessionConfig(
            symbol="ETHUSDT",
            interval="4h",
            strategy_name="MACD",
            strategy_params={"fast": 12, "slow": 26},
            initial_capital=50000.0,
        )
        d = config.to_dict()
        assert d["symbol"] == "ETHUSDT"
        assert d["interval"] == "4h"
        assert d["strategy_name"] == "MACD"
        assert d["strategy_params"] == {"fast": 12, "slow": 26}
        assert d["initial_capital"] == 50000.0
        assert d["commission_rate"] == 0.001
        assert d["slippage_rate"] == 0.0005
        assert "session_id" in d

    def test_trading_session_config_unique_ids(self):
        """Two configs should get different session_ids."""
        config1 = TradingSessionConfig()
        config2 = TradingSessionConfig()
        assert config1.session_id != config2.session_id
