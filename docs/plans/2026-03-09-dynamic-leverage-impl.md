# Dynamic Leverage System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add AI-powered dynamic leverage to the backtesting engine with Binance-style liquidation and funding rate simulation.

**Architecture:** Independent `LeverageAssessor` service scores market conditions (ATR volatility, ADX trend strength, EMA alignment) to pick leverage 1x–10x per trade. Engine gains liquidation checks, funding deductions, and margin-based PnL. Strategies can optionally override leverage via `TradeSignal.leverage`.

**Tech Stack:** Python 3.10+, numpy, pure stdlib HTTP server.

**Parallelization:** Tasks 1–3 are independent foundations. Task 4 depends on 1+2. Tasks 5–6 depend on 4. Task 7 depends on 5+6. Tasks are marked with dependency tags.

---

### Task 1: Data Model Changes

**Depends on:** nothing
**Files:**
- Modify: `backend/models/__init__.py`
- Test: `backend/tests/test_models_leverage.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_models_leverage.py`:

```python
"""Tests for leverage-related model changes."""
import pytest
from models import BacktestConfig, Trade, TradeSignal


class TestBacktestConfigLeverage:
    def test_default_max_leverage(self):
        config = BacktestConfig()
        assert config.max_leverage == 10.0

    def test_default_leverage_mode(self):
        config = BacktestConfig()
        assert config.leverage_mode == "dynamic"

    def test_default_fixed_leverage(self):
        config = BacktestConfig()
        assert config.fixed_leverage == 1.0

    def test_default_funding_rate(self):
        config = BacktestConfig()
        assert config.funding_rate == 0.0001

    def test_default_maintenance_margin_rate(self):
        config = BacktestConfig()
        assert config.maintenance_margin_rate == 0.005

    def test_custom_leverage_config(self):
        config = BacktestConfig(
            max_leverage=5.0,
            leverage_mode="fixed",
            fixed_leverage=3.0,
            funding_rate=0.0002,
            maintenance_margin_rate=0.01,
        )
        assert config.max_leverage == 5.0
        assert config.leverage_mode == "fixed"
        assert config.fixed_leverage == 3.0
        assert config.funding_rate == 0.0002
        assert config.maintenance_margin_rate == 0.01


class TestTradeLeverage:
    def test_default_leverage_fields(self):
        trade = Trade(entry_time=1000, entry_price=50000.0)
        assert trade.leverage == 1.0
        assert trade.margin_used == 0.0
        assert trade.liquidation_price == 0.0
        assert trade.funding_paid == 0.0

    def test_custom_leverage_fields(self):
        trade = Trade(
            entry_time=1000, entry_price=50000.0,
            leverage=5.0, margin_used=2000.0,
            liquidation_price=40000.0, funding_paid=10.5,
        )
        assert trade.leverage == 5.0
        assert trade.margin_used == 2000.0
        assert trade.liquidation_price == 40000.0
        assert trade.funding_paid == 10.5

    def test_to_dict_includes_leverage(self):
        trade = Trade(entry_time=1000000000000, entry_price=50000.0, leverage=3.0)
        d = trade.to_dict()
        assert d["leverage"] == 3.0
        assert "margin_used" in d
        assert "liquidation_price" in d
        assert "funding_paid" in d


class TestTradeSignalLeverage:
    def test_default_leverage_none(self):
        sig = TradeSignal(timestamp=1000, signal_type="BUY", price=50000.0)
        assert sig.leverage is None

    def test_custom_leverage(self):
        sig = TradeSignal(timestamp=1000, signal_type="BUY", price=50000.0, leverage=5.0)
        assert sig.leverage == 5.0
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_models_leverage.py -v`
Expected: Multiple FAIL — fields don't exist yet.

**Step 3: Add leverage fields to models**

In `backend/models/__init__.py`, make these changes:

1. Add to `TradeSignal` (after `reason: str = ""`):
```python
    leverage: Optional[float] = None  # Strategy-suggested leverage (None = use Assessor)
```

2. Add to `Trade` (after `exit_reason: str = ""`):
```python
    leverage: float = 1.0            # Actual leverage used
    margin_used: float = 0.0         # Margin amount locked
    liquidation_price: float = 0.0   # Forced liquidation price
    funding_paid: float = 0.0        # Cumulative funding paid
```

3. Add to `BacktestConfig` (after `trailing_stop_atr_mult: float = 3.0`):
```python
    # Leverage / contract settings
    max_leverage: float = 10.0              # Hard cap (1.0~20.0)
    leverage_mode: str = "dynamic"          # "dynamic"=AI assess, "fixed"=constant
    fixed_leverage: float = 1.0             # Used when leverage_mode="fixed"
    funding_rate: float = 0.0001            # Per 8h (0.01%), ~10.95% annualized
    maintenance_margin_rate: float = 0.005  # 0.5% (Binance default)
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_models_leverage.py -v`
Expected: All PASS.

**Step 5: Run ALL existing tests for backward compat**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 162 existing tests still pass.

**Step 6: Commit**

```bash
git add backend/models/__init__.py backend/tests/test_models_leverage.py
git commit -m "feat: add leverage fields to BacktestConfig, Trade, TradeSignal"
```

---

### Task 2: ADX Indicator

**Depends on:** nothing
**Files:**
- Modify: `backend/services/indicator_service.py`
- Test: `backend/tests/test_adx.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_adx.py`:

```python
"""Tests for ADX (Average Directional Index) indicator."""
import pytest
from services import indicator_service as ind


class TestADX:
    def test_returns_correct_length(self):
        """ADX output list length equals input length."""
        highs = [10 + i * 0.5 for i in range(30)]
        lows = [9 + i * 0.5 for i in range(30)]
        closes = [9.5 + i * 0.5 for i in range(30)]
        result = ind.adx(highs, lows, closes, period=14)
        assert len(result) == 30

    def test_early_values_are_none(self):
        """ADX needs 2*period-1 candles to produce first value."""
        highs = [10 + i * 0.5 for i in range(30)]
        lows = [9 + i * 0.5 for i in range(30)]
        closes = [9.5 + i * 0.5 for i in range(30)]
        result = ind.adx(highs, lows, closes, period=14)
        # First valid ADX at index 2*period-2 = 26
        for i in range(2 * 14 - 2):
            assert result[i] is None

    def test_strong_uptrend_high_adx(self):
        """Steady uptrend should produce ADX > 25."""
        n = 60
        highs = [100 + i * 2.0 for i in range(n)]
        lows = [99 + i * 2.0 for i in range(n)]
        closes = [99.5 + i * 2.0 for i in range(n)]
        result = ind.adx(highs, lows, closes, period=14)
        # Last value should indicate strong trend
        last = result[-1]
        assert last is not None
        assert last > 25, f"ADX={last}, expected > 25 for strong uptrend"

    def test_choppy_market_low_adx(self):
        """Alternating up/down should produce low ADX."""
        n = 60
        highs, lows, closes = [], [], []
        for i in range(n):
            if i % 2 == 0:
                highs.append(101)
                lows.append(99)
                closes.append(100.5)
            else:
                highs.append(101)
                lows.append(99)
                closes.append(99.5)
        result = ind.adx(highs, lows, closes, period=14)
        last = result[-1]
        assert last is not None
        assert last < 25, f"ADX={last}, expected < 25 for choppy market"

    def test_adx_range_0_to_100(self):
        """ADX values should be between 0 and 100."""
        n = 60
        highs = [100 + i * 1.0 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [99.5 + i * 1.0 for i in range(n)]
        result = ind.adx(highs, lows, closes, period=14)
        for v in result:
            if v is not None:
                assert 0 <= v <= 100, f"ADX={v} out of range"

    def test_insufficient_data(self):
        """Too few candles returns all None."""
        result = ind.adx([10, 11], [9, 10], [9.5, 10.5], period=14)
        assert all(v is None for v in result)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_adx.py -v`
Expected: FAIL — `ind.adx` only has ATR, not ADX.

**Step 3: Implement ADX**

Add to `backend/services/indicator_service.py` (after the `atr` function):

```python
def adx(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[Optional[float]]:
    """
    Average Directional Index — measures trend strength (0–100).
    ADX > 25 indicates a strong trend, < 20 indicates weak/no trend.
    """
    n = len(closes)
    result = [None] * n
    if n < 2 * period:
        return result

    # Step 1: Calculate +DM, -DM, TR
    plus_dm = []
    minus_dm = []
    true_ranges = []

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        plus_dm.append(pdm)
        minus_dm.append(mdm)

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    # Step 2: Smooth with Wilder's method (initial = sum of first `period` values)
    if len(true_ranges) < period:
        return result

    smooth_plus_dm = float(sum(plus_dm[:period]))
    smooth_minus_dm = float(sum(minus_dm[:period]))
    smooth_tr = float(sum(true_ranges[:period]))

    # Step 3: Calculate +DI, -DI, DX series
    dx_values = []

    for i in range(period, len(true_ranges)):
        smooth_plus_dm = smooth_plus_dm - (smooth_plus_dm / period) + plus_dm[i]
        smooth_minus_dm = smooth_minus_dm - (smooth_minus_dm / period) + minus_dm[i]
        smooth_tr = smooth_tr - (smooth_tr / period) + true_ranges[i]

        if smooth_tr == 0:
            dx_values.append(0.0)
            continue

        plus_di = (smooth_plus_dm / smooth_tr) * 100
        minus_di = (smooth_minus_dm / smooth_tr) * 100

        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(abs(plus_di - minus_di) / di_sum * 100)

    # Step 4: ADX = smoothed average of DX
    if len(dx_values) < period:
        return result

    adx_val = float(np.mean(dx_values[:period]))
    # First ADX at index: 1 (for diff) + period (for smoothing) + period-1 (for ADX smoothing) = 2*period
    first_idx = 2 * period - 1
    if first_idx < n:
        result[first_idx] = adx_val

    for i in range(period, len(dx_values)):
        adx_val = (adx_val * (period - 1) + dx_values[i]) / period
        idx = i + period  # offset: 1(diff) + period(smooth start) + i
        if idx < n:
            result[idx] = adx_val

    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_adx.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/services/indicator_service.py backend/tests/test_adx.py
git commit -m "feat: add ADX (Average Directional Index) indicator"
```

---

### Task 3: LeverageAssessor Service

**Depends on:** Task 1 (models), Task 2 (ADX)
**Files:**
- Create: `backend/services/leverage_service.py`
- Test: `backend/tests/test_leverage_assessor.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_leverage_assessor.py`:

```python
"""Tests for LeverageAssessor — AI dynamic leverage evaluation."""
import pytest
from models import Candle, OHLCVData, TradeSignal
from services.leverage_service import LeverageAssessor


def _make_trending_ohlcv(n=60, start=100, step=2.0, vol=1.0):
    """Create steady uptrend OHLCV data."""
    candles = []
    for i in range(n):
        price = start + i * step
        candles.append(Candle(
            timestamp=1000 * i,
            open=price - vol * 0.3,
            high=price + vol,
            low=price - vol,
            close=price + vol * 0.3,
            volume=1000,
        ))
    return OHLCVData(symbol="BTCUSDT", interval="4h", candles=candles)


def _make_choppy_ohlcv(n=60, base=100, swing=5.0):
    """Create choppy sideways OHLCV data."""
    candles = []
    for i in range(n):
        if i % 2 == 0:
            c = base + swing * 0.3
        else:
            c = base - swing * 0.3
        candles.append(Candle(
            timestamp=1000 * i,
            open=base,
            high=base + swing,
            low=base - swing,
            close=c,
            volume=1000,
        ))
    return OHLCVData(symbol="BTCUSDT", interval="4h", candles=candles)


class TestLeverageAssessorBounds:
    def test_returns_float(self):
        ohlcv = _make_trending_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=10.0)
        assert isinstance(result, float)

    def test_minimum_leverage_is_one(self):
        ohlcv = _make_choppy_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=10.0)
        assert result >= 1.0

    def test_maximum_leverage_respected(self):
        ohlcv = _make_trending_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=5.0)
        assert result <= 5.0

    def test_leverage_is_integer_or_half(self):
        """Leverage should be rounded to nearest 0.5 for practical use."""
        ohlcv = _make_trending_ohlcv()
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, len(ohlcv.candles) - 1, "LONG", max_leverage=10.0)
        assert result * 2 == int(result * 2), f"Leverage {result} not rounded to 0.5"


class TestLeverageAssessorScoring:
    def test_strong_trend_higher_than_choppy(self):
        """Strong trend should get higher leverage than choppy market."""
        assessor = LeverageAssessor()
        trending = _make_trending_ohlcv(n=80, step=3.0)
        choppy = _make_choppy_ohlcv(n=80, swing=8.0)
        lev_trend = assessor.assess(trending, len(trending.candles) - 1, "LONG", 10.0)
        lev_choppy = assessor.assess(choppy, len(choppy.candles) - 1, "LONG", 10.0)
        assert lev_trend > lev_choppy, f"Trend {lev_trend} should > choppy {lev_choppy}"

    def test_insufficient_data_returns_one(self):
        """Not enough data for indicators → safest leverage (1x)."""
        candles = [Candle(timestamp=i * 1000, open=100, high=101, low=99,
                          close=100, volume=1000) for i in range(5)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        assessor = LeverageAssessor()
        result = assessor.assess(ohlcv, 4, "LONG", 10.0)
        assert result == 1.0


class TestLeverageOverride:
    def test_signal_leverage_used_when_set(self):
        """When TradeSignal has leverage, Assessor is bypassed."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=5.0,
            assessed_leverage=8.0,
            leverage_mode="dynamic",
            fixed_leverage=1.0,
            max_leverage=10.0,
        )
        assert result == 5.0

    def test_signal_leverage_capped_at_max(self):
        """Signal leverage exceeding max gets capped."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=15.0,
            assessed_leverage=8.0,
            leverage_mode="dynamic",
            fixed_leverage=1.0,
            max_leverage=10.0,
        )
        assert result == 10.0

    def test_fixed_mode_uses_fixed_leverage(self):
        """leverage_mode='fixed' uses fixed_leverage value."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=None,
            assessed_leverage=8.0,
            leverage_mode="fixed",
            fixed_leverage=3.0,
            max_leverage=10.0,
        )
        assert result == 3.0

    def test_dynamic_mode_uses_assessed(self):
        """leverage_mode='dynamic' with no signal override uses assessed value."""
        assessor = LeverageAssessor()
        result = assessor.resolve_leverage(
            signal_leverage=None,
            assessed_leverage=7.5,
            leverage_mode="dynamic",
            fixed_leverage=1.0,
            max_leverage=10.0,
        )
        assert result == 7.5
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_leverage_assessor.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement LeverageAssessor**

Create `backend/services/leverage_service.py`:

```python
"""
Leverage Assessment Service — AI-powered dynamic leverage evaluation.

Evaluates market conditions before each trade to determine optimal leverage:
- Volatility (ATR/close): low vol → safer for high leverage (40% weight)
- Trend strength (ADX): strong trend → higher leverage (35% weight)
- EMA alignment: triple alignment → high score (25% weight)

Returns leverage rounded to nearest 0.5x for practical use.
"""
import math
from typing import Optional
from models import OHLCVData
from services import indicator_service as ind


class LeverageAssessor:
    """Evaluates market conditions to suggest leverage multiplier."""

    def assess(self, ohlcv: OHLCVData, index: int, side: str,
               max_leverage: float = 10.0) -> float:
        """
        Assess optimal leverage for a trade at the given candle index.

        Args:
            ohlcv: OHLCV data
            index: Current candle index
            side: "LONG" or "SHORT"
            max_leverage: Hard cap on leverage

        Returns:
            Suggested leverage (1.0 ~ max_leverage), rounded to 0.5
        """
        if index < 50:
            return 1.0  # Not enough data for reliable assessment

        closes = ohlcv.closes()
        highs = ohlcv.highs()
        lows = ohlcv.lows()

        vol_score = self._volatility_score(highs, lows, closes, index)
        adx_score = self._adx_score(highs, lows, closes, index)
        ema_score = self._ema_alignment_score(closes, index, side)

        composite = vol_score * 0.4 + adx_score * 0.35 + ema_score * 0.25
        composite = max(0.0, min(1.0, composite))

        raw_leverage = 1.0 + (max_leverage - 1.0) * composite
        # Round to nearest 0.5
        leverage = round(raw_leverage * 2) / 2
        return max(1.0, min(max_leverage, leverage))

    def resolve_leverage(
        self,
        signal_leverage: Optional[float],
        assessed_leverage: float,
        leverage_mode: str,
        fixed_leverage: float,
        max_leverage: float,
    ) -> float:
        """
        Resolve final leverage considering signal override and mode.

        Priority:
        1. TradeSignal.leverage (if set) — capped at max_leverage
        2. leverage_mode="fixed" → fixed_leverage
        3. leverage_mode="dynamic" → assessed_leverage
        """
        if signal_leverage is not None:
            return min(signal_leverage, max_leverage)
        if leverage_mode == "fixed":
            return min(fixed_leverage, max_leverage)
        return min(assessed_leverage, max_leverage)

    def _volatility_score(self, highs, lows, closes, index, period=14):
        """Low volatility = high score (safe for leverage)."""
        atr_values = ind.atr(highs, lows, closes, period)
        atr_val = atr_values[index] if index < len(atr_values) else None
        if atr_val is None or closes[index] == 0:
            return 0.0

        # ATR as % of price
        atr_pct = atr_val / closes[index]
        # Typical crypto ATR%: 1%~8%. Map to score:
        # < 1% → 1.0 (very low vol), > 6% → 0.0 (very high vol)
        score = 1.0 - (atr_pct - 0.01) / 0.05
        return max(0.0, min(1.0, score))

    def _adx_score(self, highs, lows, closes, index, period=14):
        """Strong trend (high ADX) = high score."""
        adx_values = ind.adx(highs, lows, closes, period)
        adx_val = adx_values[index] if index < len(adx_values) else None
        if adx_val is None:
            return 0.0

        # ADX < 15 → 0.0 (no trend), > 40 → 1.0 (very strong trend)
        score = (adx_val - 15) / 25
        return max(0.0, min(1.0, score))

    def _ema_alignment_score(self, closes, index, side, fast=20, mid=50, slow=200):
        """Triple EMA alignment with trade direction = high score."""
        ema_fast = ind.ema(closes, fast)
        ema_mid = ind.ema(closes, mid)
        ema_slow = ind.ema(closes, slow)

        f = ema_fast[index] if index < len(ema_fast) else None
        m = ema_mid[index] if index < len(ema_mid) else None
        s = ema_slow[index] if index < len(ema_slow) else None

        if f is None or m is None or s is None:
            return 0.0

        if side == "LONG":
            # Perfect: f > m > s
            if f > m > s:
                return 1.0
            elif f > m or f > s:
                return 0.5
            else:
                return 0.1  # EMAs against LONG direction
        else:  # SHORT
            # Perfect: f < m < s
            if f < m < s:
                return 1.0
            elif f < m or f < s:
                return 0.5
            else:
                return 0.1  # EMAs against SHORT direction
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_leverage_assessor.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/services/leverage_service.py backend/tests/test_leverage_assessor.py
git commit -m "feat: add LeverageAssessor service with three-factor scoring"
```

---

### Task 4: Engine — Liquidation Check

**Depends on:** Task 1 (models)
**Files:**
- Modify: `backend/services/strategy_engine.py`
- Test: `backend/tests/test_liquidation.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_liquidation.py`:

```python
"""Tests for Binance-style liquidation mechanics."""
import pytest
from models import Candle, OHLCVData, Trade, TradeSignal
from services.strategy_engine import StrategyEngine
from strategies.base_strategy import BaseStrategy


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
        timestamp=i * 3600000,
        open=price, high=high or price + 10,
        low=low or price - 10, close=price, volume=1000,
    )


class TestLiquidationPrice:
    def test_check_liquidation_returns_none_when_safe(self):
        """No liquidation when price is far from liq price."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="LONG",
            leverage=5.0, liquidation_price=80.0,
        )
        candle = _make_candle(1, 95, low=85)
        result = engine._check_liquidation(position, candle)
        assert result is None

    def test_long_liquidation_triggered(self):
        """LONG liquidation triggers when candle.low <= liquidation_price."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="LONG",
            leverage=5.0, liquidation_price=80.5,
        )
        candle = _make_candle(1, 82, low=79)  # low breaches 80.5
        result = engine._check_liquidation(position, candle)
        assert result == 80.5

    def test_short_liquidation_triggered(self):
        """SHORT liquidation triggers when candle.high >= liquidation_price."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, side="SHORT",
            leverage=5.0, liquidation_price=120.0,
        )
        candle = _make_candle(1, 118, high=121)  # high breaches 120
        result = engine._check_liquidation(position, candle)
        assert result == 120.0


class TestLiquidationInEngine:
    def test_long_liquidation_zeroes_capital(self):
        """After liquidation, capital goes to 0 and equity curve reflects it."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),  # Buy here at 100
            _make_candle(3, 95),   # Dropping
            _make_candle(4, 70, low=60),  # Crash — should trigger liquidation for 5x
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, AlwaysBuyStrategy({}), initial_capital=1000,
            max_leverage=5.0, leverage_mode="fixed", fixed_leverage=5.0,
            maintenance_margin_rate=0.005,
        )
        # Should have exactly 1 trade, closed by liquidation
        assert len(trades) == 1
        assert trades[0].exit_type == "LIQUIDATION"
        # After liquidation, capital = 0
        assert equity[-1] == 0.0

    def test_short_liquidation_zeroes_capital(self):
        """SHORT liquidation when price surges."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),  # Short here
            _make_candle(3, 105),
            _make_candle(4, 140, high=145),  # Surge — liquidation for 5x SHORT
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

    def test_liquidation_priority_over_sl(self):
        """Liquidation fires before SL if price gaps through both."""
        candles = [
            _make_candle(0, 100),
            _make_candle(1, 100),
            _make_candle(2, 100),  # Buy at 100 with 5x
            _make_candle(3, 60, low=55),  # Huge gap down — hits both SL and liq
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, AlwaysBuyStrategy({}), initial_capital=1000,
            stop_loss_pct=10.0,  # SL at 90
            max_leverage=5.0, leverage_mode="fixed", fixed_leverage=5.0,
            maintenance_margin_rate=0.005,
        )
        # Liquidation should fire, not SL
        assert trades[0].exit_type == "LIQUIDATION"

    def test_no_liquidation_at_1x(self):
        """At 1x leverage, there's no liquidation price (price can't go negative)."""
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
        assert trades[0].exit_type == "FORCED_CLOSE"  # End of backtest, not liquidation
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_liquidation.py -v`
Expected: FAIL — engine.run() doesn't accept leverage params yet.

**Step 3: Implement `_check_liquidation` method**

Add to `backend/services/strategy_engine.py` (after `_check_trailing_stop`):

```python
def _check_liquidation(self, position: Trade, candle: Candle) -> Optional[float]:
    """
    Check if Binance-style liquidation is triggered.

    Returns liquidation_price if triggered, else None.
    Liquidation occurs when price reaches the liquidation level,
    meaning the margin is fully consumed by losses.
    """
    if position.leverage <= 1.0 or position.liquidation_price <= 0:
        return None  # No liquidation at 1x

    if position.side == "LONG":
        if candle.low <= position.liquidation_price:
            return position.liquidation_price
    else:  # SHORT
        if candle.high >= position.liquidation_price:
            return position.liquidation_price

    return None
```

Note: The full engine `run()` integration happens in Task 6. This step only adds the method. Tests in this task will fail until Task 6 is complete. Mark this as a **partial implementation** — the `_check_liquidation` method is ready, but `run()` wiring happens later.

**Step 4: Commit the method (tests will be validated in Task 6)**

```bash
git add backend/services/strategy_engine.py backend/tests/test_liquidation.py
git commit -m "feat: add _check_liquidation method to StrategyEngine"
```

---

### Task 5: Engine — Funding Rate

**Depends on:** Task 1 (models)
**Files:**
- Modify: `backend/services/strategy_engine.py`
- Test: `backend/tests/test_funding_rate.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_funding_rate.py`:

```python
"""Tests for funding rate simulation."""
import pytest
from models import Candle, Trade
from services.strategy_engine import StrategyEngine


def _make_candle(i, price):
    return Candle(
        timestamp=i * 3600000,  # 1h intervals
        open=price, high=price + 1, low=price - 1,
        close=price, volume=1000,
    )


class TestFundingApplication:
    def test_funding_interval_1h(self):
        """1h candles: funding every 8 candles."""
        engine = StrategyEngine()
        assert engine._funding_candle_interval("1h") == 8

    def test_funding_interval_4h(self):
        """4h candles: funding every 2 candles."""
        engine = StrategyEngine()
        assert engine._funding_candle_interval("4h") == 2

    def test_funding_interval_1d(self):
        """1d candles: funding 3 times per candle (every 1, prorated)."""
        engine = StrategyEngine()
        assert engine._funding_candle_interval("1d") == 1

    def test_funding_prorate_factor_1d(self):
        """Daily candles should apply 3x the per-8h rate."""
        engine = StrategyEngine()
        assert engine._funding_prorate_factor("1d") == 3.0

    def test_funding_prorate_factor_4h(self):
        """4h candles: no proration needed."""
        engine = StrategyEngine()
        assert engine._funding_prorate_factor("4h") == 1.0

    def test_apply_funding_deducts_cost(self):
        """Funding deducts from position's funding_paid tracker."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, quantity=10.0,
            side="LONG", leverage=5.0, funding_paid=0.0,
        )
        candle = _make_candle(8, 100)  # price=100
        funding_rate = 0.0001  # 0.01%

        cost = engine._calculate_funding_cost(position, candle, funding_rate, 1.0)
        # cost = quantity * close * rate = 10 * 100 * 0.0001 = 0.1
        assert cost == pytest.approx(0.1, rel=0.01)

    def test_funding_accumulates(self):
        """Multiple funding events accumulate."""
        engine = StrategyEngine()
        position = Trade(
            entry_time=0, entry_price=100.0, quantity=10.0,
            side="LONG", leverage=5.0, funding_paid=0.5,
        )
        candle = _make_candle(16, 100)
        cost = engine._calculate_funding_cost(position, candle, 0.0001, 1.0)
        new_total = position.funding_paid + cost
        assert new_total == pytest.approx(0.6, rel=0.01)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_funding_rate.py -v`
Expected: FAIL — methods don't exist.

**Step 3: Implement funding methods**

Add to `backend/services/strategy_engine.py`:

```python
@staticmethod
def _funding_candle_interval(interval: str) -> int:
    """How many candles between funding events (8h cycle)."""
    intervals = {"1m": 480, "5m": 96, "15m": 32, "30m": 16,
                 "1h": 8, "2h": 4, "4h": 2, "8h": 1, "12h": 1, "1d": 1}
    return intervals.get(interval, 8)

@staticmethod
def _funding_prorate_factor(interval: str) -> float:
    """For intervals >= 8h, prorate funding (multiply rate)."""
    factors = {"8h": 1.0, "12h": 1.5, "1d": 3.0}
    return factors.get(interval, 1.0)

@staticmethod
def _calculate_funding_cost(position: Trade, candle: Candle,
                            funding_rate: float, prorate: float) -> float:
    """Calculate funding cost for one funding event."""
    return position.quantity * candle.close * funding_rate * prorate
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_funding_rate.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/services/strategy_engine.py backend/tests/test_funding_rate.py
git commit -m "feat: add funding rate calculation methods to StrategyEngine"
```

---

### Task 6: Engine — Leveraged Open/Close + Main Loop Integration

**Depends on:** Task 1, Task 3, Task 4, Task 5
**Files:**
- Modify: `backend/services/strategy_engine.py`
- Test: Uses tests from Task 4 (test_liquidation.py) + new `backend/tests/test_leverage_engine.py`

This is the largest task — it wires everything together in the engine's `run()` method.

**Step 1: Write integration tests**

Create `backend/tests/test_leverage_engine.py`:

```python
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
            _make_candle(3, 110),   # 10% up → 50% profit with 5x
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
            _make_candle(3, 95),  # 5% down → 25% loss with 5x
        ]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0, slippage_rate=0)
        trades, equity, _ = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=1000,
            max_leverage=10.0, leverage_mode="fixed", fixed_leverage=5.0,
        )
        # PnL = 50 * (-5) = -250, capital = 1000 - 250 = 750
        assert equity[-1] == pytest.approx(750, rel=0.02)


class TestBackwardCompat:
    def test_1x_leverage_matches_old_behavior(self):
        """fixed_leverage=1.0 should produce same result as no leverage params."""
        candles = [_make_candle(i, 100 + i * 2) for i in range(10)]
        ohlcv = OHLCVData(symbol="TEST", interval="1h", candles=candles)
        engine = StrategyEngine(commission_rate=0.001, slippage_rate=0.0005)

        # Old way (no leverage params — uses defaults)
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
        # This should not raise any errors
        trades, equity, timestamps = engine.run(
            ohlcv, BuyAndHoldStrategy({}), initial_capital=10000,
        )
        assert len(trades) >= 1
        assert len(equity) == len(candles)
```

**Step 2: Modify `StrategyEngine.run()` signature and internals**

This is the core change. Modify `backend/services/strategy_engine.py`:

1. **Update `run()` signature** to accept new leverage params (all with defaults for backward compat):

```python
def run(self, ohlcv: OHLCVData, strategy: BaseStrategy,
        initial_capital: float = 10000.0,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
        trailing_stop_atr_period: int = 0,
        trailing_stop_atr_mult: float = 3.0,
        # Leverage params (new)
        max_leverage: float = 10.0,
        leverage_mode: str = "dynamic",
        fixed_leverage: float = 1.0,
        funding_rate: float = 0.0,
        maintenance_margin_rate: float = 0.005,
        interval: str = "1h",
        ) -> Tuple[List[Trade], List[float], List[int]]:
```

Note: `funding_rate` defaults to 0.0 (not 0.0001) in the engine for backward compat. The config default of 0.0001 is set at the API layer.

2. **Update `_open_long` and `_open_short`** to accept `leverage` and `maintenance_margin_rate` params and calculate `margin_used`, `liquidation_price`, and scaled `quantity`.

3. **Update `_close_position`** to use margin-based PnL formula (margin + unrealized_pnl - funding_paid).

4. **Update main loop** to insert:
   - Liquidation check (step 1, before SL/TP)
   - Funding rate application (step 2, after liquidation)
   - LeverageAssessor call when opening positions
   - Updated equity curve formula

5. **Update equity calculation** to use `margin + unrealized_pnl - funding_paid`.

The exact code changes are extensive. The subagent implementing this task should:
- Read the current `strategy_engine.py` carefully
- Apply changes method by method
- Keep the main loop order: liquidation → funding → SL/TP → trailing → signal → process → equity
- Ensure `leverage_mode="fixed"` + `fixed_leverage=1.0` + `funding_rate=0.0` gives identical results to current behavior

**Step 3: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass (162 existing + new leverage tests).

**Step 4: Commit**

```bash
git add backend/services/strategy_engine.py backend/tests/test_leverage_engine.py
git commit -m "feat: integrate leverage into StrategyEngine main loop"
```

---

### Task 7: Backtest Service + API Pass-through

**Depends on:** Task 6
**Files:**
- Modify: `backend/services/backtest_service.py`
- Modify: `backend/app.py`

**Step 1: Update `backtest_service.py`**

Pass the new config fields to `engine.run()`:

```python
# In run_backtest(), after creating the engine:
trades, equity_curve, equity_timestamps = engine.run(
    ohlcv, strategy, config.initial_capital,
    stop_loss_pct=config.stop_loss_pct,
    take_profit_pct=config.take_profit_pct,
    trailing_stop_atr_period=config.trailing_stop_atr_period,
    trailing_stop_atr_mult=config.trailing_stop_atr_mult,
    # Leverage params
    max_leverage=config.max_leverage,
    leverage_mode=config.leverage_mode,
    fixed_leverage=config.fixed_leverage,
    funding_rate=config.funding_rate,
    maintenance_margin_rate=config.maintenance_margin_rate,
    interval=config.interval,
)
```

**Step 2: Update `app.py`**

Parse new fields in `_handle_api_post` for both `/api/backtest/run` and `/api/backtest/compare`:

```python
max_leverage=float(data.get("max_leverage", 10.0)),
leverage_mode=data.get("leverage_mode", "dynamic"),
fixed_leverage=float(data.get("fixed_leverage", 1.0)),
funding_rate=float(data.get("funding_rate", 0.0001)),
maintenance_margin_rate=float(data.get("maintenance_margin_rate", 0.005)),
```

**Step 3: Smoke test via API**

Run server and test:
```bash
python app.py &
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","strategy_name":"RSI","max_leverage":5,"leverage_mode":"fixed","fixed_leverage":3}'
```

**Step 4: Commit**

```bash
git add backend/services/backtest_service.py backend/app.py
git commit -m "feat: pass leverage config through backtest service and API"
```

---

### Task 8: Report Service — Leverage Metrics

**Depends on:** Task 6
**Files:**
- Modify: `backend/services/report_service.py`

**Step 1: Add leverage metrics to `calculate_metrics()`**

After existing metric calculations, add:

```python
# Leverage metrics
leveraged_trades = [t for t in closed if t.leverage > 1.0]
liq_trades = [t for t in closed if t.exit_type == "LIQUIDATION"]
all_leverage = [t.leverage for t in closed]
all_funding = [t.funding_paid for t in closed]

# Add to return dict:
"avg_leverage": round(float(np.mean(all_leverage)), 1) if all_leverage else 1.0,
"max_leverage_used": round(max(all_leverage), 1) if all_leverage else 1.0,
"total_funding_paid": round(sum(all_funding), 2),
"liquidation_count": len(liq_trades),
"leveraged_trade_count": len(leveraged_trades),
```

Also add `"LIQUIDATION"` to exit type count:
```python
liq_exits = len([t for t in closed if t.exit_type == "LIQUIDATION"])
# Add to return dict:
"liq_exits": liq_exits,
```

**Step 2: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All pass.

**Step 3: Commit**

```bash
git add backend/services/report_service.py
git commit -m "feat: add leverage metrics to report service"
```

---

### Task 9: Full Integration Test + Backward Compatibility Verification

**Depends on:** All previous tasks
**Files:**
- Test: verify ALL tests pass

**Step 1: Run full test suite**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All 162 existing tests + ~40 new tests pass.

**Step 2: Run backtest comparison (leverage vs no-leverage)**

```python
# Quick validation script
from models import BacktestConfig
from services import backtest_service

# 1x (old behavior)
r1 = backtest_service.run_backtest(BacktestConfig(
    symbol="BTCUSDT", strategy_name="RSI",
    start_date="2024-01-01", end_date="2024-06-01",
))

# 3x fixed leverage
r3 = backtest_service.run_backtest(BacktestConfig(
    symbol="BTCUSDT", strategy_name="RSI",
    start_date="2024-01-01", end_date="2024-06-01",
    leverage_mode="fixed", fixed_leverage=3.0,
    funding_rate=0.0001,
))

# Dynamic leverage
rd = backtest_service.run_backtest(BacktestConfig(
    symbol="BTCUSDT", strategy_name="RSI",
    start_date="2024-01-01", end_date="2024-06-01",
    leverage_mode="dynamic",
    funding_rate=0.0001,
))

print(f"1x: {r1.metrics['total_return_pct']}%")
print(f"3x: {r3.metrics['total_return_pct']}%")
print(f"Dynamic: {rd.metrics['total_return_pct']}%")
print(f"Dynamic avg leverage: {rd.metrics.get('avg_leverage')}")
```

**Step 3: Commit and push**

```bash
git push
```

---

## Parallel Execution Guide

```
Task 1 (Models) ──────────┐
                           ├──→ Task 3 (Assessor) ──┐
Task 2 (ADX) ─────────────┘                         │
                                                     ├──→ Task 6 (Engine Integration) ──→ Task 7 (API) ──→ Task 9
Task 4 (Liquidation method) ─────────────────────────┤                                    Task 8 (Metrics) ─┘
                                                     │
Task 5 (Funding methods) ───────────────────────────┘
```

**Parallelizable groups:**
- **Wave 1:** Tasks 1, 2, 4, 5 (all independent foundations)
- **Wave 2:** Task 3 (needs 1+2)
- **Wave 3:** Task 6 (needs 1+3+4+5 — core integration)
- **Wave 4:** Tasks 7, 8 (need 6, can be parallel)
- **Wave 5:** Task 9 (final validation)
