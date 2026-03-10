"""
Live Trading Engine - runs strategies on real-time (or simulated) data.

Supports three modes:
  1. Simulated mode: replay historical candles with configurable tick speed
  2. Polling mode: fetch latest candle from Binance REST every interval
  3. Realtime mode: consume closed candles from Binance WebSocket feed

The engine runs in a background daemon thread.
Supports LONG and SHORT positions, with optional stop-loss/take-profit.
"""
import datetime as dt_module
import threading
import time
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from models import OHLCVData, Candle, TradeSignal, MarketContext
from strategies.registry import StrategyRegistry
from strategies.base_strategy import BaseStrategy
from services.data_service import fetch_klines
from live.models import TradingSessionConfig, AccountState
from live.adapters.base_adapter import ExchangeAdapter
from live.persistence import TradingPersistence
from live.feeds.binance_ws_feed import BinanceWebSocketFeed
from services.leverage_service import LeverageAssessor

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
        self._feed = None  # WebSocket feed (realtime mode only)
        self._depth_feed = None  # BinanceDepthFeed (optional, for OrderBook data)

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

    def set_depth_feed(self, depth_feed) -> None:
        """Attach a BinanceDepthFeed for real-time Order Book data."""
        self._depth_feed = depth_feed

    def _build_context(self) -> MarketContext:
        """Build MarketContext with latest data from feeds."""
        ob = self._depth_feed.get_orderbook() if self._depth_feed else None
        return MarketContext(orderbook=ob)

    def stop(self) -> None:
        """Signal the engine to stop and wait for it to finish."""
        self._stop_event.set()
        # Stop WebSocket feed if running
        if self._feed is not None:
            self._feed.stop()
            self._feed = None
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
            elif self.config.mode == "realtime":
                self._run_realtime()
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
            signal = self._strategy.generate_signal_v2(ohlcv, i, self._build_context())

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
                    signal = self._strategy.generate_signal_v2(ohlcv, index, self._build_context())

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
    # Realtime mode
    # ------------------------------------------------------------------

    def _run_realtime(self) -> None:
        """Run with Binance WebSocket real-time data feed.

        Flow:
        1. Warmup: fetch 30 days of historical candles for indicator calculation
        2. Start WebSocket feed for real-time closed candles
        3. For each candle: liquidation check -> funding -> signal -> process -> equity
        """
        symbol = self.config.symbol
        interval = self.config.interval

        # 1. Warmup: fetch historical candles for strategy indicators
        warmup_end = dt_module.datetime.now(dt_module.timezone.utc)
        warmup_start = warmup_end - dt_module.timedelta(days=30)
        warmup_data = fetch_klines(
            symbol, interval,
            warmup_start.strftime("%Y-%m-%d"),
            warmup_end.strftime("%Y-%m-%d"),
        )
        candle_buffer = list(warmup_data.candles)
        logger.info(f"Warmup loaded {len(candle_buffer)} candles for {symbol}")

        # 2. Initialize leverage assessor
        assessor = LeverageAssessor()
        strategy = self._strategy
        adapter = self.adapter

        # Funding rate tracking
        funding_interval = self._funding_candle_interval(interval)
        funding_prorate = self._funding_prorate_factor(interval)
        candle_count = 0

        # 3. Start WebSocket feed
        feed = BinanceWebSocketFeed(
            symbol.lower(), interval,
            on_price_update=lambda p: adapter.set_current_price(symbol, p),
        )
        feed.start()
        self._feed = feed

        try:
            while not self._stop_event.is_set():
                candle = feed.get_candle(timeout=5.0)
                if candle is None:
                    continue

                candle_buffer.append(candle)
                ohlcv = OHLCVData(
                    symbol=symbol, interval=interval, candles=candle_buffer
                )
                index = len(candle_buffer) - 1

                adapter.set_current_price(symbol, candle.close)
                self._candle_count += 1

                # --- Risk management checks ---
                # 1. Liquidation check
                liquidated = adapter.check_liquidation(symbol, candle)
                if liquidated:
                    logger.warning(
                        f"Position LIQUIDATED on candle {candle.timestamp}"
                    )

                # 2. Funding rate (every N candles)
                config = self.config
                if (not liquidated and config.funding_rate > 0
                        and candle_count > 0):
                    if (funding_interval > 0
                            and candle_count % funding_interval == 0):
                        cost = adapter.apply_funding(
                            symbol, candle.close,
                            config.funding_rate * funding_prorate,
                        )
                        if cost > 0:
                            logger.info(f"Funding paid: ${cost:.4f}")

                # --- Strategy signal ---
                # Clear indicator cache: candle_buffer grows each iteration,
                # so cached arrays (e.g. RSI) from the previous tick are stale.
                strategy._indicator_cache.clear()
                signal = strategy.generate_signal_v2(ohlcv, index, self._build_context())
                if signal and not liquidated:
                    self._process_signal_with_leverage(
                        signal, candle, ohlcv, index, assessor
                    )
                    self._signal_count += 1

                # --- Record equity ---
                try:
                    account = adapter.get_account_state()
                    account.session_id = config.session_id
                    account.timestamp = candle.timestamp
                    self.persistence.save_equity_snapshot(account)
                except Exception as e:
                    logger.error(f"Equity snapshot error: {e}")

                candle_count += 1

        finally:
            feed.stop()

    def _process_signal_with_leverage(
        self, signal: TradeSignal, candle: Candle,
        ohlcv: OHLCVData, index: int,
        assessor: LeverageAssessor,
    ) -> None:
        """Process signal with leverage assessment.

        Unlike _process_signal() (used by simulated/polling modes), this
        method integrates the LeverageAssessor for dynamic or fixed leverage
        and passes leverage parameters to the adapter.
        """
        config = self.config
        symbol = config.symbol
        adapter = self.adapter

        # Determine leverage
        side = "LONG" if signal.signal_type in ("BUY",) else "SHORT"
        if config.leverage_mode == "dynamic":
            assessed = assessor.assess(ohlcv, index, side, config.max_leverage)
        else:
            assessed = config.fixed_leverage
        final_leverage = assessor.resolve_leverage(
            signal.leverage, assessed, config.leverage_mode,
            config.fixed_leverage, config.max_leverage,
        )

        position = adapter.get_position(symbol)

        if signal.signal_type == "BUY":
            # Close any SHORT first
            if position and position.side == "SHORT":
                order = adapter.place_order(
                    symbol, "SHORT_CLOSE", "MARKET",
                    position.quantity, candle.close,
                    "Closing SHORT for BUY",
                )
                self.persistence.save_order(order)
            # Open LONG if no position
            pos = adapter.get_position(symbol)
            if pos is None:
                order = adapter.place_order(
                    symbol, "BUY", "MARKET", 0, candle.close,
                    signal.reason, leverage=final_leverage,
                    maintenance_margin_rate=config.maintenance_margin_rate,
                )
                self.persistence.save_order(order)
                logger.info(
                    f"[{self.session_id}] BUY @ {candle.close:.2f} "
                    f"leverage={final_leverage:.1f}x | {signal.reason}"
                )

        elif signal.signal_type == "SELL":
            if position and position.side == "LONG":
                order = adapter.place_order(
                    symbol, "SELL", "MARKET",
                    position.quantity, candle.close, signal.reason,
                )
                self.persistence.save_order(order)
                logger.info(
                    f"[{self.session_id}] SELL @ {candle.close:.2f} "
                    f"| {signal.reason}"
                )

        elif signal.signal_type == "SHORT":
            # Close any LONG first
            if position and position.side == "LONG":
                order = adapter.place_order(
                    symbol, "SELL", "MARKET",
                    position.quantity, candle.close,
                    "Closing LONG for SHORT",
                )
                self.persistence.save_order(order)
            # Open SHORT if no position
            pos = adapter.get_position(symbol)
            if pos is None:
                order = adapter.place_order(
                    symbol, "SHORT_OPEN", "MARKET", 0,
                    candle.close, signal.reason,
                    leverage=final_leverage,
                    maintenance_margin_rate=config.maintenance_margin_rate,
                )
                self.persistence.save_order(order)
                logger.info(
                    f"[{self.session_id}] SHORT @ {candle.close:.2f} "
                    f"leverage={final_leverage:.1f}x | {signal.reason}"
                )

        elif signal.signal_type == "COVER":
            if position and position.side == "SHORT":
                order = adapter.place_order(
                    symbol, "SHORT_CLOSE", "MARKET",
                    position.quantity, candle.close, signal.reason,
                )
                self.persistence.save_order(order)
                logger.info(
                    f"[{self.session_id}] COVER @ {candle.close:.2f} "
                    f"| {signal.reason}"
                )

    # ------------------------------------------------------------------
    # Funding rate helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _funding_candle_interval(interval: str) -> int:
        """Number of candles between 8-hour funding rate applications.

        Funding is applied every 8 hours. This returns how many candles
        of the given interval fit into 8 hours.
        """
        intervals = {
            "1m": 480, "5m": 96, "15m": 32, "30m": 16,
            "1h": 8, "2h": 4, "4h": 2, "8h": 1, "12h": 1, "1d": 1,
        }
        return intervals.get(interval, 8)

    @staticmethod
    def _funding_prorate_factor(interval: str) -> float:
        """Prorate factor for intervals >= 8h.

        For intervals longer than 8h, a single candle spans more than
        one funding period, so the rate is multiplied accordingly.
        """
        factors = {"8h": 1.0, "12h": 1.5, "1d": 3.0}
        return factors.get(interval, 1.0)

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
