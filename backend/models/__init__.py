from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid


@dataclass
class Candle:
    timestamp: int  # ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    count: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class OHLCVData:
    symbol: str
    interval: str
    candles: List[Candle]

    def closes(self) -> List[float]:
        return [c.close for c in self.candles]

    def highs(self) -> List[float]:
        return [c.high for c in self.candles]

    def lows(self) -> List[float]:
        return [c.low for c in self.candles]

    def volumes(self) -> List[float]:
        return [c.volume for c in self.candles]

    def timestamps(self) -> List[int]:
        return [c.timestamp for c in self.candles]


@dataclass
class TradeSignal:
    timestamp: int
    signal_type: str  # "BUY" or "SELL"
    price: float
    reason: str = ""
    leverage: Optional[float] = None  # Strategy-suggested leverage (None = use Assessor)


@dataclass
class Trade:
    entry_time: int
    entry_price: float
    exit_time: int = 0
    exit_price: float = 0.0
    quantity: float = 0.0
    side: str = "LONG"  # LONG or SHORT
    profit_loss: float = 0.0
    return_pct: float = 0.0
    status: str = "OPEN"  # OPEN or CLOSED
    exit_type: str = "SIGNAL"  # SIGNAL, STOP_LOSS, TAKE_PROFIT, FORCED_CLOSE
    entry_reason: str = ""
    exit_reason: str = ""
    leverage: float = 1.0            # Actual leverage used
    margin_used: float = 0.0         # Margin amount locked
    liquidation_price: float = 0.0   # Forced liquidation price
    funding_paid: float = 0.0        # Cumulative funding paid

    def to_dict(self):
        d = asdict(self)
        d["entry_time_str"] = datetime.fromtimestamp(self.entry_time / 1000).strftime("%Y-%m-%d %H:%M")
        if self.exit_time:
            d["exit_time_str"] = datetime.fromtimestamp(self.exit_time / 1000).strftime("%Y-%m-%d %H:%M")
            d["holding_hours"] = (self.exit_time - self.entry_time) / 3600000
        return d


@dataclass
class BacktestConfig:
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    initial_capital: float = 10000.0
    strategy_name: str = "RSI"
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    commission_rate: float = 0.001  # 0.1%
    slippage_rate: float = 0.0005  # 0.05%
    stop_loss_pct: float = 0.0  # 0 = disabled. e.g. 5.0 = exit if price moves 5% against position
    take_profit_pct: float = 0.0  # 0 = disabled. e.g. 10.0 = exit if price moves 10% in favor
    trailing_stop_atr_period: int = 0  # 0 = disabled, e.g. 14
    trailing_stop_atr_mult: float = 3.0  # ATR x mult = trailing distance
    # Leverage / contract settings
    max_leverage: float = 10.0              # Hard cap (1.0~20.0)
    leverage_mode: str = "dynamic"          # "dynamic"=AI assess, "fixed"=constant
    fixed_leverage: float = 1.0             # Used when leverage_mode="fixed"
    funding_rate: float = 0.0001            # Per 8h (0.01%), ~10.95% annualized
    maintenance_margin_rate: float = 0.005  # 0.5% (Binance default)


@dataclass
class BacktestResult:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    config: Optional[BacktestConfig] = None
    trades: List[Trade] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    equity_curve: List[float] = field(default_factory=list)
    equity_timestamps: List[int] = field(default_factory=list)
    drawdown_curve: List[float] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, error
    error: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "config": asdict(self.config) if self.config else None,
            "trades": [t.to_dict() for t in self.trades],
            "metrics": self.metrics,
            "equity_curve": self.equity_curve,
            "equity_timestamps": self.equity_timestamps,
            "drawdown_curve": self.drawdown_curve,
        }


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
    Extensible container -- add fields as new data sources are integrated."""
    orderbook: Optional[OrderBook] = None
    recent_trades: Optional[List[dict]] = None
    funding_rate: Optional[float] = None
