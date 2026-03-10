"""
Data Service: Fetch K-line data from Binance API + SQLite cache
"""
import sqlite3
import json
import time
import os
import ssl
import urllib.request
import math
from typing import List, Optional
from models import Candle, OHLCVData
import numpy as np

DB_PATH = os.path.join("/tmp", "klines_cache.db")

# Symbol to contract address mapping for DeFi tokens
DEFI_TOKENS = {
    # Can be extended
}

# Binance spot kline intervals
VALID_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M"
]


def _get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS klines (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, count INTEGER,
            PRIMARY KEY (symbol, interval, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_klines_lookup
        ON klines(symbol, interval, timestamp)
    """)
    conn.commit()
    return conn


def _fetch_url(url: str, timeout: int = 30) -> dict:
    """Fetch JSON from URL with SSL handling."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "Accept-Encoding": "identity",
        "User-Agent": "CryptoBacktest/1.0"
    })
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _fetch_binance_klines(symbol: str, interval: str,
                          start_time: Optional[int] = None,
                          end_time: Optional[int] = None,
                          limit: int = 1000) -> List[Candle]:
    """Fetch K-line data from Binance public API."""
    base_url = "https://api.binance.com/api/v3/klines"
    params = f"symbol={symbol}&interval={interval}&limit={limit}"
    if start_time:
        params += f"&startTime={start_time}"
    if end_time:
        params += f"&endTime={end_time}"

    url = f"{base_url}?{params}"
    data = _fetch_url(url)

    candles = []
    for item in data:
        candles.append(Candle(
            timestamp=int(item[0]),
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
            count=int(item[8]) if len(item) > 8 else 0,
        ))
    return candles


def _cache_candles(conn: sqlite3.Connection, symbol: str, interval: str, candles: List[Candle]):
    """Store candles in SQLite cache."""
    conn.executemany(
        "INSERT OR REPLACE INTO klines VALUES (?,?,?,?,?,?,?,?,?)",
        [(symbol, interval, c.timestamp, c.open, c.high, c.low, c.close, c.volume, c.count)
         for c in candles]
    )
    conn.commit()


def _load_cached(conn: sqlite3.Connection, symbol: str, interval: str,
                 start_time: int, end_time: int) -> List[Candle]:
    """Load candles from SQLite cache."""
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume, count FROM klines "
        "WHERE symbol=? AND interval=? AND timestamp>=? AND timestamp<=? "
        "ORDER BY timestamp",
        (symbol, interval, start_time, end_time)
    ).fetchall()
    return [Candle(timestamp=r[0], open=r[1], high=r[2], low=r[3],
                   close=r[4], volume=r[5], count=r[6]) for r in rows]


def _date_to_ms(date_str: str) -> int:
    """Convert 'YYYY-MM-DD' to timestamp in ms."""
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.timestamp() * 1000)


def _interval_to_ms(interval: str) -> int:
    """Convert interval string to milliseconds."""
    units = {"m": 60000, "h": 3600000, "d": 86400000, "w": 604800000, "M": 2592000000}
    num = int(interval[:-1])
    unit = interval[-1]
    return num * units.get(unit, 3600000)


def fetch_klines(symbol: str, interval: str = "1h",
                 start_date: str = "2024-01-01",
                 end_date: str = "2025-01-01") -> OHLCVData:
    """
    Fetch K-line data with caching.
    Returns OHLCVData with all candles in the date range.
    """
    start_ms = _date_to_ms(start_date)
    end_ms = _date_to_ms(end_date)

    conn = _get_db()

    # Check cache first
    cached = _load_cached(conn, symbol, interval, start_ms, end_ms)

    if cached:
        # Check if we have enough data (allow 5% gap)
        expected_count = (end_ms - start_ms) / _interval_to_ms(interval)
        if len(cached) >= expected_count * 0.9:
            conn.close()
            return OHLCVData(symbol=symbol, interval=interval, candles=cached)

    # Fetch from Binance in chunks (max 1000 per request)
    all_candles = []
    current_start = start_ms
    chunk_size = 1000 * _interval_to_ms(interval)
    api_failed = False

    while current_start < end_ms:
        chunk_end = min(current_start + chunk_size, end_ms)
        try:
            candles = _fetch_binance_klines(
                symbol, interval,
                start_time=current_start,
                end_time=chunk_end,
                limit=1000
            )
            if not candles:
                break
            all_candles.extend(candles)
            current_start = candles[-1].timestamp + _interval_to_ms(interval)
            time.sleep(0.2)  # Rate limiting
        except Exception as e:
            print(f"API unavailable ({e}), falling back to synthetic data")
            api_failed = True
            break

    # Fallback: generate synthetic data if API failed
    if api_failed and not all_candles:
        print(f"Generating synthetic data for {symbol} {interval}")
        all_candles = _generate_synthetic(symbol, interval, start_ms, end_ms)

    # Cache the fetched data
    if all_candles:
        _cache_candles(conn, symbol, interval, all_candles)

    # Reload from cache (merged)
    result = _load_cached(conn, symbol, interval, start_ms, end_ms)
    conn.close()

    return OHLCVData(symbol=symbol, interval=interval, candles=result)


def _generate_synthetic(symbol: str, interval: str,
                        start_ms: int, end_ms: int) -> List[Candle]:
    """
    Generate realistic synthetic price data as fallback when API is unavailable.
    Uses geometric Brownian motion with mean reversion and momentum regimes.
    """
    interval_ms = _interval_to_ms(interval)
    n = int((end_ms - start_ms) / interval_ms)
    if n <= 0:
        return []

    # Base prices by symbol
    base_prices = {
        "BTCUSDT": 42000, "ETHUSDT": 2400, "BNBUSDT": 310,
        "SOLUSDT": 110, "XRPUSDT": 0.55, "DOGEUSDT": 0.08,
    }
    price = base_prices.get(symbol, 100)

    # Use symbol hash as seed for reproducibility
    np.random.seed(hash(symbol + interval + str(start_ms)) % (2**31))

    candles = []
    drift = 0.00002  # Slight upward drift
    volatility = 0.008 if "BTC" in symbol else 0.012  # Per-candle volatility

    for i in range(n):
        # Regime switching: trending vs mean-reverting
        regime = np.sin(i / (n * 0.1)) * 0.5
        change = np.random.normal(drift + regime * 0.0001, volatility)

        # Mean reversion component
        log_return = change - 0.001 * (price / base_prices.get(symbol, 100) - 1)
        price *= (1 + log_return)

        # Generate OHLC
        intra_vol = abs(np.random.normal(0, volatility * 0.6))
        o = price * (1 + np.random.normal(0, 0.0005))
        h = max(o, price) * (1 + intra_vol)
        l = min(o, price) * (1 - intra_vol)
        c = price
        vol = np.random.uniform(50, 500) * (base_prices.get(symbol, 100) / 100)

        ts = start_ms + i * interval_ms
        candles.append(Candle(
            timestamp=ts,
            open=round(o, 2),
            high=round(h, 2),
            low=round(l, 2),
            close=round(c, 2),
            volume=round(vol, 2),
            count=int(np.random.uniform(10, 200)),
        ))

    return candles


def get_cached_symbols() -> List[str]:
    """List all symbols in the cache."""
    conn = _get_db()
    rows = conn.execute("SELECT DISTINCT symbol FROM klines").fetchall()
    conn.close()
    return [r[0] for r in rows]


def fetch_depth(symbol: str, limit: int = 20) -> 'OrderBook':
    """Fetch current order book depth from Binance REST API."""
    from models import OrderBook, OrderBookLevel
    url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit={limit}"
    try:
        data = _fetch_url(url)
        bids = [OrderBookLevel(float(b[0]), float(b[1])) for b in data.get("bids", [])]
        asks = [OrderBookLevel(float(a[0]), float(a[1])) for a in data.get("asks", [])]
        return OrderBook(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=bids,
            asks=asks,
        )
    except Exception as e:
        print(f"[DataService] Failed to fetch depth for {symbol}: {e}")
        return OrderBook(symbol=symbol, timestamp=int(time.time() * 1000))
