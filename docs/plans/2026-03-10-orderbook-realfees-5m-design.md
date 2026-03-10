# Design: Real Fees + 5m Research + Order Book Integration

- **Date:** 2026-03-10
- **Status:** Approved
- **Approach:** Plan B — Extended strategy interface with MarketContext

## Background

From 1m Scalp Sniper research, we found that transaction costs (0.30% round-trip) are the primary blocker for profitability on short timeframes. The user's actual Binance fees are much lower:
- Maker (limit order): 0.018% (with BNB discount)
- Taker: 0.045% (with BNB discount)
- User primarily uses Maker orders

Additionally, the user wants Order Book (L2) data as real-time trading signals.

## 4 Phases

### P1: Re-test with Real Commission (0.018%)
- No code changes — `BacktestConfig` already supports `commission_rate` and `slippage_rate`
- Pass `commission_rate=0.00018, slippage_rate=0` for Maker scenario
- Re-test Scalp Sniper and all strategies on 1m + 5m
- Expected: dramatically better results (round-trip cost drops from 0.30% to 0.036%)

### P2: Research 5m Strategy
- Use `/research` flow on BTCUSDT 5m with real Maker fees
- 5m avg candle range (~0.20%) vs cost (0.036%) = **5.5x ratio** (vs 0.25x on 1m with old fees)
- Much more viable for profitable trading

### P3: Order Book Data Pipeline

**3a. Data Models** — `backend/models/__init__.py`
```python
@dataclass
class OrderBookLevel:
    price: float
    quantity: float

@dataclass
class OrderBook:
    symbol: str
    timestamp: int
    bids: List[OrderBookLevel]  # descending by price
    asks: List[OrderBookLevel]  # ascending by price

    @property
    def best_bid(self) -> float
    @property
    def best_ask(self) -> float
    @property
    def spread_pct(self) -> float
    @property
    def mid_price(self) -> float

@dataclass
class MarketContext:
    """Passed to generate_signal_v2 — extensible container for real-time data"""
    orderbook: Optional[OrderBook] = None
    recent_trades: Optional[List[dict]] = None
    funding_rate: Optional[float] = None
```

**3b. Binance Depth WebSocket Feed** — `backend/live/feeds/binance_depth_feed.py`
- Connect to `wss://stream.binance.com:9443/ws/{symbol}@depth20@100ms`
- Parse bids/asks into OrderBook model
- Thread-safe access to latest snapshot via `get_orderbook()`
- Auto-reconnect with exponential backoff (follow kline feed pattern)
- Partial depth updates (Binance sends top 20 levels every 100ms)

**3c. REST Depth API** — `backend/services/data_service.py`
- `fetch_depth(symbol, limit=20)` → calls `GET /api/v3/depth`
- Returns OrderBook model
- Cached for 1 second (depth data changes constantly)

**3d. HTTP Endpoints** — `backend/app.py`
- `GET /api/data/{symbol}/depth` — snapshot order book (for frontend)
- `GET /api/data/{symbol}/depth?levels=5` — configurable depth

### P4: Strategy Interface Extension

**4a. BaseStrategy v2** — `backend/strategies/base_strategy.py`
```python
class BaseStrategy(ABC):
    def generate_signal(self, ohlcv, index) -> Optional[TradeSignal]:
        """Original interface — OHLCV only"""
        ...

    def generate_signal_v2(self, ohlcv, index, context: MarketContext) -> Optional[TradeSignal]:
        """Extended interface — OHLCV + real-time context.
        Default: delegates to generate_signal() for backward compat.
        Override this in OB-aware strategies."""
        return self.generate_signal(ohlcv, index)

    @property
    def uses_market_context(self) -> bool:
        """True if strategy overrides generate_signal_v2"""
        return type(self).generate_signal_v2 is not BaseStrategy.generate_signal_v2
```

**4b. Engine Changes**
- `StrategyEngine.run()` (backtest): Call `generate_signal_v2(ohlcv, i, MarketContext())` — empty context for backtests
- `LiveTradingEngine`: Pass real OrderBook in MarketContext from DepthFeed
- Backward compatible: old strategies' `generate_signal_v2` delegates to `generate_signal`

**4c. Order Book Indicators** — `backend/services/orderbook_indicators.py`
```python
def bid_ask_imbalance(ob: OrderBook, levels: int = 5) -> float:
    """(bid_vol - ask_vol) / (bid_vol + ask_vol), range [-1, 1]"""

def depth_ratio(ob: OrderBook, levels: int = 10) -> float:
    """Total bid volume / total ask volume at top N levels"""

def wall_detection(ob: OrderBook, mult: float = 5.0) -> dict:
    """Detect large orders that are mult× average size"""

def spread_bps(ob: OrderBook) -> float:
    """Spread in basis points"""

def weighted_mid_price(ob: OrderBook) -> float:
    """Volume-weighted mid price"""

def cumulative_delta(ob: OrderBook, price_range_pct: float = 0.5) -> float:
    """Net order flow within price_range_pct of mid price"""
```

**4d. First OB-Aware Strategy** — will be designed during /research phase
- Combine OHLCV signals with OB confirmation
- Example: only take BUY if `bid_ask_imbalance > 0.2`
- Graceful fallback when `context.orderbook is None` (backtest mode)

## Order Book in Backtesting

Challenge: No historical OB data available.

**Solution (pragmatic):**
1. In backtest mode, `MarketContext.orderbook = None`
2. OB-aware strategies must handle `None` gracefully — use OHLCV-only signals as fallback
3. Future: add OB snapshot recording for paper trading sessions → build historical OB dataset over time
4. Future: synthetic OB generation (not reliable, low priority)

## Architecture Flow

```
=== LIVE MODE ===
Binance WS ─── KlineFeed ──→ OHLCV ──┐
           └── DepthFeed ──→ OB    ──┤→ MarketContext → strategy.generate_signal_v2()
                                      │
=== BACKTEST MODE ===                 │
Historical DB → OHLCV ───────────────┤→ MarketContext(orderbook=None) → strategy.generate_signal_v2()
```

## Implementation Order

1. P1: Re-test with real fees (API calls, no code changes)
2. P3a: Add OrderBook, OrderBookLevel, MarketContext models
3. P4a: Extend BaseStrategy with generate_signal_v2
4. P4b: Update StrategyEngine to use generate_signal_v2
5. P3b: Create BinanceDepthFeed WebSocket
6. P3c: Add fetch_depth() to data_service
7. P3d: Add /api/data/{symbol}/depth endpoint
8. P4c: Create orderbook_indicators.py
9. P4b: Update LiveTradingEngine to pass MarketContext
10. P4d: Create first OB-aware strategy (combined with P2 research)
11. P2: Research 5m strategy with real fees + OB signals (if live mode)

## Testing Strategy

- Unit tests for OrderBook model properties
- Unit tests for each OB indicator function
- Unit tests for BaseStrategy v2 backward compatibility
- Integration test: StrategyEngine with v2 interface + old strategies still work
- WebSocket feed: mock-based tests (follow existing ws_feed test pattern)
- API endpoint tests for /depth

## Files to Create/Modify

### New Files:
- `backend/live/feeds/binance_depth_feed.py`
- `backend/services/orderbook_indicators.py`

### Modified Files:
- `backend/models/__init__.py` — add OrderBook, OrderBookLevel, MarketContext
- `backend/strategies/base_strategy.py` — add generate_signal_v2, uses_market_context
- `backend/services/strategy_engine.py` — use generate_signal_v2 in run()
- `backend/services/data_service.py` — add fetch_depth()
- `backend/app.py` — add /api/data/{symbol}/depth endpoint
- `backend/live/engine.py` — pass MarketContext to strategy

### Test Files:
- `backend/tests/test_orderbook_models.py`
- `backend/tests/test_orderbook_indicators.py`
- `backend/tests/test_depth_feed.py`
- `backend/tests/test_strategy_v2_compat.py`
