# Real-Time Paper Trading — Design Document

> **Date:** 2026-03-09
> **Status:** Approved
> **Goal:** Connect the paper trading engine to Binance real-time WebSocket data for live strategy simulation with leverage support and a Web UI monitoring dashboard.

---

## 1. Requirements

| Requirement | Decision |
|-------------|----------|
| Data source | Binance WebSocket (kline stream, no API Key needed) |
| Trading pair | BTCUSDT (single pair focus) |
| K-line interval | Configurable at deploy time (1m, 5m, 15m, 1h, 4h, etc.) |
| Leverage | Yes — dynamic leverage, liquidation, funding rate (reuse backtest engine's system) |
| Monitoring | Web UI dashboard (live equity curve, positions, orders) + REST API |
| Dependencies | `websocket-client` (single new pip package) |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  SessionManager.deploy(mode="realtime")                     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  LiveTradingEngine (daemon thread)                   │    │
│  │                                                       │    │
│  │  ┌───────────────────┐    ┌───────────────────────┐  │    │
│  │  │ BinanceWSFeed     │    │ candle_buffer (list)   │  │    │
│  │  │ (WebSocket thread)│    │ + OHLCVData            │  │    │
│  │  │                   │    └───────────────────────┘  │    │
│  │  │ btcusdt@kline_1h  │              │                │    │
│  │  │   │               │              ▼                │    │
│  │  │   ▼               │    ┌───────────────────────┐  │    │
│  │  │ is_closed?        │    │ Strategy.generate_     │  │    │
│  │  │  ├── Yes ──────────────→  signal(ohlcv, i)     │  │    │
│  │  │  │  queue.put()   │    └───────────┬───────────┘  │    │
│  │  │  │                │                │               │    │
│  │  │  └── No ──────────────→ adapter.set_current_price │    │
│  │  │     (price update)│                │               │    │
│  │  └───────────────────┘                ▼               │    │
│  │                            ┌──────────────────────┐   │    │
│  │                            │ LeverageAssessor     │   │    │
│  │                            │ → assess() → order   │   │    │
│  │                            └──────────┬───────────┘   │    │
│  │                                       ▼               │    │
│  │                            ┌──────────────────────┐   │    │
│  │                            │ PaperTradingAdapter  │   │    │
│  │                            │ (with leverage)      │   │    │
│  │                            │ - Liquidation check  │   │    │
│  │                            │ - Funding rate       │   │    │
│  │                            │ - Margin tracking    │   │    │
│  │                            └──────────┬───────────┘   │    │
│  │                                       ▼               │    │
│  │                            ┌──────────────────────┐   │    │
│  │                            │ SQLite Persistence   │   │    │
│  │                            │ orders, positions,   │   │    │
│  │                            │ equity snapshots     │   │    │
│  │                            └──────────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Web UI (frontend/index.html)                        │    │
│  │  Live Monitor tab — auto-refresh every 10s           │    │
│  │  - Status card (strategy, equity, leverage, uptime)  │    │
│  │  - Equity curve (Plotly line chart)                   │    │
│  │  - Positions table (entry, PnL, liq price)           │    │
│  │  - Orders table (last 20 trades)                     │    │
│  │  - Stop / Emergency Close buttons                    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Component Design

### 3.1 BinanceWebSocketFeed

**File:** `backend/live/feeds/binance_ws_feed.py` (new)

**Responsibilities:**
- Connect to `wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}`
- Parse kline events into `Candle` objects
- On `kline.is_closed == True` → put completed Candle into `queue.Queue`
- On `kline.is_closed == False` → call `on_price_update(price)` callback for live price
- Auto-reconnect with exponential backoff (5s → 10s → 20s → max 60s, 10 retries)
- On reconnect, backfill missed candles via REST API

**Interface:**
```python
class BinanceWebSocketFeed:
    def __init__(self, symbol: str, interval: str,
                 on_price_update: Optional[Callable[[float], None]] = None):
        self._queue = queue.Queue()
        ...

    def start(self) -> None:
        """Start WebSocket in background daemon thread."""

    def stop(self) -> None:
        """Close WebSocket connection and stop thread."""

    def get_candle(self, timeout: float = 5.0) -> Optional[Candle]:
        """Block until a closed candle is available, or timeout."""

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
```

**WebSocket Message Format (Binance):**
```json
{
  "e": "kline",
  "k": {
    "t": 1672531200000,   // kline start time (ms)
    "T": 1672534799999,   // kline close time (ms)
    "s": "BTCUSDT",
    "i": "1h",
    "o": "42000.00",      // open
    "h": "42500.00",      // high
    "l": "41800.00",      // low
    "c": "42300.00",      // close
    "v": "1234.56",       // volume
    "x": true             // is this kline closed?
  }
}
```

### 3.2 LiveTradingEngine — `realtime` Mode

**File:** `backend/live/engine.py` (modify)

**New mode:** `_run_realtime()` alongside existing `_run_simulated()` and `_run_polling()`.

**Startup:**
1. Fetch 200 warmup candles via `data_service.fetch_klines()` (REST API)
2. Initialize `LeverageAssessor`
3. Start `BinanceWebSocketFeed`
4. Enter main loop

**Main Loop:**
```python
def _run_realtime(self):
    warmup = data_service.fetch_klines(symbol, interval, warmup_start, now)
    candle_buffer = list(warmup.candles)
    assessor = LeverageAssessor()

    feed = BinanceWebSocketFeed(
        symbol, interval,
        on_price_update=lambda p: adapter.set_current_price(symbol, p)
    )
    feed.start()

    candle_count_since_entry = 0

    while not self._stop_event.is_set():
        candle = feed.get_candle(timeout=5.0)
        if candle is None:
            continue

        candle_buffer.append(candle)
        ohlcv = OHLCVData(symbol, interval, candle_buffer)
        index = len(candle_buffer) - 1

        adapter.set_current_price(symbol, candle.close)

        # --- Leverage checks (if position open) ---
        # 1. Check liquidation
        # 2. Apply funding rate (every 8h)
        # 3. Check SL/TP
        self._check_risk_management(candle, candle_count_since_entry)

        # --- Strategy signal ---
        signal = strategy.generate_signal(ohlcv, index)
        if signal:
            self._process_signal_with_leverage(signal, candle, ohlcv, index, assessor)

        # --- Record equity ---
        persistence.save_equity_snapshot(adapter.get_account_state())
        candle_count_since_entry += 1

    feed.stop()
```

**Signal Processing with Leverage:**
```python
def _process_signal_with_leverage(self, signal, candle, ohlcv, index, assessor):
    config = self.config
    side = "LONG" if signal.signal_type in ("BUY",) else "SHORT"

    # Determine leverage
    assessed = assessor.assess(ohlcv, index, side, config.max_leverage)
    final_leverage = assessor.resolve_leverage(
        signal.leverage, assessed, config.leverage_mode,
        config.fixed_leverage, config.max_leverage
    )

    # Calculate position sizing
    margin = adapter.available_cash
    quantity = (margin * final_leverage) / candle.close

    # Place order with leverage metadata
    order = adapter.place_order(symbol, signal.signal_type, "MARKET",
                                 quantity, candle.close, signal.reason,
                                 leverage=final_leverage)
```

### 3.3 PaperTradingAdapter — Leverage Upgrade

**File:** `backend/live/adapters/paper_adapter.py` (modify)

**New capabilities:**
- `Position` model gains: `leverage`, `margin_used`, `liquidation_price`, `funding_paid`
- `place_order()` accepts optional `leverage` parameter
- `check_liquidation(candle)` — engine calls per candle, returns True if liquidated
- `apply_funding(candle, funding_rate, prorate)` — engine calls at funding intervals
- Equity calc: `cash + sum(margin + unrealized_pnl - funding_paid)` when leveraged

**Liquidation logic (same as backtest engine):**
```python
def check_liquidation(self, symbol: str, candle: Candle) -> bool:
    pos = self._positions.get(symbol)
    if not pos or pos.leverage <= 1.0:
        return False
    if pos.side == "LONG" and candle.low <= pos.liquidation_price:
        self._liquidate(symbol, pos.liquidation_price)
        return True
    if pos.side == "SHORT" and candle.high >= pos.liquidation_price:
        self._liquidate(symbol, pos.liquidation_price)
        return True
    return False
```

### 3.4 TradingSessionConfig Updates

**File:** `backend/live/models.py` (modify)

Add leverage fields to `TradingSessionConfig`:
```python
max_leverage: float = 10.0
leverage_mode: str = "dynamic"
fixed_leverage: float = 1.0
funding_rate: float = 0.0001
maintenance_margin_rate: float = 0.005
stop_loss_pct: float = 0.0
take_profit_pct: float = 0.0
```

### 3.5 Web UI — Live Monitor

**File:** `frontend/index.html` (modify)

Add a "Live Monitor" tab (CSS toggle + JS mode variable, per project convention).

**Layout:**
```
┌────────────────────────────────────────────┐
│  [Backtest]  [Live Monitor]   ← Tab switch │
├────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Status   │ │ Equity   │ │ Leverage │   │
│  │ Running  │ │ $10,523  │ │ 3.5x     │   │
│  │ 2h 15m   │ │ +5.23%   │ │ dynamic  │   │
│  └──────────┘ └──────────┘ └──────────┘   │
├────────────────────────────────────────────┤
│  Equity Curve (Plotly line chart)          │
│  ┌────────────────────────────────────┐    │
│  │  📈 real-time equity line          │    │
│  └────────────────────────────────────┘    │
├─────────────────────┬──────────────────────┤
│  Open Positions     │  Recent Orders       │
│  ┌───────────────┐  │  ┌────────────────┐  │
│  │ BTCUSDT LONG  │  │  │ BUY  3x $42.1k │  │
│  │ Entry: $42.1k │  │  │ SELL 1x $43.2k │  │
│  │ PnL: +$250    │  │  │ SHORT 5x $41k  │  │
│  │ Liq: $33.8k   │  │  │ ...            │  │
│  └───────────────┘  │  └────────────────┘  │
├─────────────────────┴──────────────────────┤
│  [Stop Session]  [Emergency Close All]     │
└────────────────────────────────────────────┘
```

**Refresh mechanism:** `setInterval(10000)` polls REST API every 10 seconds. No WebSocket needed for frontend.

---

## 4. API Changes

### Deploy Endpoint Update

```
POST /api/paper/deploy
```

New/updated fields:
```json
{
  "mode": "realtime",
  "symbol": "BTCUSDT",
  "interval": "1h",
  "strategy_name": "Trend Surfer",
  "strategy_params": {},
  "initial_capital": 10000,
  "max_leverage": 5,
  "leverage_mode": "dynamic",
  "fixed_leverage": 1.0,
  "funding_rate": 0.0001,
  "maintenance_margin_rate": 0.005,
  "stop_loss_pct": 5.0,
  "take_profit_pct": 0.0
}
```

### Status Endpoint Enhancement

`GET /api/paper/{id}` adds:
```json
{
  "ws_connected": true,
  "current_price": 42300.50,
  "current_leverage": 3.5,
  "liquidation_price": 33800.00,
  "funding_paid": 1.25,
  "candles_processed": 156
}
```

---

## 5. New Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `websocket-client` | ≥1.0 | Binance WebSocket connection |

Install: `pip install websocket-client`

---

## 6. File Changes Summary

| Action | File | Description |
|--------|------|-------------|
| Create | `backend/live/feeds/__init__.py` | Package init |
| Create | `backend/live/feeds/binance_ws_feed.py` | WebSocket data feed |
| Modify | `backend/live/engine.py` | Add `_run_realtime()` mode |
| Modify | `backend/live/adapters/paper_adapter.py` | Add leverage support |
| Modify | `backend/live/models.py` | Add leverage fields to config |
| Modify | `backend/app.py` | Parse new deploy params |
| Modify | `frontend/index.html` | Add Live Monitor tab |
| Create | `backend/tests/test_ws_feed.py` | WebSocket feed unit tests |
| Create | `backend/tests/test_realtime_engine.py` | Realtime engine tests |
| Create | `backend/tests/test_paper_leverage.py` | Paper adapter leverage tests |

---

## 7. Testing Strategy

1. **Unit tests:** WebSocket message parsing, candle queue, reconnect logic (mock WebSocket)
2. **Unit tests:** Paper adapter leverage (liquidation, funding, margin calculation)
3. **Integration test:** Engine realtime mode with mock feed (simulated candle stream)
4. **Manual test:** Deploy with real Binance WebSocket, verify signal generation and order execution
5. **Backward compat:** Existing `simulated` and `polling` modes still work unchanged

---

## 8. Backward Compatibility

- `mode="simulated"` and `mode="polling"` are unchanged
- New leverage fields in `TradingSessionConfig` have defaults matching 1x (no leverage)
- Paper adapter upgrade is purely additive (new methods, no API breaks)
- Web UI adds a new tab; existing backtest tab is unaffected

---

## 9. Known Limitations

1. **Single pair only** — designed for BTCUSDT; multi-pair requires separate sessions
2. **No order book depth** — we simulate fills at close price + slippage, not real order book
3. **No partial fills** — all orders fill immediately at market price
4. **WebSocket dependency** — requires internet connection to Binance
5. **Frontend polling** — UI updates every 10s, not true real-time push
