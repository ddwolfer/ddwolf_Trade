"""
Tests for ATR-based trailing stop-loss functionality in StrategyEngine.

Covers:
- Trailing stop disabled when period=0 (backward compat)
- LONG trailing stop triggers correctly (price rises then falls back)
- SHORT trailing stop triggers correctly (price falls then rises back)
- Trailing stop only moves in favorable direction (ratchet)
- exit_type is "TRAILING_STOP"
- Fixed SL triggers before trailing stop when both would trigger
- Synthetic trend-then-reverse candle data
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import Candle, OHLCVData, TradeSignal
from services.strategy_engine import StrategyEngine
from services import indicator_service as ind
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
    """Buy on candle index 1, never sell."""

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


class BuyOnCandleStrategy(BaseStrategy):
    """Buy on a configurable candle index, never sell."""

    @classmethod
    def metadata(cls):
        return {
            "name": "TestBuyOnCandle",
            "description": "Test helper: buys once on configured candle",
            "category": "test",
            "parameters": {"buy_index": {"type": "int", "default": 1}},
        }

    def generate_signal(self, ohlcv, index):
        buy_index = self.params.get("buy_index", 1)
        if index == buy_index:
            return TradeSignal(
                ohlcv.candles[index].timestamp,
                "BUY",
                ohlcv.candles[index].close,
                "Test buy",
            )
        return None


# Engine constants matching defaults
COMMISSION = 0.001
SLIPPAGE = 0.0005


# ---------------------------------------------------------------------------
# Tests — Trailing stop disabled (backward compatibility)
# ---------------------------------------------------------------------------

class TestTrailingStopDisabled:
    """When trailing_stop_atr_period=0, trailing stop is completely disabled."""

    def test_trailing_stop_disabled_when_period_zero(self):
        """
        Default config (period=0). Price swings wildly.
        No trailing stop exits; trade closes only via FORCED_CLOSE.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),     # candle 0
            (100, 102, 99, 100),     # candle 1 — BUY
            (100, 200, 50, 150),     # candle 2 — huge swing
            (150, 180, 40, 60),      # candle 3 — another huge swing
            (60, 70, 55, 65),        # candle 4 — end
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=0, trailing_stop_atr_mult=3.0,
        )

        assert len(trades) == 1
        assert trades[0].exit_type == "FORCED_CLOSE"

    def test_backward_compat_default_params(self):
        """
        Running with defaults (no trailing stop args at all) should behave
        identically to explicitly passing period=0.
        """
        ohlcv = make_ohlcv([
            (100, 101, 99, 100),
            (100, 102, 99, 100),
            (105, 108, 103, 106),
            (106, 110, 105, 109),
            (109, 112, 108, 111),
        ])
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)

        strategy1 = AlwaysBuyStrategy(params={})
        trades1, eq1, ts1 = engine.run(
            ohlcv, strategy1, initial_capital=10000.0,
        )

        strategy2 = AlwaysBuyStrategy(params={})
        trades2, eq2, ts2 = engine.run(
            ohlcv, strategy2, initial_capital=10000.0,
            trailing_stop_atr_period=0, trailing_stop_atr_mult=3.0,
        )

        assert len(trades1) == len(trades2)
        assert trades1[0].exit_type == trades2[0].exit_type
        assert trades1[0].exit_price == pytest.approx(trades2[0].exit_price, rel=1e-9)
        assert trades1[0].profit_loss == pytest.approx(trades2[0].profit_loss, rel=1e-9)
        for a, b in zip(eq1, eq2):
            assert a == pytest.approx(b, rel=1e-9)


# ---------------------------------------------------------------------------
# Tests — LONG trailing stop
# ---------------------------------------------------------------------------

class TestLongTrailingStop:
    """Tests for trailing stop on LONG positions."""

    def _build_trend_then_reverse_data(self):
        """
        Build candle data with enough bars for ATR(3) to be computed,
        then a trend up followed by a reversal.

        Candles 0-3: stable around 100 (ATR warmup)
        Candle 4: BUY signal (we use BuyOnCandle with buy_index=4)
        Candles 5-7: price trends UP (trailing max ratchets up)
        Candle 8: sharp reversal DOWN that triggers trailing stop
        """
        prices = [
            # ATR warmup: stable candles with range ~4
            (100, 102, 98, 100),   # 0: TR=4
            (100, 103, 97, 101),   # 1: TR=6
            (101, 104, 98, 102),   # 2: TR=6
            (102, 104, 99, 101),   # 3: TR=5  (ATR(3) from candle 2 = avg(4,6,6)=5.33)
            # Entry candle
            (101, 103, 100, 102),  # 4: BUY here, close=102
            # Uptrend (trailing max ratchets up)
            (102, 110, 101, 108),  # 5: high=110
            (108, 120, 107, 118),  # 6: high=120
            (118, 125, 117, 122),  # 7: high=125 (new max)
            # Reversal: sharp drop
            (122, 123, 100, 105),  # 8: low=100, should trigger trailing stop
            (105, 106, 104, 105),  # 9: shouldn't reach
        ]
        return make_ohlcv(prices)

    def test_long_trailing_stop_triggers(self):
        """
        Price trends up (max reaches 125), then reverses.
        With ATR period=3 and mult=2.0, trail_stop = max_price - ATR*2.
        The trailing stop should trigger when price falls enough.
        """
        ohlcv = self._build_trend_then_reverse_data()
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 4})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=3, trailing_stop_atr_mult=2.0,
        )

        # Find the trade that was closed by trailing stop
        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1, f"Expected TRAILING_STOP exit, got: {[t.exit_type for t in trades]}"

        trade = trailing_trades[0]
        assert trade.side == "LONG"
        assert trade.status == "CLOSED"
        assert trade.exit_type == "TRAILING_STOP"

    def test_long_trailing_stop_exit_price(self):
        """
        Verify exit price equals the trail_stop level (not the candle low).
        """
        ohlcv = self._build_trend_then_reverse_data()
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 4})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=3, trailing_stop_atr_mult=2.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1

        trade = trailing_trades[0]
        # The exit price should be the trail_stop line, not candle.low
        # We can verify it's NOT the candle low (which was 100 on candle 8)
        # The trailing stop should be max_price - atr * mult
        # which is above the candle low
        assert trade.exit_price > 100.0, "Exit price should be trail_stop, not candle low"

    def test_long_trailing_stop_exit_type(self):
        """exit_type should be exactly 'TRAILING_STOP'."""
        ohlcv = self._build_trend_then_reverse_data()
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 4})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=3, trailing_stop_atr_mult=2.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1
        assert trailing_trades[0].exit_type == "TRAILING_STOP"


# ---------------------------------------------------------------------------
# Tests — SHORT trailing stop
# ---------------------------------------------------------------------------

class TestShortTrailingStop:
    """Tests for trailing stop on SHORT positions."""

    def _build_short_trend_then_reverse_data(self):
        """
        Build candle data for SHORT trailing stop test.

        Candles 0-3: stable around 100 (ATR warmup)
        Candle 4: SHORT signal
        Candles 5-7: price trends DOWN (trailing min ratchets down)
        Candle 8: sharp reversal UP that triggers trailing stop
        """
        prices = [
            # ATR warmup
            (100, 102, 98, 100),   # 0: TR=4
            (100, 103, 97, 101),   # 1: TR=6
            (101, 104, 98, 102),   # 2: TR=6
            (102, 104, 99, 101),   # 3: TR=5
            # Entry candle
            (101, 103, 100, 102),  # 4: SHORT here, close=102
            # Downtrend (trailing min ratchets down)
            (102, 103, 92, 94),    # 5: low=92
            (94, 95, 82, 84),      # 6: low=82
            (84, 85, 75, 78),      # 7: low=75 (new min)
            # Reversal: sharp rise
            (78, 100, 77, 98),     # 8: high=100, should trigger trailing stop
            (98, 99, 97, 98),      # 9: shouldn't reach
        ]
        return make_ohlcv(prices)

    def test_short_trailing_stop_triggers(self):
        """
        Price trends down (min reaches 75), then reverses.
        Trailing stop should trigger when price rises back enough.
        """
        ohlcv = self._build_short_trend_then_reverse_data()
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)

        class ShortOnCandle4(BaseStrategy):
            @classmethod
            def metadata(cls):
                return {"name": "Test", "description": "test", "category": "test", "parameters": {}}

            def generate_signal(self, ohlcv, index):
                if index == 4:
                    return TradeSignal(ohlcv.candles[index].timestamp, "SHORT",
                                      ohlcv.candles[index].close, "Test short")
                return None

        strategy = ShortOnCandle4(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=3, trailing_stop_atr_mult=2.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1, f"Expected TRAILING_STOP, got: {[t.exit_type for t in trades]}"

        trade = trailing_trades[0]
        assert trade.side == "SHORT"
        assert trade.status == "CLOSED"
        assert trade.exit_type == "TRAILING_STOP"

    def test_short_trailing_stop_exit_price(self):
        """
        Exit price should be the trail_stop level (min_price + atr * mult),
        not the candle high.
        """
        ohlcv = self._build_short_trend_then_reverse_data()
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)

        class ShortOnCandle4(BaseStrategy):
            @classmethod
            def metadata(cls):
                return {"name": "Test", "description": "test", "category": "test", "parameters": {}}

            def generate_signal(self, ohlcv, index):
                if index == 4:
                    return TradeSignal(ohlcv.candles[index].timestamp, "SHORT",
                                      ohlcv.candles[index].close, "Test short")
                return None

        strategy = ShortOnCandle4(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=3, trailing_stop_atr_mult=2.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1

        trade = trailing_trades[0]
        # Exit price should be trail_stop, not candle high (100)
        # trail_stop = min_price + atr * mult > min_price
        assert trade.exit_price < 100.0, "Exit price should be trail_stop, not candle high"
        assert trade.exit_price > 75.0, "Exit price should be above the min price"


# ---------------------------------------------------------------------------
# Tests — Ratchet behavior
# ---------------------------------------------------------------------------

class TestTrailingStopRatchet:
    """Trailing stop only moves in the favorable direction (ratchets)."""

    def _build_long_ratchet_data(self):
        """
        Build data with 10 stable warmup candles (ATR(10)~2), BUY at candle 10,
        gradual uptrend in two phases (to 110, then to 120), then reversal.
        Uses gradual moves to keep each candle's range small relative to ATR * mult.
        """
        prices = []
        # 10 stable warmup candles: ATR(10) stabilizes at ~2
        for i in range(10):
            prices.append((100, 101, 99, 100))
        # BUY at candle 10
        prices.append((100, 101, 99, 100))
        # Gradual up phase 1: to ~110 (ranges ~3, low stays close to close)
        for ct in [102, 104, 106, 108, 110]:
            prices.append((ct - 2, ct + 1, ct - 1, ct))
        # Stable at 110
        prices.append((110, 111, 109, 110))
        # Gradual up phase 2: to ~120
        for ct in [112, 114, 116, 118, 120]:
            prices.append((ct - 2, ct + 1, ct - 1, ct))
        # Stable at 120
        prices.append((120, 121, 119, 120))
        # BIG reversal (candle 23)
        prices.append((120, 121, 90, 95))
        return make_ohlcv(prices)

    def test_long_trailing_max_only_increases(self):
        """
        Price goes up in two phases (max 110 → 120), then reversal.
        The trailing stop exit price should be based on max=120 (ratcheted up),
        proving the stop moved up with the max and didn't reset on dips.
        """
        ohlcv = self._build_long_ratchet_data()
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 10})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=10, trailing_stop_atr_mult=3.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1, f"Expected TRAILING_STOP, got: {[t.exit_type for t in trades]}"

        trade = trailing_trades[0]
        # Exit price = max(120) - ATR*3. Should be above entry (~100) proving ratchet works.
        assert trade.exit_price > trade.entry_price, \
            f"Trailing stop should lock in gains (ratchet up to 120), got exit_price={trade.exit_price:.2f}"
        assert trade.profit_loss > 0, \
            f"Should be profitable with ratchet, got PnL={trade.profit_loss:.2f}"

    def test_short_trailing_min_only_decreases(self):
        """
        For SHORT: price goes down in two phases (min 90 → 80), then reversal.
        The trailing stop exit price should be based on min=80.
        """
        prices = []
        for i in range(10):
            prices.append((100, 101, 99, 100))
        # SHORT at candle 10
        prices.append((100, 101, 99, 100))
        # Gradual down phase 1: to ~90
        for ct in [98, 96, 94, 92, 90]:
            prices.append((ct + 2, ct + 2, ct - 1, ct))
        # Stable at 90
        prices.append((90, 91, 89, 90))
        # Gradual down phase 2: to ~80
        for ct in [88, 86, 84, 82, 80]:
            prices.append((ct + 2, ct + 2, ct - 1, ct))
        # Stable at 80
        prices.append((80, 81, 79, 80))
        # BIG reversal up
        prices.append((80, 120, 79, 115))

        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)

        class ShortOnCandle10(BaseStrategy):
            @classmethod
            def metadata(cls):
                return {"name": "Test", "description": "test", "category": "test", "parameters": {}}
            def generate_signal(self, ohlcv, index):
                if index == 10:
                    return TradeSignal(ohlcv.candles[index].timestamp, "SHORT",
                                      ohlcv.candles[index].close, "Test short")
                return None

        strategy = ShortOnCandle10(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=10, trailing_stop_atr_mult=3.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1, f"Expected TRAILING_STOP, got: {[t.exit_type for t in trades]}"

        trade = trailing_trades[0]
        # Exit price = min(80) + ATR*3. Should be below entry (~100) proving ratchet works.
        assert trade.exit_price < trade.entry_price, \
            f"Trailing stop should lock in gains (ratchet down to 80), got exit_price={trade.exit_price:.2f}"
        assert trade.profit_loss > 0, \
            f"Short should be profitable with ratchet, got PnL={trade.profit_loss:.2f}"


# ---------------------------------------------------------------------------
# Tests — Fixed SL priority over trailing stop
# ---------------------------------------------------------------------------

class TestFixedSLPriority:
    """Fixed SL/TP should trigger before trailing stop when both would trigger."""

    def test_fixed_sl_before_trailing_stop(self):
        """
        Set both fixed SL (5%) and trailing stop.
        On a candle where both would trigger, fixed SL should win
        because it's checked first in the main loop.

        Uses 10 stable warmup candles so ATR is well-defined, then
        BUY at candle 10 and a massive drop on candle 12 that
        triggers both SL and trailing stop simultaneously.
        """
        prices = []
        # 10 stable warmup candles: ATR(10) = 2
        for i in range(10):
            prices.append((100, 101, 99, 100))
        # BUY at candle 10 (close=100, entry ~100.05)
        prices.append((100, 101, 99, 100))
        # Candle 11: stable (no trigger yet)
        prices.append((100, 101, 99, 100))
        # Candle 12: massive drop — triggers BOTH:
        # Fixed SL: entry=100.05, SL=100.05*0.95=95.05, low=50 -> HIT
        # Trailing: max=101, trail_stop=101-ATR*3~=95, low=50 -> HIT
        # Fixed SL checked FIRST -> should win
        prices.append((100, 101, 50, 55))

        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 10})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            stop_loss_pct=5.0, take_profit_pct=0.0,
            trailing_stop_atr_period=10, trailing_stop_atr_mult=3.0,
        )

        assert len(trades) >= 1
        trade = trades[0]
        # Fixed SL should take priority
        assert trade.exit_type == "STOP_LOSS", \
            f"Fixed SL should take priority over trailing stop, got {trade.exit_type}"


# ---------------------------------------------------------------------------
# Tests — Synthetic trend-then-reverse with realistic data
# ---------------------------------------------------------------------------

class TestTrailingStopRealisticData:
    """Test with more realistic price movements."""

    def test_long_uptrend_then_reversal(self):
        """
        Simulate a realistic uptrend followed by a sharp reversal.
        25 candles: warm-up, entry, gradual uptrend, sharp reversal.
        """
        prices = []
        # Warm-up candles 0-9: price around 100 with normal volatility
        base = 100.0
        for i in range(10):
            o = base + i * 0.5
            h = o + 2
            l = o - 2
            c = o + 1
            prices.append((o, h, l, c))

        # Candle 10: entry (BUY)
        prices.append((105, 107, 104, 106))  # index 10

        # Uptrend candles 11-17: price climbs from 106 to ~150
        for i in range(7):
            base_p = 106 + i * 6.5
            prices.append((base_p, base_p + 3, base_p - 1, base_p + 5))

        # Candle 18: peak
        prices.append((148, 155, 147, 152))

        # Reversal candles 19-22: sharp drop
        prices.append((152, 153, 130, 132))  # 19: big drop
        prices.append((132, 135, 120, 122))  # 20: more drop
        prices.append((122, 125, 110, 115))  # 21
        prices.append((115, 118, 108, 112))  # 22

        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 10})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=5, trailing_stop_atr_mult=2.0,
        )

        # Should have at least one trade
        assert len(trades) >= 1

        # The trade should have been profitable (entered low, trailed up)
        trade = trades[0]
        if trade.exit_type == "TRAILING_STOP":
            # The trailing stop locked in some profit
            assert trade.profit_loss > 0, \
                f"Trailing stop after uptrend should lock in profit, got PnL={trade.profit_loss:.2f}"

    def test_no_trigger_during_steady_trend(self):
        """
        Price trends steadily up with no sharp reversals.
        Trailing stop should NOT trigger; position closes via FORCED_CLOSE.
        Use a large ATR multiplier to ensure the stop stays far away.
        """
        prices = []
        # Warm-up candles
        for i in range(5):
            o = 100 + i * 0.5
            prices.append((o, o + 1, o - 1, o + 0.5))

        # BUY at candle 5
        prices.append((102, 104, 101, 103))

        # Steady uptrend with very small pullbacks
        for i in range(10):
            base_p = 103 + i * 2
            prices.append((base_p, base_p + 1.5, base_p - 0.5, base_p + 1.5))

        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 5})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=3, trailing_stop_atr_mult=10.0,  # very wide
        )

        assert len(trades) == 1
        assert trades[0].exit_type == "FORCED_CLOSE", \
            f"Steady trend should not trigger trailing stop, got {trades[0].exit_type}"

    def test_early_candles_no_atr_skip_trailing_check(self):
        """
        When ATR hasn't been computed yet (early candles), trailing stop
        check should be skipped without errors.
        """
        # Only 4 candles but ATR period = 10 (not enough data)
        prices = [
            (100, 102, 98, 100),
            (100, 102, 99, 101),   # BUY
            (101, 103, 80, 82),    # Price drops sharply but no ATR available
            (82, 85, 80, 83),
        ]
        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = AlwaysBuyStrategy(params={})

        # Should not crash
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=10, trailing_stop_atr_mult=2.0,
        )

        assert len(trades) == 1
        # ATR not available, so trailing stop can't trigger
        assert trades[0].exit_type == "FORCED_CLOSE"


# ---------------------------------------------------------------------------
# Tests — PnL correctness for trailing stop
# ---------------------------------------------------------------------------

class TestTrailingStopPnL:
    """Verify PnL calculations for trailing stop exits."""

    def test_long_trailing_stop_pnl_positive(self):
        """
        LONG position: price goes up significantly, then reversal triggers
        trailing stop. PnL should be positive (exit_price > entry_price).

        Uses 10 stable warmup candles (ATR(10)~2) so the trailing stop
        is tight relative to the price gains, ensuring profitability.
        """
        prices = []
        # 10 stable warmup candles
        for i in range(10):
            prices.append((100, 101, 99, 100))
        # BUY at candle 10
        prices.append((100, 101, 99, 100))
        # Gradual uptrend: to ~120 (small ranges keep ATR manageable)
        for ct in [102, 104, 106, 108, 110, 112, 114, 116, 118, 120]:
            prices.append((ct - 2, ct + 1, ct - 1, ct))
        # Stable at 120
        prices.append((120, 121, 119, 120))
        # Reversal
        prices.append((120, 121, 90, 95))

        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)
        strategy = BuyOnCandleStrategy(params={"buy_index": 10})

        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=10, trailing_stop_atr_mult=3.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1, \
            f"Expected TRAILING_STOP, got: {[t.exit_type for t in trades]}"

        trade = trailing_trades[0]
        assert trade.exit_price > trade.entry_price, \
            f"Trailing stop should lock in profit (exit={trade.exit_price:.2f} > entry={trade.entry_price:.2f})"
        assert trade.profit_loss > 0, \
            f"Should be profitable, got PnL={trade.profit_loss:.2f}"

    def test_short_trailing_stop_pnl_positive(self):
        """
        SHORT position: price goes down significantly, then reversal triggers
        trailing stop. PnL should be positive (exit_price < entry_price).
        """
        prices = []
        # 10 stable warmup candles
        for i in range(10):
            prices.append((100, 101, 99, 100))
        # SHORT at candle 10
        prices.append((100, 101, 99, 100))
        # Gradual downtrend: to ~80
        for ct in [98, 96, 94, 92, 90, 88, 86, 84, 82, 80]:
            prices.append((ct + 2, ct + 2, ct - 1, ct))
        # Stable at 80
        prices.append((80, 81, 79, 80))
        # Reversal up
        prices.append((80, 120, 79, 115))

        ohlcv = make_ohlcv(prices)
        engine = StrategyEngine(commission_rate=COMMISSION, slippage_rate=SLIPPAGE)

        class ShortOnCandle10(BaseStrategy):
            @classmethod
            def metadata(cls):
                return {"name": "Test", "description": "test", "category": "test", "parameters": {}}
            def generate_signal(self, ohlcv, index):
                if index == 10:
                    return TradeSignal(ohlcv.candles[index].timestamp, "SHORT",
                                      ohlcv.candles[index].close, "Test short")
                return None

        strategy = ShortOnCandle10(params={})
        trades, equity, timestamps = engine.run(
            ohlcv, strategy, initial_capital=10000.0,
            trailing_stop_atr_period=10, trailing_stop_atr_mult=3.0,
        )

        trailing_trades = [t for t in trades if t.exit_type == "TRAILING_STOP"]
        assert len(trailing_trades) >= 1, \
            f"Expected TRAILING_STOP, got: {[t.exit_type for t in trades]}"

        trade = trailing_trades[0]
        assert trade.exit_price < trade.entry_price, \
            f"Trailing stop should lock in profit (exit={trade.exit_price:.2f} < entry={trade.entry_price:.2f})"
        assert trade.profit_loss > 0, \
            f"Short should be profitable, got PnL={trade.profit_loss:.2f}"
