"""Integration tests for leveraged backtesting engine."""
import pytest
from models import Candle, OHLCVData, TradeSignal
from services.strategy_engine import StrategyEngine
from strategies.base_strategy import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):
    """Buys on candle 2, never sells."""
    @classmethod
    def metadata(cls):
        return {"name": "BuyHold", "description": "Test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 2:
            return TradeSignal(ohlcv.candles[index].timestamp, "BUY",
                               ohlcv.candles[index].close, "test buy")
        return None


class AlwaysBuyStrategy(BaseStrategy):
    """Buys on candle 2, never sells (rely on liquidation or forced close)."""
    @classmethod
    def metadata(cls):
        return {"name": "AlwaysBuy", "description": "Test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 2:
            return TradeSignal(ohlcv.candles[index].timestamp, "BUY",
                               ohlcv.candles[index].close, "test buy")
        return None


class AlwaysShortStrategy(BaseStrategy):
    """Shorts on candle 2."""
    @classmethod
    def metadata(cls):
        return {"name": "AlwaysShort", "description": "Test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 2:
            return TradeSignal(ohlcv.candles[index].timestamp, "SHORT",
                               ohlcv.candles[index].close, "test short")
        return None


def _make_candle(i, price, low=None, high=None):
    return Candle(
        timestamp=i * 3600000, open=price,
        high=high or price + 1, low=low or price - 1,
        close=price, volume=1000,
    )


class TestLeveragedQuantity:
    def test_3x_leverage_triples_quantity(self):
        """3x leverage should give ~3x the quantity of 1x."""
        candles = [_make_candle(i, 100) for i in range(5)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)

        trades_1x, _, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=1.0,
        )
        trades_3x, _, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=3.0,
        )

        assert trades_3x[0].quantity == pytest.approx(trades_1x[0].quantity * 3, rel=0.01)
        assert trades_3x[0].leverage == 3.0

    def test_leverage_stored_on_trade(self):
        """Trade object should have leverage, margin_used, liquidation_price."""
        candles = [_make_candle(i, 100) for i in range(5)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, _, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
            maintenance_margin_rate=0.005,
        )
        t = trades[0]
        assert t.leverage == 5.0
        assert t.margin_used == 1000.0
        assert t.liquidation_price > 0


class TestLeveragedPnL:
    def test_leveraged_profit_amplified(self):
        """5x leverage on 10% gain should give ~50% return."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),   # Buy at 100
            _make_candle(3, 110),   # 10% up -> 50% profit with 5x
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
        )
        # Margin = 1000, position = 5000, qty = 50
        # Exit at 110: PnL = 50 * 10 = 500, capital = 1000 + 500 = 1500
        assert equity[-1] == pytest.approx(1500, rel=0.02)

    def test_leveraged_loss_amplified(self):
        """5x leverage on 5% loss should give ~25% loss."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),
            _make_candle(3, 95),  # 5% down -> 25% loss with 5x
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
        )
        # PnL = 50 * (-5) = -250, capital = 1000 - 250 = 750
        assert equity[-1] == pytest.approx(750, rel=0.02)


class TestLiquidationInEngine:
    def test_long_liquidation_zeroes_capital(self):
        """After liquidation, capital goes to 0."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),  # Buy here at 100
            _make_candle(3, 95),   # Dropping
            _make_candle(4, 70, low=60),  # Crash -- should trigger liquidation for 5x
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, AlwaysBuyStrategy({}), initial_capital=1000,
            max_leverage=5.0, leverage_mode="fixed", fixed_leverage=5.0,
            maintenance_margin_rate=0.005,
        )
        assert len(trades) == 1
        assert trades[0].exit_type == "LIQUIDATION"
        assert equity[-1] == 0.0

    def test_short_liquidation_zeroes_capital(self):
        """SHORT liquidation when price surges."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),  # Short here
            _make_candle(3, 105),
            _make_candle(4, 140, high=145),  # Surge -- liquidation for 5x SHORT
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, AlwaysShortStrategy({}), initial_capital=1000,
            max_leverage=5.0, leverage_mode="fixed", fixed_leverage=5.0,
            maintenance_margin_rate=0.005,
        )
        assert len(trades) == 1
        assert trades[0].exit_type == "LIQUIDATION"
        assert equity[-1] == 0.0

    def test_no_liquidation_at_1x(self):
        """At 1x leverage, there's no liquidation price."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),  # Buy
            _make_candle(3, 50),   # 50% drop but 1x = no liq
            _make_candle(4, 30),   # 70% drop still no liq
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, AlwaysBuyStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=1.0,
            maintenance_margin_rate=0.005,
        )
        assert len(trades) == 1
        assert trades[0].exit_type == "FORCED_CLOSE"


class TestBackwardCompat:
    def test_1x_leverage_matches_old_behavior(self):
        """fixed_leverage=1.0 should produce same result as no leverage params."""
        candles = [_make_candle(i, 100 + i * 2) for i in range(10)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)

        # Old way (no leverage params -- uses defaults)
        trades_old, equity_old, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=10000,
        )

        # New way (explicit 1x)
        trades_new, equity_new, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=10000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=1.0,
        )

        assert len(trades_old) == len(trades_new)
        assert equity_old[-1] == pytest.approx(equity_new[-1], rel=0.001)

    def test_default_params_backward_compat(self):
        """Calling run() with no new params should work exactly as before."""
        candles = [_make_candle(i, 100 + i) for i in range(10)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine()
        trades, equity, timestamps = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=10000,
        )
        assert len(trades) >= 1
        assert len(equity) == len(candles)


class TestFundingInLoop:
    def test_funding_deducted_from_capital(self):
        """Funding rate should reduce capital over time for leveraged positions."""
        # Create 17 candles (enough for 2 funding events at 1h = every 8 candles)
        candles = [_make_candle(i, 100) for i in range(17)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)

        # With funding
        trades_f, equity_f, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
            funding_rate=0.001,  # 0.1% per 8h (high to make effect visible)
            interval="1h",
        )

        # Without funding
        trades_nf, equity_nf, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
            funding_rate=0.0,
            interval="1h",
        )

        # Funding should reduce final equity
        assert equity_f[-1] < equity_nf[-1]
        # Trade should record funding_paid > 0
        assert trades_f[0].funding_paid > 0

    def test_no_funding_at_1x(self):
        """No funding deducted when leverage is 1x even if funding_rate > 0."""
        candles = [_make_candle(i, 100) for i in range(17)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)

        trades, equity, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=1.0,
            funding_rate=0.001,
            interval="1h",
        )
        assert trades[0].funding_paid == 0.0


class TestLeveragedShort:
    def test_short_3x_leverage_triples_quantity(self):
        """3x SHORT leverage should give ~3x quantity."""
        candles = [_make_candle(i, 100) for i in range(5)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)

        trades_1x, _, _ = engine.run(
            ohlcv, AlwaysShortStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=1.0,
        )
        trades_3x, _, _ = engine.run(
            ohlcv, AlwaysShortStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=3.0,
        )

        assert trades_3x[0].quantity == pytest.approx(trades_1x[0].quantity * 3, rel=0.01)
        assert trades_3x[0].leverage == 3.0

    def test_short_leveraged_profit(self):
        """5x SHORT on 10% drop should give ~50% return."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),   # Short at 100
            _make_candle(3, 90),    # 10% down -> 50% profit for SHORT 5x
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, AlwaysShortStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
        )
        # Margin = 1000, qty = 50, PnL = (100-90)*50 = 500, capital = 1000+500 = 1500
        assert equity[-1] == pytest.approx(1500, rel=0.02)
