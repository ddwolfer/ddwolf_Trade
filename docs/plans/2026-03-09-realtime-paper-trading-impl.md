# Real-Time Paper Trading — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect paper trading to Binance WebSocket for live BTCUSDT strategy execution with dynamic leverage, liquidation, and a Web UI monitoring dashboard.

**Architecture:** A `BinanceWebSocketFeed` class runs in a background thread subscribing to Binance kline streams. When a candle closes, it queues the candle for the `LiveTradingEngine`'s new `realtime` mode. The engine evaluates strategy signals, applies leverage via `LeverageAssessor`, checks liquidation/funding, and executes through the upgraded `PaperTradingAdapter`. A new Live Monitor tab in the frontend polls the REST API every 10 seconds.

**Tech Stack:** Python 3.10+, websocket-client, existing SQLite persistence, Plotly CDN for charts.

**Parallelization:** Tasks 1-2 are independent foundations. Task 3 depends on 2. Task 4 depends on 1+3. Task 5 depends on 4. Task 6 depends on 4+5. Task 7 is final validation.

---

### Task 1: BinanceWebSocketFeed Module

**Depends on:** nothing
**Files:**
- Create: `backend/live/feeds/__init__.py`
- Create: `backend/live/feeds/binance_ws_feed.py`
- Test: `backend/tests/test_ws_feed.py` (create)

**Step 1: Install dependency**

Run: `pip install websocket-client`

**Step 2: Create package**

Create `backend/live/feeds/__init__.py`:
```python
"""Real-time data feed modules."""
```

**Step 3: Write failing tests**

Create `backend/tests/test_ws_feed.py`:

```python
"""Tests for BinanceWebSocketFeed — message parsing and queue behavior."""
import json
import pytest
import queue
from unittest.mock import MagicMock, patch
from models import Candle
from live.feeds.binance_ws_feed import BinanceWebSocketFeed


def _kline_msg(symbol="BTCUSDT", interval="1h", is_closed=True,
               t=1672531200000, o="42000", h="42500", l="41800",
               c="42300", v="1234.56"):
    """Build a Binance kline WebSocket message."""
    return json.dumps({
        "e": "kline",
        "E": t + 1000,
        "s": symbol,
        "k": {
            "t": t,
            "T": t + 3600000 - 1,
            "s": symbol,
            "i": interval,
            "o": o, "h": h, "l": l, "c": c,
            "v": v,
            "x": is_closed,
        }
    })


class TestMessageParsing:
    def test_parse_closed_kline(self):
        """Closed kline should produce a Candle."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        msg = _kline_msg(is_closed=True, c="42300")
        feed._on_message(None, msg)
        candle = feed.get_candle(timeout=1.0)
        assert candle is not None
        assert candle.close == 42300.0
        assert candle.high == 42500.0
        assert candle.low == 41800.0
        assert candle.volume == 1234.56

    def test_parse_open_kline_no_candle(self):
        """Non-closed kline should NOT produce a candle."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        msg = _kline_msg(is_closed=False)
        feed._on_message(None, msg)
        candle = feed.get_candle(timeout=0.1)
        assert candle is None

    def test_open_kline_calls_price_callback(self):
        """Non-closed kline should call on_price_update with close price."""
        callback = MagicMock()
        feed = BinanceWebSocketFeed("btcusdt", "1h", on_price_update=callback)
        msg = _kline_msg(is_closed=False, c="42100")
        feed._on_message(None, msg)
        callback.assert_called_once_with(42100.0)

    def test_closed_kline_also_calls_price_callback(self):
        """Closed kline should also update price."""
        callback = MagicMock()
        feed = BinanceWebSocketFeed("btcusdt", "1h", on_price_update=callback)
        msg = _kline_msg(is_closed=True, c="42300")
        feed._on_message(None, msg)
        callback.assert_called_once_with(42300.0)

    def test_invalid_message_ignored(self):
        """Non-kline messages should be silently ignored."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        feed._on_message(None, '{"e": "trade", "p": "42000"}')
        candle = feed.get_candle(timeout=0.1)
        assert candle is None

    def test_malformed_json_ignored(self):
        """Malformed JSON should not crash."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        feed._on_message(None, "not json at all")
        candle = feed.get_candle(timeout=0.1)
        assert candle is None


class TestQueueBehavior:
    def test_multiple_candles_queued_in_order(self):
        """Multiple closed klines should queue in order."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        feed._on_message(None, _kline_msg(c="100", t=1000))
        feed._on_message(None, _kline_msg(c="200", t=2000))
        feed._on_message(None, _kline_msg(c="300", t=3000))
        c1 = feed.get_candle(timeout=0.1)
        c2 = feed.get_candle(timeout=0.1)
        c3 = feed.get_candle(timeout=0.1)
        assert c1.close == 100.0
        assert c2.close == 200.0
        assert c3.close == 300.0

    def test_get_candle_timeout_returns_none(self):
        """Empty queue + timeout should return None."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        result = feed.get_candle(timeout=0.1)
        assert result is None


class TestConnectionState:
    def test_initial_state_not_connected(self):
        """Feed starts not connected."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        assert feed.is_connected() is False

    def test_ws_url_format(self):
        """WebSocket URL should follow Binance format."""
        feed = BinanceWebSocketFeed("btcusdt", "1h")
        assert "btcusdt@kline_1h" in feed._ws_url

    def test_ws_url_different_interval(self):
        """WebSocket URL should include the interval."""
        feed = BinanceWebSocketFeed("ethusdt", "4h")
        assert "ethusdt@kline_4h" in feed._ws_url
```

**Step 4: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ws_feed.py -v`
Expected: FAIL — module doesn't exist.

**Step 5: Implement BinanceWebSocketFeed**

Create `backend/live/feeds/binance_ws_feed.py`:

```python
"""
Binance WebSocket K-line Data Feed.

Connects to Binance's public WebSocket stream for real-time kline data.
No API key required — kline data is public.

When a candle closes (kline.x == true), the completed Candle is placed
into a thread-safe queue for the engine to consume.
"""
import json
import time
import queue
import logging
import threading
from typing import Optional, Callable

from models import Candle

logger = logging.getLogger(__name__)

BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"


class BinanceWebSocketFeed:
    """
    Real-time kline feed from Binance WebSocket.

    Usage:
        feed = BinanceWebSocketFeed("btcusdt", "1h", on_price_update=callback)
        feed.start()
        while running:
            candle = feed.get_candle(timeout=5.0)
            if candle:
                process(candle)
        feed.stop()
    """

    def __init__(self, symbol: str, interval: str,
                 on_price_update: Optional[Callable[[float], None]] = None):
        """
        Args:
            symbol: Trading pair in lowercase (e.g. "btcusdt")
            interval: K-line interval (e.g. "1h", "4h", "1m")
            on_price_update: Optional callback for real-time price updates
                             (called on every kline event, not just closed)
        """
        self._symbol = symbol.lower()
        self._interval = interval
        self._on_price_update = on_price_update
        self._queue: queue.Queue = queue.Queue()
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._connected = False
        self._stop_event = threading.Event()
        self._ws_url = f"{BINANCE_WS_BASE}/{self._symbol}@kline_{self._interval}"

        # Reconnection config
        self._max_retries = 10
        self._base_delay = 5.0
        self._max_delay = 60.0

    def start(self) -> None:
        """Start WebSocket connection in a background daemon thread."""
        import websocket

        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws, daemon=True, name="binance-ws-feed"
        )
        self._ws_thread.start()
        logger.info(f"WebSocket feed started: {self._ws_url}")

    def stop(self) -> None:
        """Stop WebSocket connection and background thread."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=10)
        self._connected = False
        logger.info("WebSocket feed stopped")

    def get_candle(self, timeout: float = 5.0) -> Optional[Candle]:
        """
        Get the next closed candle from the queue.

        Blocks until a candle is available or timeout expires.
        Returns None on timeout.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._connected

    # ------------------------------------------------------------------
    # Internal WebSocket handlers
    # ------------------------------------------------------------------

    def _run_ws(self) -> None:
        """Main WebSocket loop with auto-reconnect."""
        import websocket

        retry_count = 0

        while not self._stop_event.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                self._ws.run_forever()

                if self._stop_event.is_set():
                    break

                # Connection dropped — reconnect
                retry_count += 1
                if retry_count > self._max_retries:
                    logger.error(f"Max retries ({self._max_retries}) reached, giving up")
                    break

                delay = min(self._base_delay * (2 ** (retry_count - 1)), self._max_delay)
                logger.warning(f"Reconnecting in {delay}s (attempt {retry_count}/{self._max_retries})")
                self._stop_event.wait(delay)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if not self._stop_event.is_set():
                    self._stop_event.wait(self._base_delay)

    def _on_open(self, ws) -> None:
        """Called when WebSocket connection is established."""
        self._connected = True
        logger.info(f"Connected to {self._ws_url}")

    def _on_close(self, ws, close_status_code=None, close_msg=None) -> None:
        """Called when WebSocket connection is closed."""
        self._connected = False
        logger.info(f"WebSocket closed: {close_status_code} {close_msg}")

    def _on_error(self, ws, error) -> None:
        """Called on WebSocket error."""
        self._connected = False
        logger.error(f"WebSocket error: {error}")

    def _on_message(self, ws, message: str) -> None:
        """
        Process incoming WebSocket message.

        Binance kline format:
        {
            "e": "kline",
            "k": {
                "t": start_time_ms, "o": open, "h": high, "l": low,
                "c": close, "v": volume, "x": is_closed
            }
        }
        """
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return

        if data.get("e") != "kline":
            return

        k = data.get("k", {})
        close_price = float(k.get("c", 0))

        # Always update price (for live UI)
        if self._on_price_update and close_price > 0:
            try:
                self._on_price_update(close_price)
            except Exception as e:
                logger.error(f"Price update callback error: {e}")

        # Only queue completed candles
        if k.get("x", False):
            candle = Candle(
                timestamp=int(k["t"]),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
            )
            self._queue.put(candle)
```

**Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_ws_feed.py -v`
Expected: All PASS.

**Step 7: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All 214 existing + new tests pass.

**Step 8: Commit**

```bash
git add backend/live/feeds/__init__.py backend/live/feeds/binance_ws_feed.py backend/tests/test_ws_feed.py
git commit -m "feat: add BinanceWebSocketFeed for real-time kline data"
```

---

### Task 2: Model Updates — Leverage Fields for Live Trading

**Depends on:** nothing
**Files:**
- Modify: `backend/live/models.py`
- Test: `backend/tests/test_live_models.py` (add to existing)

**Step 1: Write failing tests**

Add to `backend/tests/test_live_models.py`:

```python
class TestTradingSessionConfigLeverage:
    def test_default_leverage_fields(self):
        config = TradingSessionConfig()
        assert config.max_leverage == 10.0
        assert config.leverage_mode == "dynamic"
        assert config.fixed_leverage == 1.0
        assert config.funding_rate == 0.0001
        assert config.maintenance_margin_rate == 0.005
        assert config.stop_loss_pct == 0.0
        assert config.take_profit_pct == 0.0

    def test_custom_leverage_config(self):
        config = TradingSessionConfig(
            max_leverage=5.0,
            leverage_mode="fixed",
            fixed_leverage=3.0,
            stop_loss_pct=5.0,
        )
        assert config.max_leverage == 5.0
        assert config.leverage_mode == "fixed"
        assert config.fixed_leverage == 3.0
        assert config.stop_loss_pct == 5.0

    def test_leverage_config_in_to_dict(self):
        config = TradingSessionConfig(max_leverage=5.0)
        d = config.to_dict()
        assert d["max_leverage"] == 5.0
        assert d["leverage_mode"] == "dynamic"


class TestPositionLeverage:
    def test_position_default_leverage(self):
        pos = Position(symbol="BTCUSDT", side="LONG", quantity=1.0, entry_price=100.0)
        assert pos.leverage == 1.0
        assert pos.margin_used == 0.0
        assert pos.liquidation_price == 0.0
        assert pos.funding_paid == 0.0

    def test_position_custom_leverage(self):
        pos = Position(
            symbol="BTCUSDT", side="LONG", quantity=1.0, entry_price=100.0,
            leverage=5.0, margin_used=20.0, liquidation_price=80.0,
        )
        assert pos.leverage == 5.0
        assert pos.margin_used == 20.0
        assert pos.liquidation_price == 80.0
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_live_models.py -v -k "Leverage"`
Expected: FAIL — fields don't exist.

**Step 3: Add leverage fields**

In `backend/live/models.py`:

1. Add to `TradingSessionConfig` (after `mode: str = "simulated"`):
```python
    # Leverage / contract settings
    max_leverage: float = 10.0
    leverage_mode: str = "dynamic"         # "dynamic" or "fixed"
    fixed_leverage: float = 1.0
    funding_rate: float = 0.0001           # Per 8h
    maintenance_margin_rate: float = 0.005  # 0.5%
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
```

2. Add to `Position` (after `status: str = "open"`):
```python
    leverage: float = 1.0
    margin_used: float = 0.0
    liquidation_price: float = 0.0
    funding_paid: float = 0.0
```

3. Update `to_dict()` in both classes to include new fields.

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_live_models.py -v`
Expected: All PASS.

**Step 5: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All pass.

**Step 6: Commit**

```bash
git add backend/live/models.py backend/tests/test_live_models.py
git commit -m "feat: add leverage fields to TradingSessionConfig and Position"
```

---

### Task 3: PaperTradingAdapter — Leverage Support

**Depends on:** Task 2 (model fields)
**Files:**
- Modify: `backend/live/adapters/paper_adapter.py`
- Test: `backend/tests/test_paper_leverage.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_paper_leverage.py`:

```python
"""Tests for PaperTradingAdapter leverage support."""
import pytest
from models import Candle
from live.adapters.paper_adapter import PaperTradingAdapter


def _adapter(capital=10000, commission=0, slippage=0):
    return PaperTradingAdapter("test", initial_capital=capital,
                                commission_rate=commission, slippage_rate=slippage)


class TestLeveragedOrder:
    def test_buy_with_leverage_increases_quantity(self):
        """3x leverage should give 3x the quantity of 1x."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        order = a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                              "test", leverage=3.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        assert pos is not None
        assert pos.leverage == 3.0
        # quantity = (1000 * 3) / 100 = 30
        assert pos.quantity == pytest.approx(30.0, rel=0.01)
        assert pos.margin_used == pytest.approx(1000.0, rel=0.01)
        assert pos.liquidation_price > 0

    def test_short_with_leverage(self):
        """SHORT with leverage should set leverage fields."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        order = a.place_order("BTC", "SHORT_OPEN", "MARKET", 0, 100.0,
                              "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        assert pos.leverage == 5.0
        assert pos.side == "SHORT"
        assert pos.liquidation_price > 100.0  # SHORT liq is above entry

    def test_1x_leverage_no_liquidation_price(self):
        """1x leverage should have liquidation_price = 0."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0, "test", leverage=1.0)
        pos = a.get_position("BTC")
        assert pos.liquidation_price == 0.0


class TestLiquidationCheck:
    def test_long_liquidation_triggered(self):
        """LONG position should be liquidated when price drops to liq level."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        liq_price = pos.liquidation_price

        candle = Candle(timestamp=1000, open=85, high=90,
                        low=liq_price - 1, close=82, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is True
        assert a.get_position("BTC") is None  # Position closed
        assert a._cash == 0.0  # Lost all margin

    def test_short_liquidation_triggered(self):
        """SHORT position should be liquidated when price rises to liq level."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "SHORT_OPEN", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        liq_price = pos.liquidation_price

        candle = Candle(timestamp=1000, open=115, high=liq_price + 1,
                        low=110, close=118, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is True
        assert a.get_position("BTC") is None

    def test_no_liquidation_when_safe(self):
        """No liquidation when price is far from liq level."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)

        candle = Candle(timestamp=1000, open=98, high=102, low=95, close=99, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is False
        assert a.get_position("BTC") is not None

    def test_no_liquidation_at_1x(self):
        """1x leverage should never trigger liquidation."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0, "test", leverage=1.0)

        candle = Candle(timestamp=1000, open=50, high=55, low=10, close=20, volume=100)
        result = a.check_liquidation("BTC", candle)
        assert result is False


class TestFundingRate:
    def test_apply_funding_deducts_from_cash(self):
        """Funding rate should deduct cost from cash."""
        a = _adapter(capital=1000)
        a.set_current_price("BTC", 100.0)
        a.place_order("BTC", "BUY", "MARKET", 0, 100.0,
                      "test", leverage=5.0, maintenance_margin_rate=0.005)
        pos = a.get_position("BTC")
        # qty = 50, price = 100, rate = 0.0001 → cost = 50 * 100 * 0.0001 = 0.5
        cost = a.apply_funding("BTC", 100.0, 0.0001)
        assert cost == pytest.approx(0.5, rel=0.01)
        pos_after = a.get_position("BTC")
        assert pos_after.funding_paid == pytest.approx(0.5, rel=0.01)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_paper_leverage.py -v`
Expected: FAIL — methods don't exist.

**Step 3: Implement leverage in PaperTradingAdapter**

Modify `backend/live/adapters/paper_adapter.py`:

1. **Update `place_order()` signature** to accept optional `leverage` and `maintenance_margin_rate`:
```python
def place_order(self, symbol, side, order_type, quantity, price=0.0,
                reason="", leverage=1.0, maintenance_margin_rate=0.005):
```

2. **Update `_fill_buy()` and `_fill_short_open()`** to:
   - Accept `leverage` and `maintenance_margin_rate` params
   - When `leverage > 1.0`: quantity = (cash * leverage) / fill_price (if quantity==0, auto-size)
   - Set position.leverage, position.margin_used, position.liquidation_price
   - LONG liq: `fill_price * (1 - 1/leverage + mmr)`
   - SHORT liq: `fill_price * (1 + 1/leverage - mmr)`

3. **Add `check_liquidation()` method**:
```python
def check_liquidation(self, symbol: str, candle: Candle) -> bool:
    """Check if position should be liquidated. Returns True if liquidated."""
    with self._lock:
        pos = self._positions.get(symbol)
        if not pos or pos.leverage <= 1.0 or pos.liquidation_price <= 0:
            return False

        triggered = False
        if pos.side == "LONG" and candle.low <= pos.liquidation_price:
            triggered = True
        elif pos.side == "SHORT" and candle.high >= pos.liquidation_price:
            triggered = True

        if triggered:
            self._liquidate(symbol, pos)
            return True
        return False

def _liquidate(self, symbol: str, pos):
    """Execute liquidation — margin is lost."""
    pos.exit_price = pos.liquidation_price
    pos.exit_time = int(time.time() * 1000)
    pos.realized_pnl = -pos.margin_used
    pos.unrealized_pnl = 0.0
    pos.status = "liquidated"
    self._closed_positions.append(pos)
    del self._positions[symbol]
    self._cash = 0.0
    logger.warning(f"LIQUIDATED {pos.side} {symbol} at {pos.liquidation_price}")
```

4. **Add `apply_funding()` method**:
```python
def apply_funding(self, symbol: str, current_price: float,
                  funding_rate: float) -> float:
    """Apply funding rate to position. Returns cost deducted."""
    with self._lock:
        pos = self._positions.get(symbol)
        if not pos or pos.leverage <= 1.0:
            return 0.0
        cost = pos.quantity * current_price * funding_rate
        pos.funding_paid += cost
        self._cash -= cost
        return cost
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_paper_leverage.py -v`
Expected: All PASS.

**Step 5: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All pass (including existing paper adapter tests).

**Step 6: Commit**

```bash
git add backend/live/adapters/paper_adapter.py backend/tests/test_paper_leverage.py
git commit -m "feat: add leverage support to PaperTradingAdapter"
```

---

### Task 4: Engine — `realtime` Mode

**Depends on:** Task 1 (WebSocket feed), Task 3 (adapter leverage)
**Files:**
- Modify: `backend/live/engine.py`
- Test: `backend/tests/test_realtime_engine.py` (create)

**Step 1: Write failing tests**

Create `backend/tests/test_realtime_engine.py`:

```python
"""Tests for LiveTradingEngine realtime mode (with mock feed)."""
import pytest
import queue
import threading
import time
from unittest.mock import MagicMock, patch
from models import Candle, OHLCVData, TradeSignal
from live.engine import LiveTradingEngine
from live.models import TradingSessionConfig
from live.adapters.paper_adapter import PaperTradingAdapter
from live.persistence import TradingPersistence


class MockFeed:
    """Mock WebSocket feed that delivers candles from a list."""
    def __init__(self, candles):
        self._queue = queue.Queue()
        for c in candles:
            self._queue.put(c)
        self._started = False
        self._stopped = False

    def start(self):
        self._started = True

    def stop(self):
        self._stopped = True

    def get_candle(self, timeout=5.0):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_connected(self):
        return self._started and not self._stopped


def _make_candle(i, price):
    return Candle(timestamp=i * 3600000, open=price, high=price + 5,
                  low=price - 5, close=price, volume=1000)


class TestRealtimeMode:
    def test_config_mode_realtime(self):
        """Config should accept 'realtime' mode."""
        config = TradingSessionConfig(mode="realtime")
        assert config.mode == "realtime"

    def test_realtime_processes_candles(self):
        """Engine in realtime mode should process candles from feed."""
        config = TradingSessionConfig(
            mode="realtime", symbol="BTCUSDT", interval="1h",
            strategy_name="RSI",
        )
        adapter = PaperTradingAdapter("test", initial_capital=10000)

        # Create warmup + feed candles
        warmup_candles = [_make_candle(i, 100 + i) for i in range(50)]
        feed_candles = [_make_candle(50 + i, 150 + i) for i in range(3)]

        with patch('live.engine.fetch_klines') as mock_fetch, \
             patch('live.engine.BinanceWebSocketFeed') as mock_ws_cls:

            mock_fetch.return_value = OHLCVData(
                symbol="BTCUSDT", interval="1h", candles=warmup_candles
            )
            mock_feed = MockFeed(feed_candles)
            mock_ws_cls.return_value = mock_feed

            persistence = MagicMock(spec=TradingPersistence)
            engine = LiveTradingEngine(config, adapter, persistence)

            # Run in background thread, stop after processing
            engine.start()
            time.sleep(2)  # Let it process candles
            engine.stop()

            # Verify candles were processed
            assert mock_feed._started
            assert mock_feed._stopped
```

**Step 2: Implement `_run_realtime()` in engine**

Modify `backend/live/engine.py`:

1. **Add imports** at the top:
```python
from live.feeds.binance_ws_feed import BinanceWebSocketFeed
from services.leverage_service import LeverageAssessor
```

2. **Update `_run_loop()`** to handle `"realtime"` mode:
```python
def _run_loop(self) -> None:
    if self.config.mode == "simulated":
        self._run_simulated()
    elif self.config.mode == "polling":
        self._run_polling()
    elif self.config.mode == "realtime":
        self._run_realtime()
```

3. **Add `_run_realtime()`** method:
```python
def _run_realtime(self) -> None:
    """Run with Binance WebSocket real-time data feed."""
    symbol = self.config.symbol
    interval = self.config.interval

    # 1. Warmup: fetch historical candles for strategy indicators
    warmup_end = datetime.datetime.utcnow()
    warmup_start = warmup_end - datetime.timedelta(days=30)  # ~720 1h candles
    warmup_data = fetch_klines(
        symbol, interval,
        warmup_start.strftime("%Y-%m-%d"),
        warmup_end.strftime("%Y-%m-%d"),
    )
    candle_buffer = list(warmup_data.candles)
    logger.info(f"Warmup loaded {len(candle_buffer)} candles")

    # 2. Initialize components
    assessor = LeverageAssessor()
    strategy = self._strategy
    adapter = self._adapter

    # Funding rate tracking
    funding_interval = self._funding_candle_interval(self.config.interval)
    funding_prorate = self._funding_prorate_factor(self.config.interval)
    candle_count = 0

    # 3. Start WebSocket feed
    feed = BinanceWebSocketFeed(
        symbol, interval,
        on_price_update=lambda p: adapter.set_current_price(symbol, p)
    )
    feed.start()
    self._feed = feed  # Store for stop()

    try:
        while not self._stop_event.is_set():
            candle = feed.get_candle(timeout=5.0)
            if candle is None:
                continue

            candle_buffer.append(candle)
            ohlcv = OHLCVData(symbol=symbol, interval=interval, candles=candle_buffer)
            index = len(candle_buffer) - 1

            adapter.set_current_price(symbol, candle.close)

            # --- Risk management checks ---
            # 1. Liquidation check
            liquidated = adapter.check_liquidation(symbol, candle)
            if liquidated:
                logger.warning(f"Position LIQUIDATED on candle {candle.timestamp}")
                candle_count = 0

            # 2. Funding rate (every N candles)
            config = self.config
            if not liquidated and config.funding_rate > 0 and candle_count > 0:
                if funding_interval > 0 and candle_count % funding_interval == 0:
                    cost = adapter.apply_funding(
                        symbol, candle.close,
                        config.funding_rate * funding_prorate
                    )
                    if cost > 0:
                        logger.info(f"Funding paid: ${cost:.4f}")

            # --- Strategy signal ---
            signal = strategy.generate_signal(ohlcv, index)
            if signal and not liquidated:
                self._process_signal_with_leverage(
                    signal, candle, ohlcv, index, assessor
                )

            # --- Record equity ---
            try:
                account = adapter.get_account_state()
                self._persistence.save_equity_snapshot(
                    self.config.session_id, account
                )
            except Exception as e:
                logger.error(f"Equity snapshot error: {e}")

            candle_count += 1

    finally:
        feed.stop()
```

4. **Add `_process_signal_with_leverage()`** method:
```python
def _process_signal_with_leverage(self, signal, candle, ohlcv, index, assessor):
    """Process signal with leverage assessment."""
    config = self.config
    symbol = config.symbol
    adapter = self._adapter

    # Determine leverage
    side = "LONG" if signal.signal_type in ("BUY",) else "SHORT"
    if config.leverage_mode == "dynamic":
        assessed = assessor.assess(ohlcv, index, side, config.max_leverage)
    else:
        assessed = config.fixed_leverage
    final_leverage = assessor.resolve_leverage(
        signal.leverage, assessed, config.leverage_mode,
        config.fixed_leverage, config.max_leverage
    )

    # Use existing _process_signal with leverage info
    # Delegate to existing order logic
    if signal.signal_type == "BUY":
        pos = adapter.get_position(symbol)
        if pos and pos.side == "SHORT":
            adapter.place_order(symbol, "SHORT_CLOSE", "MARKET", pos.quantity,
                                candle.close, "Closing SHORT for BUY")
        if not pos or pos.side == "SHORT":
            adapter.place_order(symbol, "BUY", "MARKET", 0, candle.close,
                                signal.reason, leverage=final_leverage,
                                maintenance_margin_rate=config.maintenance_margin_rate)
    elif signal.signal_type == "SELL":
        pos = adapter.get_position(symbol)
        if pos and pos.side == "LONG":
            adapter.place_order(symbol, "SELL", "MARKET", pos.quantity,
                                candle.close, signal.reason)
    elif signal.signal_type == "SHORT":
        pos = adapter.get_position(symbol)
        if pos and pos.side == "LONG":
            adapter.place_order(symbol, "SELL", "MARKET", pos.quantity,
                                candle.close, "Closing LONG for SHORT")
        if not pos or pos.side == "LONG":
            adapter.place_order(symbol, "SHORT_OPEN", "MARKET", 0, candle.close,
                                signal.reason, leverage=final_leverage,
                                maintenance_margin_rate=config.maintenance_margin_rate)
    elif signal.signal_type == "COVER":
        pos = adapter.get_position(symbol)
        if pos and pos.side == "SHORT":
            adapter.place_order(symbol, "SHORT_CLOSE", "MARKET", pos.quantity,
                                candle.close, signal.reason)
```

5. **Add funding helpers** (same as backtest engine, reuse):
```python
@staticmethod
def _funding_candle_interval(interval: str) -> int:
    intervals = {"1m": 480, "5m": 96, "15m": 32, "30m": 16,
                 "1h": 8, "2h": 4, "4h": 2, "8h": 1, "12h": 1, "1d": 1}
    return intervals.get(interval, 8)

@staticmethod
def _funding_prorate_factor(interval: str) -> float:
    factors = {"8h": 1.0, "12h": 1.5, "1d": 3.0}
    return factors.get(interval, 1.0)
```

6. **Update `stop()` method** to also stop the feed:
```python
def stop(self):
    self._stop_event.set()
    if hasattr(self, '_feed') and self._feed:
        self._feed.stop()
    # ... rest of existing stop logic
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_realtime_engine.py -v`
Expected: All PASS.

**Step 4: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add backend/live/engine.py backend/tests/test_realtime_engine.py
git commit -m "feat: add realtime mode to LiveTradingEngine with WebSocket feed"
```

---

### Task 5: API Deploy Updates

**Depends on:** Task 4
**Files:**
- Modify: `backend/app.py`
- No new tests (smoke test via curl)

**Step 1: Update deploy handler in `backend/app.py`**

Find the `/api/paper/deploy` handler (around line 306). Add parsing of new fields:

```python
config = TradingSessionConfig(
    symbol=data.get("symbol", "BTCUSDT"),
    interval=data.get("interval", "1h"),
    strategy_name=data.get("strategy_name", "RSI"),
    strategy_params=data.get("strategy_params", {}),
    initial_capital=float(data.get("initial_capital", 10000)),
    commission_rate=float(data.get("commission_rate", 0.001)),
    slippage_rate=float(data.get("slippage_rate", 0.0005)),
    data_start_date=data.get("data_start_date", "2024-01-01"),
    data_end_date=data.get("data_end_date", "2025-01-01"),
    tick_interval_seconds=float(data.get("tick_interval_seconds", 1.0)),
    mode=data.get("mode", "simulated"),
    # Leverage params (new)
    max_leverage=float(data.get("max_leverage", 10.0)),
    leverage_mode=data.get("leverage_mode", "dynamic"),
    fixed_leverage=float(data.get("fixed_leverage", 1.0)),
    funding_rate=float(data.get("funding_rate", 0.0001)),
    maintenance_margin_rate=float(data.get("maintenance_margin_rate", 0.005)),
    stop_loss_pct=float(data.get("stop_loss_pct", 0.0)),
    take_profit_pct=float(data.get("take_profit_pct", 0.0)),
)
```

**Step 2: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All pass.

**Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat: parse leverage params in paper trading deploy API"
```

---

### Task 6: Web UI — Live Monitor Tab

**Depends on:** Task 5
**Files:**
- Modify: `frontend/index.html`

**Step 1: Add Live Monitor tab**

This task modifies the single `frontend/index.html` file. Per project convention, use CSS `display` toggle + JS mode variable to switch between Backtest and Live Monitor views.

The Live Monitor tab should include:
1. **Status cards** — session status, strategy name, uptime, current equity, leverage
2. **Equity curve** — Plotly line chart auto-refreshing every 10 seconds
3. **Positions table** — open positions with entry price, PnL, leverage, liquidation price
4. **Orders table** — recent 20 orders
5. **Control buttons** — Stop Session, Emergency Close All
6. **Deploy form** — deploy a new realtime session with strategy + leverage params

The subagent implementing this task should:
- Read the current `frontend/index.html` to understand existing tab structure
- Add a new `live-monitor` div alongside the existing backtest content
- Add `setInterval(10000)` to poll `/api/paper/{id}`, `/api/paper/{id}/equity`, `/api/paper/{id}/positions`, `/api/paper/{id}/orders`
- Use Plotly for the equity chart (CDN already loaded)
- Style consistently with the existing dark theme

**Step 2: Manual test**

Run: `cd backend && python app.py`
Open: `http://localhost:8000`
Verify: Live Monitor tab appears and can deploy/monitor sessions.

**Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add Live Monitor tab with real-time paper trading dashboard"
```

---

### Task 7: Integration Test + Validation

**Depends on:** All previous tasks
**Files:**
- Verify all tests pass

**Step 1: Run full test suite**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All 214 existing tests + ~30 new tests pass.

**Step 2: Install dependency**

```bash
pip install websocket-client
```

**Step 3: Manual smoke test with real Binance WebSocket**

```bash
cd backend && python -c "
from live.feeds.binance_ws_feed import BinanceWebSocketFeed
import time

def on_price(p):
    print(f'  Price: {p}')

feed = BinanceWebSocketFeed('btcusdt', '1m', on_price_update=on_price)
feed.start()
print('Waiting for candle...')
time.sleep(10)
print(f'Connected: {feed.is_connected()}')
feed.stop()
print('Done')
"
```

Expected: Should connect and receive price updates within seconds.

**Step 4: Deploy a realtime session**

```bash
cd backend && python app.py &
sleep 2

# Deploy realtime session
curl -X POST http://localhost:8000/api/paper/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "realtime",
    "symbol": "BTCUSDT",
    "interval": "1m",
    "strategy_name": "RSI",
    "max_leverage": 3,
    "leverage_mode": "fixed",
    "fixed_leverage": 2.0
  }'

# Check status after 30 seconds
sleep 30
curl http://localhost:8000/api/paper
```

**Step 5: Push**

```bash
git push
```

---

## Parallel Execution Guide

```
Task 1 (WebSocket Feed) ────────────┐
                                      ├──→ Task 4 (Engine realtime) ──→ Task 5 (API) ──→ Task 6 (UI) ──→ Task 7
Task 2 (Model fields) ──→ Task 3 (Adapter leverage) ─┘
```

**Parallelizable groups:**
- **Wave 1:** Task 1 + Task 2 (independent foundations)
- **Wave 2:** Task 3 (needs Task 2)
- **Wave 3:** Task 4 (needs Task 1 + Task 3)
- **Wave 4:** Task 5 (needs Task 4)
- **Wave 5:** Task 6 (needs Task 5)
- **Wave 6:** Task 7 (final validation)
