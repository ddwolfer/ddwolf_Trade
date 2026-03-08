"""
Tests for stop-loss and take-profit functionality in StrategyEngine.

Covers:
- LONG position SL/TP triggers
- SHORT position SL/TP triggers
- SL priority over TP when both trigger on same candle
- SL checked before signal generation
- PnL correctness for SL/TP exits
- Backward compatibility when SL/TP are disabled (default 0)
- exit_type field: SIGNAL, STOP_LOSS, TAKE_PROFIT, FORCED_CLOSE
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import Candle, OHLCVData, TradeSignal
from services.strategy_engine import StrategyEngine
from strategies.base_strategy import BaseStrategy


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

BASE_TS = 1704067200000  # 2024-01-01T00:00:00Z in ms


def make_ohlcv(prices):
    """
    Build OHLCVData from a list of (open, high, low, close) tuples.

    Each tuple becomes one 1h candle with volume=100.
    """
    candles = []
    for i, (o, h, l, c) in enumerate(prices):
        candles.append(Candle(
            timestamp=BASE_TS + i * 3600000,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=100.0,
        ))
    return OHLCVData(symbol="TESTUSDT", interval="1h", candles=candles)


class AlwaysBuyStrategy(BaseStrategy):
    """Buy on candle index 1, never sell (let SL/TP or forced close handle exit)."""

    @classmethod
    def metadata(cls):
        return {
            "name": "TestAlwaysBuy",
            "description": "Test helper: buys once on candle 1",
            "category": "test",
            "parameters": {},
        }

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp,
                "BUY",
                ohlcv.candles[index].close,
                "Test buy",
            )
        return None


class AlwaysShortStrategy(BaseStrategy):
    """Short on candle index 1, never cover."""

    @classmethod
    def metadata(cls):
        return {
            "name": "TestAlwaysShort",
            "description": "Test helper: shorts once on candle 1",
            "category": "test",
            "parameters": {},
        }

    def generate_signal(self, ohlcv, index):
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp,
                "SHORT",
                ohlcv.candles[index].close,
                "Test short",
            )
        return None


class BuySellStrategy(BaseStrategy):
    """Buy on candle 1, sell on a configurable candle index."""

    @classmethod
    def metadata(cls):
        return {
            "name": "TestBuySell",
            "description": "Test helper: buys candle 1, sells on configured candle",
            "category": "test",
            "parameters": {"sell_index": {"type": "int", "default": 3, "min": 2, "max": 100}},
        }

    def generate_signal(self, ohlcv, index):
        sell_index = self.params.get("sell_index", 3)
        if index == 1:
            return TradeSignal(
                ohlcv.candles[index].timestamp,
                "BUY",
                ohlcv.candles[index].close,
                "Test buy",
            )
        if index == sell_index:
            return TradeSignal(
                ohlcv.candles[index].timestamp,
                "SELL",
                ohlcv.candles[index].close,
                "Test sell",
            )
        return None


# Engine constants matching defaults
COMMISSION = 0.001
SLIPPAGE = 0.0005


# ---------------------------------------------------------------------------
# Tests — LONG stop-loss and take-profit
# ---------------------------------------------------------------------------

class TestLongStopLossTakeProfit:
    """Tests for SL/TP on LONG positions."""

    def test_sl_triggered_on_long(self):
        """
        BUY at ~100, SL=5%.
        Candle low drops to 94 (below SL price of 95). Verify exit at SL price.
        """
        # Candle 0: neutral, Candle 1: buy at close=100
        # Candle 2: price drops sharply, low=94 triggers SL
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0 — warm-up
            (100, 102, 99, 100),     # candle 1 — BUY here (fill = 100 * 1.0005 = 100.05)
            (98, 98, 94, 95),        # candle 2 — low=94 triggers SL (SL price = 100.05*0.95 = 95.0475)
            (95, 96, 94, 95),        # candle 3 — won't be reached
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "STOP_LOSS"
        assert trade.status == "CLOSED"

        # SL price = entry * (1 - 5/100) = 100.05 * 0.95 = 95.0475
        expected_entry = 100 * (1 + SLIPPAGE)
        expected_sl_price = expected_entry * (1 - 5.0 / 100)
        assert trade.exit_price == pytest.approx(expected_sl_price, rel=1e-6)

    def test_tp_triggered_on_long(self):
        """
        BUY at ~100, TP=10%.
        Candle high reaches 111 (above TP price of 110). Verify exit at TP price.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0 — warm-up
            (100, 102, 99, 100),     # candle 1 — BUY (fill = 100.05)
            (105, 111, 104, 108),    # candle 2 — high=111 triggers TP (TP = 100.05*1.10 = 110.055)
            (108, 109, 107, 108),    # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=10.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "TAKE_PROFIT"
        assert trade.status == "CLOSED"

        expected_entry = 100 * (1 + SLIPPAGE)
        expected_tp_price = expected_entry * (1 + 10.0 / 100)
        assert trade.exit_price == pytest.approx(expected_tp_price, rel=1e-6)
        assert trade.profit_loss > 0, "TP exit should be profitable"


# ---------------------------------------------------------------------------
# Tests — SHORT stop-loss and take-profit
# ---------------------------------------------------------------------------

class TestShortStopLossTakeProfit:
    """Tests for SL/TP on SHORT positions."""

    def test_sl_triggered_on_short(self):
        """
        SHORT at ~100, SL=5%.
        Candle high rises to 106 (above SL price of ~105). Verify exit.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0 — warm-up
            (100, 101, 99, 100),     # candle 1 — SHORT (fill = 100 * 0.9995 = 99.95)
            (103, 106, 102, 105),    # candle 2 — high=106 triggers SL (SL = 99.95*1.05 = 104.9475)
            (105, 106, 104, 105),    # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysShortStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "STOP_LOSS"
        assert trade.status == "CLOSED"
        assert trade.side == "SHORT"

        expected_entry = 100 * (1 - SLIPPAGE)  # 99.95
        expected_sl_price = expected_entry * (1 + 5.0 / 100)
        assert trade.exit_price == pytest.approx(expected_sl_price, rel=1e-6)

    def test_tp_triggered_on_short(self):
        """
        SHORT at ~100, TP=10%.
        Candle low drops to 89 (below TP price of ~90). Verify exit.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0 — warm-up
            (100, 101, 99, 100),     # candle 1 — SHORT (fill = 99.95)
            (95, 96, 89, 90),        # candle 2 — low=89 triggers TP (TP = 99.95*0.90 = 89.955)
            (90, 91, 89, 90),        # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysShortStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=10.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "TAKE_PROFIT"
        assert trade.status == "CLOSED"
        assert trade.side == "SHORT"

        expected_entry = 100 * (1 - SLIPPAGE)
        expected_tp_price = expected_entry * (1 - 10.0 / 100)
        assert trade.exit_price == pytest.approx(expected_tp_price, rel=1e-6)
        assert trade.profit_loss > 0, "SHORT TP exit should be profitable"


# ---------------------------------------------------------------------------
# Tests — Edge cases and priority rules
# ---------------------------------------------------------------------------

class TestSLTPEdgeCases:
    """Edge cases: both trigger, disabled, priority over signals."""

    def test_sl_tp_disabled_when_zero(self):
        """
        Default config (sl=0, tp=0). Price swings wildly.
        No SL/TP exits; trade closes only via FORCED_CLOSE at end.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (100, 200, 10, 50),      # candle 2 — huge swing, but no SL/TP
            (50, 300, 5, 120),       # candle 3 — even wilder
            (120, 130, 110, 115),    # candle 4
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "FORCED_CLOSE"
        assert trade.status == "CLOSED"

    def test_sl_priority_over_tp(self):
        """
        Both SL and TP trigger on the same candle.
        SL should take priority (conservative: worst case first).
        BUY at ~100, SL=5%, TP=10%.
        Candle has low=94 (SL triggers) AND high=111 (TP triggers).
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY (fill = 100.05)
            (100, 111, 94, 100),     # candle 2 — SL & TP both trigger
            (100, 101, 99, 100),     # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=10.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "STOP_LOSS", "SL should take priority over TP"

        expected_entry = 100 * (1 + SLIPPAGE)
        expected_sl_price = expected_entry * (1 - 5.0 / 100)
        assert trade.exit_price == pytest.approx(expected_sl_price, rel=1e-6)

    def test_sl_before_signal(self):
        """
        Strategy emits SELL on the same candle where SL triggers.
        SL is checked BEFORE signal generation, so SL should win.
        """
        # Use BuySellStrategy that sells on candle 2
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY (fill = 100.05)
            (97, 98, 94, 96),        # candle 2 — SL triggers (low=94) AND strategy says SELL
            (96, 97, 95, 96),        # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuySellStrategy(params={"sell_index": 2})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "STOP_LOSS", "SL should be checked before signal"
        assert trade.exit_reason == "STOP_LOSS at $95"  # formatted with SL price


# ---------------------------------------------------------------------------
# Tests — PnL correctness
# ---------------------------------------------------------------------------

class TestSLTPPnL:
    """Verify exact PnL calculations for SL/TP exits."""

    def test_sl_pnl_correct(self):
        """
        BUY at 100 with 10000 capital, SL=5%.
        Verify PnL = (sl_price - entry) * qty - exit_commission.
        (Loss expected.)
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (97, 98, 94, 95),        # candle 2 — SL triggers
            (95, 96, 94, 95),        # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        capital = 10000.0
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=capital,
            stop_loss_pct=5.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]

        # Reconstruct expected values
        entry_price = 100 * (1 + SLIPPAGE)  # 100.05
        entry_commission = capital * COMMISSION  # 10.0
        available = capital - entry_commission  # 9990.0
        qty = available / entry_price

        sl_price = entry_price * (1 - 5.0 / 100)  # 95.0475
        proceeds = qty * sl_price
        exit_commission = proceeds * COMMISSION
        final_capital = proceeds - exit_commission

        # Engine calculates PnL as: final_capital - (qty * entry_price)
        expected_pnl = final_capital - (qty * entry_price)

        assert trade.profit_loss == pytest.approx(expected_pnl, rel=1e-6)
        assert trade.profit_loss < 0, "SL exit should be a loss"

        # Verify entry/exit prices
        assert trade.entry_price == pytest.approx(entry_price, rel=1e-6)
        assert trade.exit_price == pytest.approx(sl_price, rel=1e-6)

    def test_tp_pnl_correct(self):
        """
        BUY at 100 with 10000 capital, TP=10%.
        Verify PnL = (tp_price - entry) * qty - exit_commission.
        (Profit expected.)
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (105, 112, 104, 110),    # candle 2 — TP triggers (high=112 >= 110.055)
            (110, 111, 109, 110),    # candle 3
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        capital = 10000.0
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=capital,
            stop_loss_pct=0.0, take_profit_pct=10.0,
        )

        assert len(trades) == 1
        trade = trades[0]

        # Reconstruct expected values
        entry_price = 100 * (1 + SLIPPAGE)
        entry_commission = capital * COMMISSION
        available = capital - entry_commission
        qty = available / entry_price

        tp_price = entry_price * (1 + 10.0 / 100)  # 110.055
        proceeds = qty * tp_price
        exit_commission = proceeds * COMMISSION
        final_capital = proceeds - exit_commission

        expected_pnl = final_capital - (qty * entry_price)

        assert trade.profit_loss == pytest.approx(expected_pnl, rel=1e-6)
        assert trade.profit_loss > 0, "TP exit should be a profit"

        assert trade.entry_price == pytest.approx(entry_price, rel=1e-6)
        assert trade.exit_price == pytest.approx(tp_price, rel=1e-6)


# ---------------------------------------------------------------------------
# Tests — exit_type field values
# ---------------------------------------------------------------------------

class TestExitTypes:
    """Verify all four exit_type values appear correctly."""

    def test_forced_close_exit_type(self):
        """
        No SL/TP configured, position still open at end.
        Should be FORCED_CLOSE.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (101, 103, 100, 102),    # candle 2
            (102, 104, 101, 103),    # candle 3 — end of data
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "FORCED_CLOSE"
        assert "End of backtest" in trade.exit_reason

    def test_signal_close_exit_type(self):
        """
        Normal SELL signal closes position. exit_type should be SIGNAL.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (101, 103, 100, 102),    # candle 2
            (102, 104, 101, 103),    # candle 3 — SELL signal
            (103, 105, 102, 104),    # candle 4
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuySellStrategy(params={"sell_index": 3})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.exit_type == "SIGNAL"
        assert trade.status == "CLOSED"


# ---------------------------------------------------------------------------
# Tests — Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure default params (no SL/TP) match original engine behavior."""

    def test_backward_compat_no_sl_tp(self):
        """
        Run engine with default SL/TP (both 0). Behavior should be
        identical to the pre-SL/TP engine: position held until signal
        or forced close, no intermediate exits.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (100, 200, 10, 50),      # candle 2 — extreme swing (no SL/TP)
            (50, 60, 45, 55),        # candle 3
            (55, 58, 50, 52),        # candle 4 — forced close
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})

        # Run with explicit zeros
        trades_explicit, eq1, ts1 = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=0.0,
        )

        # Run with defaults (not passing SL/TP at all)
        strategy2 = AlwaysBuyStrategy(params={})
        trades_default, eq2, ts2 = engine.run(
            ohlcv, strategy2, initial_capital=10000.0,
        )

        # Both should produce identical results
        assert len(trades_explicit) == len(trades_default) == 1
        t1 = trades_explicit[0]
        t2 = trades_default[0]
        assert t1.exit_type == t2.exit_type == "FORCED_CLOSE"
        assert t1.exit_price == pytest.approx(t2.exit_price, rel=1e-9)
        assert t1.profit_loss == pytest.approx(t2.profit_loss, rel=1e-9)
        assert t1.entry_price == pytest.approx(t2.entry_price, rel=1e-9)
        assert t1.quantity == pytest.approx(t2.quantity, rel=1e-9)

        # Equity curves should match
        for a, b in zip(eq1, eq2):
            assert a == pytest.approx(b, rel=1e-9)

    def test_sl_not_triggered_when_price_stays_safe(self):
        """
        SL=5% configured but price never drops enough to trigger.
        Position should close via FORCED_CLOSE, not STOP_LOSS.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY (fill = 100.05)
            (101, 103, 98, 102),     # candle 2 — low=98 > SL=95.0475
            (102, 104, 99, 103),     # candle 3 — still safe
            (103, 105, 100, 104),    # candle 4 — forced close
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=0.0,
        )

        assert len(trades) == 1
        assert trades[0].exit_type == "FORCED_CLOSE"

    def test_tp_not_triggered_when_price_stays_below(self):
        """
        TP=10% configured but price never rises enough to trigger.
        Position should close via FORCED_CLOSE, not TAKE_PROFIT.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY (fill = 100.05)
            (101, 108, 100, 105),    # candle 2 — high=108 < TP=110.055
            (105, 109, 104, 107),    # candle 3 — high=109 < TP
            (107, 109, 105, 108),    # candle 4 — forced close
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=0.0, take_profit_pct=10.0,
        )

        assert len(trades) == 1
        assert trades[0].exit_type == "FORCED_CLOSE"
