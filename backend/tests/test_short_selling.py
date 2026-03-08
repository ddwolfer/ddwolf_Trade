"""
Comprehensive tests for SHORT selling functionality in the strategy engine.

Tests cover:
- SHORT open/close mechanics (SHORT, COVER, BUY-to-close)
- SHORT financial model (slippage, commission, PnL)
- Equity curve during SHORT positions
- Reversal flows (LONG→SHORT, SHORT→LONG)
- Stop-loss / take-profit on SHORT positions
- Backward compatibility (existing strategies unchanged)
- Force close at end of backtest
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import Candle, OHLCVData, TradeSignal
from services.strategy_engine import StrategyEngine
from strategies.base_strategy import BaseStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ohlcv(prices):
    """Build OHLCVData from a list of (open, high, low, close) tuples."""
    candles = []
    for i, (o, h, l, c) in enumerate(prices):
        candles.append(Candle(
            timestamp=(1704067200 + i * 3600) * 1000,
            open=o, high=h, low=l, close=c, volume=100,
        ))
    return OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)


# ---------------------------------------------------------------------------
# Test strategy helpers (NOT registered in the global registry)
# ---------------------------------------------------------------------------

class ShortOnSecondCandleStrategy(BaseStrategy):
    """SHORT on candle 1, no other signals."""

    @classmethod
    def metadata(cls):
        return {"name": "TestShort", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SHORT",
                ohlcv.candles[index].close, "Test short",
            )
        return None


class ShortThenCoverStrategy(BaseStrategy):
    """SHORT on candle 1, COVER on candle 3."""

    @classmethod
    def metadata(cls):
        return {"name": "TestShortCover", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SHORT",
                ohlcv.candles[index].close, "Short entry",
            )
        if index == 3:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "COVER",
                ohlcv.candles[index].close, "Cover exit",
            )
        return None


class ShortThenBuyStrategy(BaseStrategy):
    """SHORT on candle 1, BUY on candle 3 (close SHORT + open LONG)."""

    @classmethod
    def metadata(cls):
        return {"name": "TestShortBuy", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SHORT",
                ohlcv.candles[index].close, "Short entry",
            )
        if index == 3:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "BUY",
                ohlcv.candles[index].close, "Buy to close short",
            )
        return None


class BuyThenShortStrategy(BaseStrategy):
    """BUY on candle 1, SHORT on candle 3 (close LONG then open SHORT)."""

    @classmethod
    def metadata(cls):
        return {"name": "TestBuyShort", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "BUY",
                ohlcv.candles[index].close, "Buy entry",
            )
        if index == 3:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SHORT",
                ohlcv.candles[index].close, "Short reversal",
            )
        return None


class SellWithNoPositionStrategy(BaseStrategy):
    """SELL on candle 1 when there is no open position."""

    @classmethod
    def metadata(cls):
        return {"name": "TestSellNoop", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SELL",
                ohlcv.candles[index].close, "Sell with no pos",
            )
        return None


class MixedLongShortStrategy(BaseStrategy):
    """BUY idx=1, SELL idx=3, SHORT idx=5, COVER idx=7."""

    @classmethod
    def metadata(cls):
        return {"name": "TestMixed", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "BUY",
                ohlcv.candles[index].close, "Buy entry",
            )
        if index == 3:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SELL",
                ohlcv.candles[index].close, "Sell exit",
            )
        if index == 5:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SHORT",
                ohlcv.candles[index].close, "Short entry",
            )
        if index == 7:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "COVER",
                ohlcv.candles[index].close, "Cover exit",
            )
        return None


class ShortWithSLTPStrategy(BaseStrategy):
    """SHORT on candle 1. Designed to be used with SL/TP engine params."""

    @classmethod
    def metadata(cls):
        return {"name": "TestShortSLTP", "description": "Test",
                "category": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp, "SHORT",
                ohlcv.candles[index].close, "Short entry",
            )
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestShortOpensPosition:
    """1. SHORT signal creates a trade with side='SHORT'."""

    def test_short_opens_position(self):
        prices = [
            (100, 105, 95, 100),  # idx 0
            (100, 105, 95, 100),  # idx 1 - SHORT here
            (100, 105, 95, 100),  # idx 2
            (100, 105, 95, 100),  # idx 3
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortOnSecondCandleStrategy({})

        trades, equity_curve, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        # Should have exactly 1 trade (force-closed at end)
        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == "SHORT"
        assert trade.status == "CLOSED"
        # Entry price = close * (1 - slippage)
        expected_fill = 100 * (1 - 0.0005)
        assert trade.entry_price == pytest.approx(expected_fill, rel=1e-6)


class TestCoverClosesShort:
    """2. SHORT then COVER closes the position."""

    def test_cover_closes_short(self):
        prices = [
            (100, 105, 95, 100),  # idx 0
            (100, 105, 95, 100),  # idx 1 - SHORT
            (95, 100, 90, 95),    # idx 2
            (90, 95, 85, 90),     # idx 3 - COVER
            (90, 95, 85, 90),     # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == "SHORT"
        assert trade.status == "CLOSED"
        assert trade.exit_type == "SIGNAL"
        # Exit price for SHORT close = close * (1 + slippage)
        expected_exit = 90 * (1 + 0.0005)
        assert trade.exit_price == pytest.approx(expected_exit, rel=1e-6)


class TestBuyClosesShort:
    """3. SHORT then BUY closes the SHORT and opens a LONG."""

    def test_buy_closes_short(self):
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT
            (95, 100, 90, 95),     # idx 2
            (90, 95, 85, 90),      # idx 3 - BUY (close SHORT + open LONG)
            (95, 100, 90, 95),     # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortThenBuyStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        # 2 trades: SHORT closed by BUY, then LONG force-closed at end
        assert len(trades) == 2

        short_trade = trades[0]
        assert short_trade.side == "SHORT"
        assert short_trade.status == "CLOSED"
        assert short_trade.exit_type == "SIGNAL"

        long_trade = trades[1]
        assert long_trade.side == "LONG"
        assert long_trade.status == "CLOSED"
        assert long_trade.exit_type == "FORCED_CLOSE"


class TestShortProfit:
    """4. SHORT at 100, price drops to 90, cover -> positive PnL."""

    def test_short_profit(self):
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT at 100
            (95, 100, 90, 95),     # idx 2 - price dropping
            (90, 95, 85, 90),      # idx 3 - COVER at 90 -> profit
            (90, 95, 85, 90),      # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        trade = trades[0]
        assert trade.side == "SHORT"
        # Entry > exit => profit on SHORT
        assert trade.entry_price > trade.exit_price
        assert trade.profit_loss > 0
        assert trade.return_pct > 0


class TestShortLoss:
    """5. SHORT at 100, price rises to 110, cover -> negative PnL."""

    def test_short_loss(self):
        prices = [
            (100, 105, 95, 100),    # idx 0
            (100, 105, 95, 100),    # idx 1 - SHORT at 100
            (105, 110, 100, 105),   # idx 2 - price rising
            (110, 115, 105, 110),   # idx 3 - COVER at 110 -> loss
            (110, 115, 105, 110),   # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        trade = trades[0]
        assert trade.side == "SHORT"
        # Entry < exit => loss on SHORT
        assert trade.entry_price < trade.exit_price
        assert trade.profit_loss < 0
        assert trade.return_pct < 0


class TestShortSlippage:
    """6. Verify SHORT slippage: open fill = close*(1-slip), close fill = close*(1+slip)."""

    def test_short_slippage(self):
        slip = 0.001  # Use a more visible slippage for clarity
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT
            (95, 100, 90, 95),     # idx 2
            (90, 95, 85, 90),      # idx 3 - COVER
            (90, 95, 85, 90),      # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.0, slippage_rate=slip)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        trade = trades[0]
        # SHORT open: sell at lower price due to slippage
        assert trade.entry_price == pytest.approx(100 * (1 - slip), rel=1e-9)
        # SHORT close (COVER): buy back at higher price due to slippage
        assert trade.exit_price == pytest.approx(90 * (1 + slip), rel=1e-9)


class TestShortCommission:
    """7. Verify commission is deducted on both SHORT open and close."""

    def test_short_commission(self):
        comm = 0.001  # 0.1%
        slip = 0.0    # Zero slippage to isolate commission effects
        initial_capital = 10000.0

        # Flat price -> zero gross PnL, only commission costs
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT at 100
            (100, 105, 95, 100),   # idx 2
            (100, 105, 95, 100),   # idx 3 - COVER at 100
            (100, 105, 95, 100),   # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=comm, slippage_rate=slip)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=initial_capital)

        trade = trades[0]
        assert trade.side == "SHORT"

        # With zero slippage and flat price, entry and exit are both 100.
        # Gross PnL = (entry - exit) * qty = 0
        # At open: commission = capital * comm_rate = 10000 * 0.001 = 10
        # available = 10000 - 10 = 9990
        # qty = 9990 / 100 = 99.9
        # At close: buy_cost = qty * 100 = 9990
        # close_commission = 9990 * 0.001 = 9.99
        # PnL = (100 - 100) * 99.9 - 9.99 = -9.99
        expected_qty = (initial_capital - initial_capital * comm) / 100.0
        assert trade.quantity == pytest.approx(expected_qty, rel=1e-6)

        close_commission = expected_qty * 100 * comm
        expected_pnl = 0 - close_commission  # gross PnL is 0, minus exit commission
        assert trade.profit_loss == pytest.approx(expected_pnl, rel=1e-4)

        # Final capital should be less than initial (both commissions eaten)
        final_equity = eq[-1]
        assert final_equity < initial_capital


class TestShortEquityCurve:
    """8. During SHORT position: equity = capital + (entry - current) * qty."""

    def test_short_equity_curve(self):
        comm = 0.001
        slip = 0.0005
        initial_capital = 10000.0

        prices = [
            (100, 105, 95, 100),   # idx 0 - no position
            (100, 105, 95, 100),   # idx 1 - SHORT at close=100
            (95, 100, 90, 95),     # idx 2 - price dropped
            (90, 95, 85, 90),      # idx 3 - COVER at close=90
            (90, 95, 85, 90),      # idx 4 - no position
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=comm, slippage_rate=slip)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=initial_capital)

        # idx 0: no position, equity = capital = 10000
        assert eq[0] == pytest.approx(initial_capital, rel=1e-6)

        # idx 1: SHORT just opened
        # fill_price = 100 * (1 - 0.0005) = 99.95
        # commission = 10000 * 0.001 = 10
        # available = 10000 - 10 = 9990
        # qty = 9990 / 99.95 = ...
        # capital after open = 10000 - 10 = 9990
        # equity = capital + (entry - current) * qty
        #        = 9990 + (99.95 - 100) * qty  (current = close = 100)
        fill_price = 100 * (1 - slip)
        entry_commission = initial_capital * comm
        available = initial_capital - entry_commission
        qty = available / fill_price
        capital_after_open = initial_capital - entry_commission

        equity_idx1 = capital_after_open + (fill_price - 100) * qty
        assert eq[1] == pytest.approx(equity_idx1, rel=1e-4)

        # idx 2: still SHORT, price = 95
        # equity = capital + (entry - 95) * qty
        equity_idx2 = capital_after_open + (fill_price - 95) * qty
        assert eq[2] == pytest.approx(equity_idx2, rel=1e-4)

        # idx 3: COVER executed, position closed. Equity = new capital
        # idx 4: no position, equity = capital (same as idx 3)
        assert eq[3] == pytest.approx(eq[4], rel=1e-6)


class TestSellIgnoredNoPosition:
    """9. SELL when no position open -> ignored (backward compatible)."""

    def test_sell_ignored_no_position(self):
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SELL (no position)
            (100, 105, 95, 100),   # idx 2
            (100, 105, 95, 100),   # idx 3
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = SellWithNoPositionStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        # No trades should be generated
        assert len(trades) == 0
        # Equity should stay flat at initial capital
        for e in eq:
            assert e == pytest.approx(10000.0, rel=1e-6)


class TestShortReversalFromLong:
    """10. BUY on candle 1, SHORT on candle 3 -> closes LONG + opens SHORT (2 trades)."""

    def test_short_reversal_from_long(self):
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - BUY
            (105, 110, 100, 105),  # idx 2
            (110, 115, 105, 110),  # idx 3 - SHORT (close LONG + open SHORT)
            (105, 110, 100, 105),  # idx 4
            (100, 105, 95, 100),   # idx 5
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = BuyThenShortStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        # Should produce 2 trades:
        # 1) LONG closed by reversal
        # 2) SHORT force-closed at end
        assert len(trades) == 2

        long_trade = trades[0]
        assert long_trade.side == "LONG"
        assert long_trade.status == "CLOSED"
        assert long_trade.exit_type == "SIGNAL"
        assert long_trade.exit_reason == "Reversing to SHORT"

        short_trade = trades[1]
        assert short_trade.side == "SHORT"
        assert short_trade.status == "CLOSED"
        # SHORT should be force-closed at end
        assert short_trade.exit_type == "FORCED_CLOSE"


class TestExistingRSIStrategyUnchanged:
    """11. RSI strategy produces only LONG trades — no SHORT trades."""

    def test_existing_rsi_strategy_unchanged(self):
        # Import RSI strategy (triggers registration)
        import strategies.rsi_strategy  # noqa: F401
        from strategies.registry import StrategyRegistry
        from services.data_service import fetch_klines

        rsi = StrategyRegistry.create("RSI", {})
        ohlcv = fetch_klines("BTCUSDT", "1h", "2024-01-01", "2024-04-01")

        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        trades, eq, ts = engine.run(ohlcv, rsi, initial_capital=10000.0)

        # All trades should be LONG (RSI strategy only emits BUY/SELL)
        for trade in trades:
            assert trade.side == "LONG", (
                f"RSI strategy produced a {trade.side} trade — expected only LONG"
            )


class TestShortForceClose:
    """12. Open SHORT at end of data -> force closed with exit_type='FORCED_CLOSE'."""

    def test_short_force_close(self):
        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT (never covered)
            (95, 100, 90, 95),     # idx 2
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortOnSecondCandleStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == "SHORT"
        assert trade.status == "CLOSED"
        assert trade.exit_type == "FORCED_CLOSE"
        assert trade.exit_reason == "End of backtest period"

        # Force close exit price for SHORT = last_close * (1 + slippage)
        expected_exit = 95 * (1 + 0.0005)
        assert trade.exit_price == pytest.approx(expected_exit, rel=1e-6)


class TestShortWithSLTP:
    """13. SHORT + SL=5%. Price rises to trigger SL. Verify SL exit."""

    def test_short_with_sl_tp(self):
        # SHORT at idx=1, close=100.  SL at 5% means SL price = entry * 1.05.
        # entry_price = 100 * (1 - 0.0005) = 99.95
        # SL trigger = 99.95 * 1.05 = ~104.9475
        # Candle idx=2 high reaches 106, which exceeds SL level.
        prices = [
            (100, 105, 95, 100),    # idx 0
            (100, 105, 95, 100),    # idx 1 - SHORT
            (102, 106, 100, 104),   # idx 2 - high=106 triggers SL
            (104, 108, 102, 106),   # idx 3 - not reached if SL hit
            (106, 110, 104, 108),   # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortWithSLTPStrategy({})

        trades, eq, ts = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == "SHORT"
        assert trade.exit_type == "STOP_LOSS"
        assert trade.status == "CLOSED"

        # SL price = entry * (1 + 5/100)
        entry = 100 * (1 - 0.0005)
        expected_sl_price = entry * (1 + 5.0 / 100)
        assert trade.exit_price == pytest.approx(expected_sl_price, rel=1e-6)

        # Loss: we shorted, price went up
        assert trade.profit_loss < 0

    def test_short_with_take_profit(self):
        """SHORT + TP=10%. Price drops to trigger TP. Verify TP exit."""
        # SHORT at idx=1, close=100.
        # entry_price = 100 * (1 - 0.0005) = 99.95
        # TP trigger = 99.95 * (1 - 0.10) = ~89.955
        # Candle idx=2 low reaches 88, which is below TP level.
        prices = [
            (100, 105, 95, 100),    # idx 0
            (100, 105, 95, 100),    # idx 1 - SHORT
            (95, 98, 88, 90),       # idx 2 - low=88 triggers TP
            (90, 92, 85, 88),       # idx 3
            (88, 90, 85, 87),       # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = ShortWithSLTPStrategy({})

        trades, eq, ts = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=10.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == "SHORT"
        assert trade.exit_type == "TAKE_PROFIT"
        assert trade.status == "CLOSED"

        entry = 100 * (1 - 0.0005)
        expected_tp_price = entry * (1 - 10.0 / 100)
        assert trade.exit_price == pytest.approx(expected_tp_price, rel=1e-6)

        # Profit: we shorted, price went down
        assert trade.profit_loss > 0


class TestMixedLongShort:
    """14. Strategy alternates BUY/SELL/SHORT/COVER -> all tracked correctly."""

    def test_mixed_long_short(self):
        prices = [
            (100, 105, 95, 100),    # idx 0
            (100, 105, 95, 100),    # idx 1 - BUY
            (105, 110, 100, 105),   # idx 2
            (110, 115, 105, 110),   # idx 3 - SELL (close LONG)
            (108, 112, 104, 108),   # idx 4
            (108, 112, 104, 108),   # idx 5 - SHORT
            (104, 108, 100, 104),   # idx 6
            (100, 104, 96, 100),    # idx 7 - COVER (close SHORT)
            (100, 104, 96, 100),    # idx 8
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = MixedLongShortStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        assert len(trades) == 2

        # First trade: LONG
        long_trade = trades[0]
        assert long_trade.side == "LONG"
        assert long_trade.status == "CLOSED"
        assert long_trade.exit_type == "SIGNAL"
        # LONG profit: bought at ~100, sold at ~110
        assert long_trade.profit_loss > 0

        # Second trade: SHORT
        short_trade = trades[1]
        assert short_trade.side == "SHORT"
        assert short_trade.status == "CLOSED"
        assert short_trade.exit_type == "SIGNAL"
        # SHORT profit: shorted at ~108, covered at ~100
        assert short_trade.profit_loss > 0

        # Final equity should be > initial (both trades profitable)
        assert eq[-1] > 10000.0

    def test_mixed_long_short_trade_sequence(self):
        """Verify entry/exit timestamps are in proper sequential order."""
        prices = [
            (100, 105, 95, 100),    # idx 0
            (100, 105, 95, 100),    # idx 1 - BUY
            (105, 110, 100, 105),   # idx 2
            (110, 115, 105, 110),   # idx 3 - SELL
            (108, 112, 104, 108),   # idx 4
            (108, 112, 104, 108),   # idx 5 - SHORT
            (104, 108, 100, 104),   # idx 6
            (100, 104, 96, 100),    # idx 7 - COVER
            (100, 104, 96, 100),    # idx 8
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)
        strategy = MixedLongShortStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=10000.0)

        # entry timestamps should be candle 1 and candle 5
        assert trades[0].entry_time == ohlcv.candles[1].timestamp
        assert trades[0].exit_time == ohlcv.candles[3].timestamp
        assert trades[1].entry_time == ohlcv.candles[5].timestamp
        assert trades[1].exit_time == ohlcv.candles[7].timestamp

        # LONG exit must precede SHORT entry (or same candle)
        assert trades[0].exit_time <= trades[1].entry_time

        # All equity curve entries should be positive
        for e in eq:
            assert e > 0


class TestShortPnLAccuracy:
    """Additional precision tests for SHORT PnL calculations."""

    def test_short_pnl_exact(self):
        """Verify exact PnL formula: PnL = (entry - exit) * qty - exit_commission."""
        comm = 0.001
        slip = 0.0005
        initial_capital = 10000.0

        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT at 100
            (95, 100, 90, 95),     # idx 2
            (90, 95, 85, 90),      # idx 3 - COVER at 90
            (90, 95, 85, 90),      # idx 4
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=comm, slippage_rate=slip)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=initial_capital)

        trade = trades[0]

        # Manually compute expected values
        entry_fill = 100 * (1 - slip)       # 99.95
        entry_comm = initial_capital * comm  # 10
        available = initial_capital - entry_comm  # 9990
        qty = available / entry_fill

        exit_fill = 90 * (1 + slip)          # 90.045
        buy_cost = qty * exit_fill
        exit_comm = buy_cost * comm

        expected_pnl = (entry_fill - exit_fill) * qty - exit_comm

        assert trade.profit_loss == pytest.approx(expected_pnl, rel=1e-4)

    def test_short_capital_after_close(self):
        """Verify capital = entry_value + pnl after SHORT close."""
        comm = 0.001
        slip = 0.0005
        initial_capital = 10000.0

        prices = [
            (100, 105, 95, 100),   # idx 0
            (100, 105, 95, 100),   # idx 1 - SHORT
            (95, 100, 90, 95),     # idx 2
            (90, 95, 85, 90),      # idx 3 - COVER
            (90, 95, 85, 90),      # idx 4 - no position, equity = capital
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=comm, slippage_rate=slip)
        strategy = ShortThenCoverStrategy({})

        trades, eq, ts = engine.run(ohlcv, strategy, initial_capital=initial_capital)

        trade = trades[0]
        entry_value = trade.entry_price * trade.quantity
        expected_capital = entry_value + trade.profit_loss

        # At idx 3 after cover, equity should equal the resulting capital.
        # At idx 4 (no position), equity = capital.
        assert eq[4] == pytest.approx(expected_capital, rel=1e-4)
        # idx 3 and idx 4 should be same (no position on both after close)
        assert eq[3] == pytest.approx(eq[4], rel=1e-6)
