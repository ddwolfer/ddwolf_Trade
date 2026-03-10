"""Binance WebSocket depth feed for real-time Order Book data.

Connects to Binance partial book depth stream and maintains
the latest OrderBook snapshot. Thread-safe access via get_orderbook().

Stream: {symbol}@depth{levels}@100ms
  - Pushes top N bid/ask levels every 100ms
  - No API key required (public data)

Usage:
    feed = BinanceDepthFeed("BTCUSDT", on_depth_update=callback)
    feed.start()
    ob = feed.get_orderbook()  # thread-safe
    feed.stop()
"""
import json
import logging
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

    Supports two Binance message formats:
      1. Partial depth stream (has "lastUpdateId", "bids", "asks")
      2. Diff depth stream (has "e": "depthUpdate", "b", "a")
    """

    def __init__(self, symbol: str, levels: int = 20,
                 on_depth_update: Optional[Callable[[OrderBook], None]] = None):
        """
        Args:
            symbol: Trading pair (e.g. "BTCUSDT", case-insensitive)
            levels: Number of price levels (5, 10, or 20)
            on_depth_update: Optional callback invoked on each new OrderBook
        """
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

        # Reconnection config
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
            target=self._run_with_reconnect, daemon=True,
            name="binance-depth-feed"
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
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)
        self._connected = False
        logger.info("Depth feed stopped")

    def get_orderbook(self) -> Optional[OrderBook]:
        """Get the latest order book snapshot. Thread-safe."""
        with self._lock:
            return self._latest_ob

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._connected

    def _parse_depth_message(self, data: dict) -> Optional[OrderBook]:
        """Parse a Binance depth message into an OrderBook.

        Handles two formats:
          - Partial depth stream: keys "bids"/"asks" with "lastUpdateId"
          - Diff depth stream: keys "b"/"a" with event type "depthUpdate"

        Returns None if the message is not a depth-related message.
        """
        # Try both key naming conventions
        bids_raw = data.get("b", data.get("bids"))
        asks_raw = data.get("a", data.get("asks"))

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
        """Process incoming WebSocket message."""
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
        """Called when WebSocket connection is established."""
        self._connected = True
        logger.info(f"Depth WebSocket connected: {self._ws_url}")

    def _on_close(self, ws, close_status_code=None, close_msg=None) -> None:
        """Called when WebSocket connection is closed."""
        self._connected = False
        logger.info(f"Depth WebSocket closed: {close_status_code}")

    def _on_error(self, ws, error) -> None:
        """Called on WebSocket error."""
        self._connected = False
        logger.error(f"Depth WebSocket error: {error}")

    def _run_with_reconnect(self) -> None:
        """Run WebSocket with exponential backoff reconnection."""
        try:
            import websocket
        except ImportError:
            logger.error(
                "websocket-client not installed. "
                "Install with: pip install websocket-client"
            )
            return

        retries = 0
        while not self._stop_event.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self._ws.run_forever()

                if self._stop_event.is_set():
                    break

                # Connection dropped -- reconnect
                retries += 1
                if retries > self._max_retries:
                    logger.error(
                        f"Max retries ({self._max_retries}) reached, giving up"
                    )
                    break

                delay = min(
                    self._base_delay * (2 ** (retries - 1)), self._max_delay
                )
                logger.warning(
                    f"Reconnecting in {delay}s "
                    f"(attempt {retries}/{self._max_retries})"
                )
                self._stop_event.wait(delay)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if not self._stop_event.is_set():
                    self._stop_event.wait(self._base_delay)
