"""
Binance WebSocket K-line Data Feed.

Connects to Binance's public WebSocket stream for real-time kline data.
No API key required — kline data is public.

When a candle closes (kline.x == true), the completed Candle is placed
into a thread-safe queue for the engine to consume.
"""
import json
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
            try:
                candle = Candle(
                    timestamp=int(k["t"]),
                    open=float(k["o"]),
                    high=float(k["h"]),
                    low=float(k["l"]),
                    close=float(k["c"]),
                    volume=float(k["v"]),
                )
                self._queue.put(candle)
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"Failed to parse kline: {e}")
