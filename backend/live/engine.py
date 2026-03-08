"""
Live Trading Engine - runs strategies on real-time (or simulated) data.

For Phase 1-2, "real-time" means:
  1. Simulated mode: replay historical candles with configurable tick speed
  2. Polling mode: fetch latest candle from Binance REST every interval

The engine runs in a background daemon thread.
Supports LONG and SHORT positions, with optional stop-loss/take-profit.
"""
import threading
import time
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from models import OHLCVData, Candle, TradeSignal
from strategies.registry import StrategyRegistry
from strategies.base_strategy import BaseStrategy
from services.data_service import fetch_klines
from live.models import TradingSessionConfig, AccountState
from live.adapters.base_adapter import ExchangeAdapter
from live.persistence import TradingPersistence

logger = logging.getLogger(__name__)


class LiveTradingEngine:
    """
    Manages a single paper trading session.

    Lifecycle:
        engine = LiveTradingEngine(config, adapter, persistence)
        engine.start()    # spawns background thread
        engine.status()   # returns current state
        engine.stop()     # signals thread to stop, blocks until joined
    """

    def __init__(self, config: TradingSessionConfig, adapter: ExchangeAdapter,
                 persistence: TradingPersistence):
        self.config = config
        self.adapter = adapter
        self.persistence = persistence

        self._strategy: Optional[BaseStrategy] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state = "initialized"  # initialized, running, stopped, error
        self._error_msg = ""
        self._candle_count = 0
        self._signal_count = 0

    @property
    def session_id(self) -> str:
        return self.config.session_id

    def start(self) -> None:
        """Start the trading engine in a background thread."""
        if self._state == "running":
            raise RuntimeError(f"Session {self.session_id} already running")

        self._strategy = StrategyRegistry.create(
            self.config.strategy_name,
            self.config.strategy_params,
        )
        self._stop_event.clear()
        self._state = "running"

        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"live-engine-{self.session_id}",
            daemon=True,
        )
        self._thread.start()
        self.persistence.save_session_state(self.session_id, "running")

    def stop(self) -> None:
        """Signal the engine to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._state = "stopped"

        # Close any open positions
        close_orders = self.adapter.close_all_positions("Session stopped")
        for order in close_orders:
            self.persistence.save_order(order)

        self.persistence.save_session_state(self.session_id, "stopped")

    def status(self) -> Dict[str, Any]:
        """Get current engine status."""
        account = self.adapter.get_account_state()
        positions = self.adapter.get_all_positions()
        return {
            "session_id": self.session_id,
            "state": self._state,
            "error": self._error_msg,
            "config": self.config.to_dict(),
            "candles_processed": self._candle_count,
            "signals_generated": self._signal_count,
            "account": account.to_dict(),
            "open_positions": [p.to_dict() for p in positions],
        }

    # ------------------------------------------------------------------
    # Internal run loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main engine loop. Runs in background thread."""
        try:
            if self.config.mode == "simulated":
                self._run_simulated()
            elif self.config.mode == "polling":
                self._run_polling()
            else:
                raise ValueError(f"Unknown mode: {self.config.mode}")
        except Exception as e:
            self._state = "error"
            self._error_msg = str(e)
            logger.exception(f"Engine {self.session_id} error: {e}")
        finally:
            if self._state == "running":
                self._state = "stopped"
            self.persistence.save_session_state(self.session_id, self._state)

    def _run_simulated(self) -> None:
        """Replay historical data as if live."""
        ohlcv = fetch_klines(
            self.config.symbol,
            self.config.interval,
            self.config.data_start_date,
            self.config.data_end_date,
        )

        if not ohlcv.candles:
            raise RuntimeError("No historical data available")

        for i, candle in enumerate(ohlcv.candles):
            if self._stop_event.is_set():
                break

            # Update market price in adapter
            self.adapter.set_current_price(self.config.symbol, candle.close)
            self._candle_count += 1

            # Generate signal using full ohlcv up to index i
            signal = self._strategy.generate_signal(ohlcv, i)

            if signal is not None:
                self._process_signal(signal, candle)
                self._signal_count += 1

            # Snapshot equity for every candle
            account = self.adapter.get_account_state()
            account.session_id = self.config.session_id
            account.timestamp = candle.timestamp
            self.persistence.save_equity_snapshot(account)

            # Throttle to simulate real-time
            if self.config.tick_interval_seconds > 0:
                time.sleep(self.config.tick_interval_seconds)

    def _run_polling(self) -> None:
        """Poll Binance REST API for new candles."""
        warmup_candles = 200
        interval_seconds = self._interval_to_seconds(self.config.interval)

        while not self._stop_event.is_set():
            try:
                ohlcv = fetch_klines(
                    self.config.symbol,
                    self.config.interval,
                    start_date=self._calculate_start_date(
                        warmup_candles, self.config.interval
                    ),
                    end_date=datetime.now().strftime("%Y-%m-%d"),
                )

                if ohlcv.candles:
                    latest = ohlcv.candles[-1]
                    self.adapter.set_current_price(
                        self.config.symbol, latest.close
                    )
                    self._candle_count += 1

                    index = len(ohlcv.candles) - 1
                    signal = self._strategy.generate_signal(ohlcv, index)

                    if signal is not None:
                        self._process_signal(signal, latest)
                        self._signal_count += 1

                    account = self.adapter.get_account_state()
                    account.session_id = self.config.session_id
                    account.timestamp = latest.timestamp
                    self.persistence.save_equity_snapshot(account)

            except Exception as e:
                logger.error(f"Polling error: {e}")

            self._stop_event.wait(timeout=interval_seconds)

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------

    def _process_signal(self, signal: TradeSignal, candle: Candle) -> None:
        """Translate a strategy signal into adapter orders."""
        position = self.adapter.get_position(self.config.symbol)

        if signal.signal_type == "BUY":
            if position is None:
                # Open LONG
                self._open_long(signal)
            elif position.side == "SHORT":
                # Close SHORT
                self._close_short(position, signal)

        elif signal.signal_type == "SELL":
            if position is not None and position.side == "LONG":
                # Close LONG
                self._close_long(position, signal)

        elif signal.signal_type == "SHORT":
            if position is not None and position.side == "LONG":
                # Close LONG first
                self._close_long(position, signal)
            if self.adapter.get_position(self.config.symbol) is None:
                # Open SHORT
                self._open_short(signal)

        elif signal.signal_type == "COVER":
            if position is not None and position.side == "SHORT":
                # Close SHORT
                self._close_short(position, signal)

    def _open_long(self, signal: TradeSignal) -> None:
        """Open a LONG position."""
        account = self.adapter.get_account_state()
        price = self.adapter.get_current_price(self.config.symbol)
        if price <= 0:
            return
        quantity = account.available_cash / price

        order = self.adapter.place_order(
            symbol=self.config.symbol,
            side="BUY",
            order_type="MARKET",
            quantity=quantity,
            reason=signal.reason,
        )
        self.persistence.save_order(order)
        logger.info(
            f"[{self.session_id}] BUY {order.filled_quantity:.6f} "
            f"{self.config.symbol} @ {order.avg_fill_price:.2f} "
            f"| {signal.reason}"
        )

    def _close_long(self, position, signal: TradeSignal) -> None:
        """Close a LONG position."""
        order = self.adapter.place_order(
            symbol=self.config.symbol,
            side="SELL",
            order_type="MARKET",
            quantity=position.quantity,
            reason=signal.reason,
        )
        self.persistence.save_order(order)
        logger.info(
            f"[{self.session_id}] SELL {order.filled_quantity:.6f} "
            f"{self.config.symbol} @ {order.avg_fill_price:.2f} "
            f"| PnL: {position.realized_pnl:.2f} | {signal.reason}"
        )

    def _open_short(self, signal: TradeSignal) -> None:
        """Open a SHORT position."""
        account = self.adapter.get_account_state()
        price = self.adapter.get_current_price(self.config.symbol)
        if price <= 0:
            return
        quantity = account.available_cash / price

        order = self.adapter.place_order(
            symbol=self.config.symbol,
            side="SHORT_OPEN",
            order_type="MARKET",
            quantity=quantity,
            reason=signal.reason,
        )
        self.persistence.save_order(order)
        logger.info(
            f"[{self.session_id}] SHORT {order.filled_quantity:.6f} "
            f"{self.config.symbol} @ {order.avg_fill_price:.2f} "
            f"| {signal.reason}"
        )

    def _close_short(self, position, signal: TradeSignal) -> None:
        """Close a SHORT position."""
        order = self.adapter.place_order(
            symbol=self.config.symbol,
            side="SHORT_CLOSE",
            order_type="MARKET",
            quantity=position.quantity,
            reason=signal.reason,
        )
        self.persistence.save_order(order)
        logger.info(
            f"[{self.session_id}] COVER {order.filled_quantity:.6f} "
            f"{self.config.symbol} @ {order.avg_fill_price:.2f} "
            f"| PnL: {position.realized_pnl:.2f} | {signal.reason}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _interval_to_seconds(interval: str) -> float:
        """Convert a Binance-style interval string to seconds."""
        units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
        num = int(interval[:-1])
        unit = interval[-1]
        return num * units.get(unit, 3600)

    @staticmethod
    def _calculate_start_date(candles_needed: int, interval: str) -> str:
        """Calculate how far back to fetch for warmup candles."""
        seconds = LiveTradingEngine._interval_to_seconds(interval)
        total_seconds = candles_needed * seconds
        start = datetime.now().timestamp() - total_seconds
        return datetime.fromtimestamp(start).strftime("%Y-%m-%d")
