"""Order Book indicator calculations for strategy signals.

Functions take an OrderBook snapshot and return numeric indicators
that strategies can use for entry/exit decisions.
"""
from typing import Dict, List, Any
from models import OrderBook


def bid_ask_imbalance(ob: OrderBook, levels: int = 5) -> float:
    """(bid_vol - ask_vol) / (bid_vol + ask_vol) for top N levels.

    Range: [-1, 1]. Positive = more buy pressure, negative = more sell pressure.
    Returns 0.0 when the order book is empty.
    """
    bid_vol = sum(l.quantity for l in ob.bids[:levels])
    ask_vol = sum(l.quantity for l in ob.asks[:levels])
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def depth_ratio(ob: OrderBook, levels: int = 10) -> float:
    """Total bid volume / total ask volume at top N levels.

    >1 = more bids, <1 = more asks.
    Returns inf if ask volume is zero (with nonzero bids), 1.0 if both zero.
    """
    bid_vol = sum(l.quantity for l in ob.bids[:levels])
    ask_vol = sum(l.quantity for l in ob.asks[:levels])
    if ask_vol == 0:
        return float('inf') if bid_vol > 0 else 1.0
    return bid_vol / ask_vol


def wall_detection(ob: OrderBook, mult: float = 5.0) -> Dict[str, List[Dict[str, Any]]]:
    """Detect large orders that are mult x the average size on the opposite side.

    A bid wall is a bid level whose quantity >= mult * avg_ask_quantity,
    and an ask wall is an ask level whose quantity >= mult * avg_bid_quantity.
    This captures levels that dwarf the opposing side's typical order size.

    Returns dict with 'bid_walls' and 'ask_walls' lists, each containing
    dicts with 'price' and 'quantity' keys.
    """
    result: Dict[str, List[Dict[str, Any]]] = {"bid_walls": [], "ask_walls": []}

    avg_ask_qty = (sum(l.quantity for l in ob.asks) / len(ob.asks)) if ob.asks else 0.0
    avg_bid_qty = (sum(l.quantity for l in ob.bids) / len(ob.bids)) if ob.bids else 0.0

    if ob.bids and avg_ask_qty > 0:
        for l in ob.bids:
            if l.quantity >= avg_ask_qty * mult:
                result["bid_walls"].append({"price": l.price, "quantity": l.quantity})

    if ob.asks and avg_bid_qty > 0:
        for l in ob.asks:
            if l.quantity >= avg_bid_qty * mult:
                result["ask_walls"].append({"price": l.price, "quantity": l.quantity})

    return result


def spread_bps(ob: OrderBook) -> float:
    """Spread in basis points (1 bp = 0.01%).

    Calculated as (best_ask - best_bid) / mid_price * 10000.
    Returns 0.0 when mid price is zero.
    """
    mid = ob.mid_price
    if mid == 0:
        return 0.0
    return (ob.best_ask - ob.best_bid) / mid * 10000


def weighted_mid_price(ob: OrderBook) -> float:
    """Volume-weighted mid price using top-of-book quantities.

    Shifts toward the side with more volume: heavier bids pull
    the weighted mid toward the ask price, and vice versa.
    Returns plain mid_price when book is empty or volumes are zero.
    """
    bb, ba = ob.best_bid, ob.best_ask
    if not ob.bids or not ob.asks:
        return ob.mid_price
    bv = ob.bids[0].quantity
    av = ob.asks[0].quantity
    total = bv + av
    if total == 0:
        return ob.mid_price
    return (bb * av + ba * bv) / total


def cumulative_delta(ob: OrderBook, price_range_pct: float = 0.5) -> float:
    """Net order flow: total bid qty - total ask qty within price range of mid.

    Positive = net buying pressure, negative = net selling pressure.
    price_range_pct defines the percentage band around mid price to include.
    Returns 0.0 when mid price is zero.
    """
    mid = ob.mid_price
    if mid == 0:
        return 0.0
    range_abs = mid * price_range_pct / 100
    lo, hi = mid - range_abs, mid + range_abs

    bid_vol = sum(l.quantity for l in ob.bids if l.price >= lo)
    ask_vol = sum(l.quantity for l in ob.asks if l.price <= hi)
    return bid_vol - ask_vol
