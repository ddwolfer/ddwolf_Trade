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
    entry_reason: str = ""
    exit_reason: str = ""

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
