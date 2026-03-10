# Order Book + Real Fees + 5m Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Order Book data pipeline, extend strategy interface for real-time market context, re-test strategies with real Maker fees (0.018%), and research a profitable 5m strategy.

**Architecture:** Extend BaseStrategy with `generate_signal_v2(ohlcv, index, context)` where `MarketContext` carries Order Book data. New Binance WebSocket depth feed follows the existing kline feed pattern. Backward compatible — old strategies unchanged.

**Tech Stack:** Python 3.10+, websocket-client, Binance WebSocket API (`@depth20@100ms`), SQLite cache, existing BaseStrategy/StrategyEngine

---

## Task 1: Data Models — OrderBook + MarketContext

**Files:**
- Modify: `backend/models/__init__.py` (after line 127)
- Test: `backend/tests/test_orderbook_models.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_orderbook_models.py`:
```python
"""Tests for OrderBook and MarketContext data models."""
import pytest
from models import OrderBookLevel, OrderBook, MarketContext


class TestOrderBookLevel:
    def test_create_level(self):
        level = OrderBookLevel(price=42000.0, quantity=1.5)
        assert level.price == 42000.0
        assert level.quantity == 1.5


class TestOrderBook:
    @pytest.fixture
    def sample_ob(self):
        return OrderBook(
            symbol="BTCUSDT",
            timestamp=1700000000000,
            bids=[
                OrderBookLevel(42000.0, 10.0),
                OrderBookLevel(41900.0, 20.0),
                OrderBookLevel(41800.0, 5.0),
            ],
            asks=[
                OrderBookLevel(42100.0, 15.0),
                OrderBookLevel(42200.0, 8.0),
                OrderBookLevel(42300.0, 12.0),
            ],
        )

    def test_best_bid(self, sample_ob):
        assert sample_ob.best_bid == 42000.0

    def test_best_ask(self, sample_ob):
        assert sample_ob.best_ask == 42100.0

    def test_mid_price(self, sample_ob):
        assert sample_ob.mid_price == 42050.0

    def test_spread_pct(self, sample_ob):
        expected = (42100.0 - 42000.0) / 42050.0 * 100
        assert abs(sample_ob.spread_pct - expected) < 0.001

    def test_to_dict(self, sample_ob):
        d = sample_ob.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert len(d["bids"]) == 3
        assert d["bids"][0]["price"] == 42000.0

    def test_empty_bids(self):
        ob = OrderBook("BTCUSDT", 0, [], [OrderBookLevel(100, 1)])
        assert ob.best_bid == 0.0
        assert ob.mid_price == 50.0

    def test_empty_asks(self):
        ob = OrderBook("BTCUSDT", 0, [OrderBookLevel(100, 1)], [])
        assert ob.best_ask == 0.0


class TestMarketContext:
    def test_empty_context(self):
        ctx = MarketContext()
        assert ctx.orderbook is None
        assert ctx.recent_trades is None

    def test_with_orderbook(self):
        ob = OrderBook("BTCUSDT", 0, [], [])
        ctx = MarketContext(orderbook=ob)
        assert ctx.orderbook.symbol == "BTCUSDT"
```

**Step 2: Run tests — expect FAIL (models not defined yet)**
```bash
cd backend && python -m pytest tests/test_orderbook_models.py -v
```
Expected: `ImportError: cannot import name 'OrderBookLevel'`

**Step 3: Implement models**

Add to `backend/models/__init__.py` after line 127:
```python
# --- Order Book Models ---

@dataclass
class OrderBookLevel:
    """Single price level in an order book."""
    price: float
    quantity: float


@dataclass
class OrderBook:
    """Order book snapshot with bids and asks."""
    symbol: str
    timestamp: int
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        if bb and ba:
            return (bb + ba) / 2
        return bb or ba or 0.0

    @property
    def spread_pct(self) -> float:
        mid = self.mid_price
        if mid == 0:
            return 0.0
        return (self.best_ask - self.best_bid) / mid * 100

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bids": [{"price": l.price, "quantity": l.quantity} for l in self.bids],
            "asks": [{"price": l.price, "quantity": l.quantity} for l in self.asks],
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "spread_pct": self.spread_pct,
        }


@dataclass
class MarketContext:
    """Real-time market data passed to strategy.generate_signal_v2().
    Extensible container — add fields as new data sources are integrated."""
    orderbook: Optional[OrderBook] = None
    recent_trades: Optional[List[dict]] = None
    funding_rate: Optional[float] = None
```

Also update the import at top of `models/__init__.py` to include `List` in typing imports if not already present.

**Step 4: Run tests — expect PASS**
```bash
cd backend && python -m pytest tests/test_orderbook_models.py -v
```

**Step 5: Commit**
```bash
git add backend/models/__init__.py backend/tests/test_orderbook_models.py
git commit -m "feat: add OrderBook, OrderBookLevel, MarketContext models"
```

---

## Task 2: Order Book Indicators

**Files:**
- Create: `backend/services/orderbook_indicators.py`
- Test: `backend/tests/test_orderbook_indicators.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_orderbook_indicators.py`:
```python
"""Tests for Order Book indicator calculations."""
import pytest
from models import OrderBook, OrderBookLevel
from services.orderbook_indicators import (
    bid_ask_imbalance, depth_ratio, wall_detection,
    spread_bps, weighted_mid_price, cumulative_delta,
)


@pytest.fixture
def balanced_ob():
    return OrderBook("BTCUSDT", 0,
        bids=[OrderBookLevel(100, 10), OrderBookLevel(99, 10), OrderBookLevel(98, 10)],
        asks=[OrderBookLevel(101, 10), OrderBookLevel(102, 10), OrderBookLevel(103, 10)],
    )


@pytest.fixture
def buy_heavy_ob():
    return OrderBook("BTCUSDT", 0,
        bids=[OrderBookLevel(100, 50), OrderBookLevel(99, 30), OrderBookLevel(98, 20)],
        asks=[OrderBookLevel(101, 5), OrderBookLevel(102, 5), OrderBookLevel(103, 5)],
    )


@pytest.fixture
def sell_heavy_ob():
    return OrderBook("BTCUSDT", 0,
        bids=[OrderBookLevel(100, 5), OrderBookLevel(99, 5)],
        asks=[OrderBookLevel(101, 50), OrderBookLevel(102, 30)],
    )


class TestBidAskImbalance:
    def test_balanced(self, balanced_ob):
        result = bid_ask_imbalance(balanced_ob, levels=3)
        assert abs(result) < 0.01  # ~0

    def test_buy_heavy(self, buy_heavy_ob):
        result = bid_ask_imbalance(buy_heavy_ob, levels=3)
        assert result > 0.5  # Strong buy pressure

    def test_sell_heavy(self, sell_heavy_ob):
        result = bid_ask_imbalance(sell_heavy_ob, levels=2)
        assert result < -0.5  # Strong sell pressure

    def test_empty_ob(self):
        ob = OrderBook("X", 0, [], [])
        assert bid_ask_imbalance(ob) == 0.0


class TestDepthRatio:
    def test_balanced(self, balanced_ob):
        assert abs(depth_ratio(balanced_ob, levels=3) - 1.0) < 0.01

    def test_buy_heavy(self, buy_heavy_ob):
        assert depth_ratio(buy_heavy_ob, levels=3) > 5.0


class TestWallDetection:
    def test_detects_buy_wall(self, buy_heavy_ob):
        walls = wall_detection(buy_heavy_ob, mult=3.0)
        assert len(walls["bid_walls"]) > 0
        assert walls["bid_walls"][0]["price"] == 100

    def test_no_walls_balanced(self, balanced_ob):
        walls = wall_detection(balanced_ob, mult=3.0)
        assert len(walls["bid_walls"]) == 0
        assert len(walls["ask_walls"]) == 0


class TestSpreadBps:
    def test_spread(self, balanced_ob):
        result = spread_bps(balanced_ob)
        expected = (101 - 100) / 100.5 * 10000
        assert abs(result - expected) < 1


class TestWeightedMidPrice:
    def test_balanced(self, balanced_ob):
        result = weighted_mid_price(balanced_ob)
        assert 100 < result < 101

    def test_buy_heavy_pulls_up(self, buy_heavy_ob):
        # More bid volume → mid shifts toward ask
        result = weighted_mid_price(buy_heavy_ob)
        assert result > 100.5


class TestCumulativeDelta:
    def test_buy_heavy(self, buy_heavy_ob):
        result = cumulative_delta(buy_heavy_ob, price_range_pct=5.0)
        assert result > 0  # More bids than asks

    def test_sell_heavy(self, sell_heavy_ob):
        result = cumulative_delta(sell_heavy_ob, price_range_pct=5.0)
        assert result < 0
```

**Step 2: Run tests — expect FAIL**
```bash
cd backend && python -m pytest tests/test_orderbook_indicators.py -v
```

**Step 3: Implement indicators**

Create `backend/services/orderbook_indicators.py`:
```python
"""Order Book indicator calculations for strategy signals.

Functions take an OrderBook snapshot and return numeric indicators
that strategies can use for entry/exit decisions.
"""
from typing import Dict, List, Any
from models import OrderBook


def bid_ask_imbalance(ob: OrderBook, levels: int = 5) -> float:
    """(bid_vol - ask_vol) / (bid_vol + ask_vol) for top N levels.
    Range: [-1, 1]. Positive = more buy pressure."""
    bid_vol = sum(l.quantity for l in ob.bids[:levels])
    ask_vol = sum(l.quantity for l in ob.asks[:levels])
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def depth_ratio(ob: OrderBook, levels: int = 10) -> float:
    """Total bid volume / total ask volume at top N levels.
    >1 = more bids, <1 = more asks."""
    bid_vol = sum(l.quantity for l in ob.bids[:levels])
    ask_vol = sum(l.quantity for l in ob.asks[:levels])
    if ask_vol == 0:
        return float('inf') if bid_vol > 0 else 1.0
    return bid_vol / ask_vol


def wall_detection(ob: OrderBook, mult: float = 5.0) -> Dict[str, List[Dict[str, Any]]]:
    """Detect large orders that are mult x average size.
    Returns dict with 'bid_walls' and 'ask_walls' lists."""
    result: Dict[str, List[Dict[str, Any]]] = {"bid_walls": [], "ask_walls": []}

    if ob.bids:
        avg_bid_qty = sum(l.quantity for l in ob.bids) / len(ob.bids)
        for l in ob.bids:
            if l.quantity >= avg_bid_qty * mult:
                result["bid_walls"].append({"price": l.price, "quantity": l.quantity})

    if ob.asks:
        avg_ask_qty = sum(l.quantity for l in ob.asks) / len(ob.asks)
        for l in ob.asks:
            if l.quantity >= avg_ask_qty * mult:
                result["ask_walls"].append({"price": l.price, "quantity": l.quantity})

    return result


def spread_bps(ob: OrderBook) -> float:
    """Spread in basis points (1 bp = 0.01%)."""
    mid = ob.mid_price
    if mid == 0:
        return 0.0
    return (ob.best_ask - ob.best_bid) / mid * 10000


def weighted_mid_price(ob: OrderBook) -> float:
    """Volume-weighted mid price. Shifts toward side with more volume."""
    bb, ba = ob.best_bid, ob.best_ask
    if not ob.bids or not ob.asks:
        return ob.mid_price
    bv = ob.bids[0].quantity
    av = ob.asks[0].quantity
    total = bv + av
    if total == 0:
        return ob.mid_price
    return (bb * av + ba * bv) / total


def cumulative_delta(ob: OrderBook, price_range_pct: float = 0.5) -> float:
    """Net order flow: total bid qty - total ask qty within price range of mid.
    Positive = net buying pressure."""
    mid = ob.mid_price
    if mid == 0:
        return 0.0
    range_abs = mid * price_range_pct / 100
    lo, hi = mid - range_abs, mid + range_abs

    bid_vol = sum(l.quantity for l in ob.bids if l.price >= lo)
    ask_vol = sum(l.quantity for l in ob.asks if l.price <= hi)
    return bid_vol - ask_vol
```

**Step 4: Run tests — expect PASS**
```bash
cd backend && python -m pytest tests/test_orderbook_indicators.py -v
```

**Step 5: Commit**
```bash
git add backend/services/orderbook_indicators.py backend/tests/test_orderbook_indicators.py
git commit -m "feat: add Order Book indicator functions (imbalance, depth ratio, walls, spread)"
```

---

## Task 3: Extend BaseStrategy with generate_signal_v2

**Files:**
- Modify: `backend/strategies/base_strategy.py`
- Test: `backend/tests/test_strategy_v2_compat.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_strategy_v2_compat.py`:
```python
"""Tests for BaseStrategy v2 interface backward compatibility."""
import pytest
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal, MarketContext, Candle
from strategies.base_strategy import BaseStrategy


class OldStrategy(BaseStrategy):
    """v1 strategy — only implements generate_signal."""
    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {"name": "Old", "description": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index) -> Optional[TradeSignal]:
        return TradeSignal(timestamp=0, signal_type="BUY", price=100, reason="test")


class NewStrategy(BaseStrategy):
    """v2 strategy — overrides generate_signal_v2 to use MarketContext."""
    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {"name": "New", "description": "test", "parameters": {}}

    def generate_signal(self, ohlcv, index) -> Optional[TradeSignal]:
        return None  # v1 returns nothing

    def generate_signal_v2(self, ohlcv, index, context: MarketContext) -> Optional[TradeSignal]:
        if context.orderbook is not None:
            return TradeSignal(timestamp=0, signal_type="BUY", price=100, reason="OB signal")
        return None


class TestV2Compatibility:
    def test_old_strategy_v2_delegates(self):
        """Old strategies' generate_signal_v2 should delegate to generate_signal."""
        s = OldStrategy({})
        ctx = MarketContext()
        signal = s.generate_signal_v2(None, 0, ctx)
        assert signal is not None
        assert signal.signal_type == "BUY"

    def test_old_strategy_uses_market_context_false(self):
        s = OldStrategy({})
        assert s.uses_market_context is False

    def test_new_strategy_uses_market_context_true(self):
        s = NewStrategy({})
        assert s.uses_market_context is True

    def test_new_strategy_with_ob(self):
        from models import OrderBook
        s = NewStrategy({})
        ob = OrderBook("BTC", 0, [], [])
        ctx = MarketContext(orderbook=ob)
        signal = s.generate_signal_v2(None, 0, ctx)
        assert signal is not None
        assert signal.reason == "OB signal"

    def test_new_strategy_without_ob(self):
        s = NewStrategy({})
        ctx = MarketContext()
        signal = s.generate_signal_v2(None, 0, ctx)
        assert signal is None
```

**Step 2: Run tests — expect FAIL**
```bash
cd backend && python -m pytest tests/test_strategy_v2_compat.py -v
```

**Step 3: Implement v2 interface**

Modify `backend/strategies/base_strategy.py` — add after line 6:
```python
from models import OHLCVData, TradeSignal, MarketContext
```

Add after `cache_indicator` method (after line 78):
```python
    def generate_signal_v2(self, ohlcv: OHLCVData, index: int,
                           context: MarketContext) -> Optional[TradeSignal]:
        """Extended signal generation with real-time market context.

        Default: delegates to generate_signal() for backward compatibility.
        Override in strategies that use Order Book or other real-time data.

        Args:
            ohlcv: Full OHLCV dataset
            index: Current candle index
            context: MarketContext with orderbook, recent_trades, etc.
        """
        return self.generate_signal(ohlcv, index)

    @property
    def uses_market_context(self) -> bool:
        """True if this strategy overrides generate_signal_v2."""
        return type(self).generate_signal_v2 is not BaseStrategy.generate_signal_v2
```

**Step 4: Run tests — expect PASS**
```bash
cd backend && python -m pytest tests/test_strategy_v2_compat.py -v
```

**Step 5: Run ALL tests to ensure no regressions**
```bash
cd backend && python -m pytest tests/ -v
```

**Step 6: Commit**
```bash
git add backend/strategies/base_strategy.py backend/tests/test_strategy_v2_compat.py
git commit -m "feat: add generate_signal_v2 with MarketContext to BaseStrategy"
```

---

## Task 4: Update StrategyEngine to Use generate_signal_v2

**Files:**
- Modify: `backend/services/strategy_engine.py` (line 150)
- Modify: `backend/live/engine.py` (lines 160, 200, 410)

**Step 1: Update backtest engine**

In `backend/services/strategy_engine.py`, change line 150 from:
```python
signal = strategy.generate_signal(ohlcv, i)
```
to:
```python
from models import MarketContext
...
signal = strategy.generate_signal_v2(ohlcv, i, MarketContext())
```

Note: Import `MarketContext` at top of file. For backtest, context is empty (no OB data).

**Step 2: Update live engine**

In `backend/live/engine.py`, change all 3 occurrences of `generate_signal` to `generate_signal_v2` with empty `MarketContext()`. (Lines 160, 200, 410)

These will be enhanced later (Task 7) to pass real OB data when depth feed is connected.

**Step 3: Run ALL tests**
```bash
cd backend && python -m pytest tests/ -v
```

All existing 257+ tests must pass — this is purely a backward-compatible interface change.

**Step 4: Commit**
```bash
git add backend/services/strategy_engine.py backend/live/engine.py
git commit -m "refactor: use generate_signal_v2 in backtest and live engines"
```

---

## Task 5: Binance Depth WebSocket Feed

**Files:**
- Create: `backend/live/feeds/binance_depth_feed.py`
- Modify: `backend/live/feeds/__init__.py`
- Test: `backend/tests/test_depth_feed.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_depth_feed.py`:
```python
"""Tests for Binance Depth WebSocket Feed."""
import json
import pytest
from models import OrderBook, OrderBookLevel
from live.feeds.binance_depth_feed import BinanceDepthFeed


def _depth_msg(bids=None, asks=None, symbol="BTCUSDT", timestamp=1700000000000):
    if bids is None:
        bids = [["42000.00", "10.500"], ["41900.00", "20.000"]]
    if asks is None:
        asks = [["42100.00", "15.300"], ["42200.00", "25.000"]]
    return json.dumps({
        "e": "depthUpdate",
        "E": timestamp,
        "s": symbol,
        "U": 1000,
        "u": 1001,
        "b": bids,
        "a": asks,
    })


class TestDepthMessageParsing:
    def test_parse_valid_depth(self):
        feed = BinanceDepthFeed("BTCUSDT")
        msg = _depth_msg()
        ob = feed._parse_depth_message(json.loads(msg))
        assert ob is not None
        assert ob.symbol == "BTCUSDT"
        assert len(ob.bids) == 2
        assert ob.bids[0].price == 42000.0
        assert ob.bids[0].quantity == 10.5
        assert len(ob.asks) == 2
        assert ob.asks[0].price == 42100.0

    def test_parse_empty_depth(self):
        feed = BinanceDepthFeed("BTCUSDT")
        msg = json.loads(_depth_msg(bids=[], asks=[]))
        ob = feed._parse_depth_message(msg)
        assert ob is not None
        assert len(ob.bids) == 0

    def test_parse_invalid_message(self):
        feed = BinanceDepthFeed("BTCUSDT")
        ob = feed._parse_depth_message({"e": "trade"})
        assert ob is None

    def test_get_orderbook_returns_latest(self):
        feed = BinanceDepthFeed("BTCUSDT")
        msg = json.loads(_depth_msg())
        feed._latest_ob = feed._parse_depth_message(msg)
        ob = feed.get_orderbook()
        assert ob is not None
        assert ob.best_bid == 42000.0

    def test_get_orderbook_none_before_data(self):
        feed = BinanceDepthFeed("BTCUSDT")
        assert feed.get_orderbook() is None
```

**Step 2: Run tests — expect FAIL**

**Step 3: Implement depth feed**

Create `backend/live/feeds/binance_depth_feed.py`:
```python
"""Binance WebSocket depth feed for real-time Order Book data.

Connects to Binance partial book depth stream and maintains
the latest OrderBook snapshot. Thread-safe access via get_orderbook().
"""
import json
import logging
import queue
import threading
import time
from typing import Optional, Callable

from models import OrderBook, OrderBookLevel

logger = logging.getLogger(__name__)

BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"


class BinanceDepthFeed:
    """Real-time order book feed from Binance WebSocket.

    Subscribes to partial book depth stream (@depth20@100ms)
    which sends top 20 bid/ask levels every 100ms.
    """

    def __init__(self, symbol: str, levels: int = 20,
                 on_depth_update: Optional[Callable[[OrderBook], None]] = None):
        self._symbol = symbol.lower()
        self._levels = levels
        self._on_depth_update = on_depth_update
        self._latest_ob: Optional[OrderBook] = None
        self._lock = threading.Lock()
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._connected = False
        self._stop_event = threading.Event()
        self._ws_url = f"{BINANCE_WS_BASE}/{self._symbol}@depth{levels}@100ms"
        self._max_retries = 10
        self._base_delay = 5.0
        self._max_delay = 60.0

    def start(self) -> None:
        """Start the WebSocket connection in a background thread."""
        if self._ws_thread and self._ws_thread.is_alive():
            logger.warning("Depth feed already running")
            return
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_with_reconnect, daemon=True
        )
        self._ws_thread.start()
        logger.info(f"Depth feed started for {self._symbol}")

    def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        self._connected = False
        logger.info("Depth feed stopped")

    def get_orderbook(self) -> Optional[OrderBook]:
        """Get the latest order book snapshot. Thread-safe."""
        with self._lock:
            return self._latest_ob

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _parse_depth_message(self, data: dict) -> Optional[OrderBook]:
        """Parse a Binance depth message into an OrderBook."""
        if data.get("e") not in ("depthUpdate", None):
            # Partial depth stream sends without event type
            pass

        bids_raw = data.get("b", data.get("bids", []))
        asks_raw = data.get("a", data.get("asks", []))

        if bids_raw is None and asks_raw is None:
            return None

        bids = [OrderBookLevel(float(b[0]), float(b[1])) for b in (bids_raw or [])]
        asks = [OrderBookLevel(float(a[0]), float(a[1])) for a in (asks_raw or [])]

        return OrderBook(
            symbol=self._symbol.upper(),
            timestamp=data.get("E", int(time.time() * 1000)),
            bids=bids,
            asks=asks,
        )

    def _on_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return

        ob = self._parse_depth_message(data)
        if ob is None:
            return

        with self._lock:
            self._latest_ob = ob

        if self._on_depth_update:
            try:
                self._on_depth_update(ob)
            except Exception as e:
                logger.error(f"Depth update callback error: {e}")

    def _on_open(self, ws) -> None:
        self._connected = True
        logger.info(f"Depth WebSocket connected: {self._ws_url}")

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self._connected = False
        logger.info(f"Depth WebSocket closed: {close_status_code}")

    def _on_error(self, ws, error) -> None:
        logger.error(f"Depth WebSocket error: {error}")

    def _run_with_reconnect(self) -> None:
        """Run WebSocket with exponential backoff reconnection."""
        try:
            import websocket
        except ImportError:
            logger.error("websocket-client not installed. pip install websocket-client")
            return

        retries = 0
        while not self._stop_event.is_set() and retries < self._max_retries:
            try:
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self._ws.run_forever()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            if self._stop_event.is_set():
                break

            retries += 1
            delay = min(self._base_delay * (2 ** (retries - 1)), self._max_delay)
            logger.info(f"Reconnecting in {delay}s (attempt {retries})")
            self._stop_event.wait(delay)
```

Update `backend/live/feeds/__init__.py`:
```python
"""Real-time data feed modules."""
from .binance_depth_feed import BinanceDepthFeed
```

**Step 4: Run tests — expect PASS**
```bash
cd backend && python -m pytest tests/test_depth_feed.py -v
```

**Step 5: Commit**
```bash
git add backend/live/feeds/binance_depth_feed.py backend/live/feeds/__init__.py backend/tests/test_depth_feed.py
git commit -m "feat: add Binance depth WebSocket feed for real-time Order Book"
```

---

## Task 6: REST API for Depth Data

**Files:**
- Modify: `backend/services/data_service.py` (add fetch_depth)
- Modify: `backend/app.py` (add /api/data/{symbol}/depth endpoint)

**Step 1: Add fetch_depth to data_service.py**

Add at end of `backend/services/data_service.py`:
```python
def fetch_depth(symbol: str, limit: int = 20) -> OrderBook:
    """Fetch current order book depth from Binance REST API."""
    from models import OrderBook, OrderBookLevel
    url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit={limit}"
    try:
        data = json.loads(_fetch_url(url))
        bids = [OrderBookLevel(float(b[0]), float(b[1])) for b in data.get("bids", [])]
        asks = [OrderBookLevel(float(a[0]), float(a[1])) for a in data.get("asks", [])]
        return OrderBook(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=bids,
            asks=asks,
        )
    except Exception as e:
        logger.warning(f"Failed to fetch depth for {symbol}: {e}")
        return OrderBook(symbol=symbol, timestamp=int(time.time() * 1000))
```

**Step 2: Add API endpoint to app.py**

In the `do_GET` handler, add depth route BEFORE the existing `/api/data/` catch-all:
```python
# GET /api/data/{symbol}/depth
elif path.startswith("/api/data/") and "/depth" in path:
    parts = path.split("/")
    symbol = parts[3]  # /api/data/BTCUSDT/depth
    limit = int(params.get("levels", params.get("limit", ["20"]))[0])
    from services.data_service import fetch_depth
    depth = fetch_depth(symbol, limit)
    self._send_json(depth.to_dict())
```

**Step 3: Test manually**
```bash
curl -s http://localhost:8000/api/data/BTCUSDT/depth | python -m json.tool | head -20
```

**Step 4: Commit**
```bash
git add backend/services/data_service.py backend/app.py
git commit -m "feat: add /api/data/{symbol}/depth endpoint for Order Book snapshots"
```

---

## Task 7: Wire Depth Feed to Live Engine

**Files:**
- Modify: `backend/live/engine.py` (pass MarketContext with real OB)

**Step 1: Update LiveTradingEngine to accept depth feed**

In `engine.py`, update the `_run_realtime()` method and `_run_polling()` to:
1. Optionally accept a `BinanceDepthFeed` instance
2. Get latest OB snapshot before each signal generation
3. Pass it in `MarketContext`

```python
# In the signal generation section:
from models import MarketContext
from live.feeds import BinanceDepthFeed

# Get current orderbook if depth feed available
ob = self._depth_feed.get_orderbook() if self._depth_feed else None
context = MarketContext(orderbook=ob)
signal = self._strategy.generate_signal_v2(ohlcv, index, context)
```

**Step 2: Run ALL tests**
```bash
cd backend && python -m pytest tests/ -v
```

**Step 3: Commit**
```bash
git add backend/live/engine.py
git commit -m "feat: wire depth feed to live engine, pass MarketContext to strategies"
```

---

## Task 8: Re-test Strategies with Real Maker Fees

**No code changes needed.** Run backtests via API with real fees.

**Step 1: Re-test Scalp Sniper on 1m with Maker fees**
```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT", "interval": "1m",
    "start_date": "2025-01-01", "end_date": "2025-03-01",
    "initial_capital": 10000,
    "strategy_name": "Scalp Sniper",
    "commission_rate": 0.00018,
    "slippage_rate": 0,
    "leverage_mode": "fixed", "fixed_leverage": 1.0, "max_leverage": 1.0
  }'
```

**Step 2: Compare all strategies on 1m and 5m with real fees**

Run comparison endpoint with `commission_rate: 0.00018, slippage_rate: 0`.

**Step 3: Document results and commit**
```bash
git commit -m "docs: re-test results with real Maker fees (0.018%)"
```

---

## Task 9: Research 5m Strategy

**Run `/research BTCUSDT 5m` with real Maker fees.**

This is executed via the research workflow and will:
1. Baseline all strategies on 5m
2. Design new strategy optimized for 5m
3. Implement, backtest, optimize
4. Walk-Forward validation
5. Final report

**Key config override:** Always pass `commission_rate=0.00018, slippage_rate=0` to all backtests.

---

## Task 10: Push All Changes

```bash
git push
```
