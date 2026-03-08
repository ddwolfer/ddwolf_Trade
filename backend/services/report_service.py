"""
Report Service - calculates performance metrics and generates chart data.
"""
import numpy as np
from typing import List, Dict, Any
from datetime import datetime
from models import Trade, OHLCVData


def calculate_metrics(trades: List[Trade], equity_curve: List[float],
                      initial_capital: float) -> Dict[str, Any]:
    """Calculate comprehensive backtest performance metrics."""
    if not trades or not equity_curve:
        return {"error": "No trades executed"}

    closed = [t for t in trades if t.status == "CLOSED"]
    if not closed:
        return {"error": "No closed trades"}

    winners = [t for t in closed if t.profit_loss > 0]
    losers = [t for t in closed if t.profit_loss <= 0]

    total_profit = sum(t.profit_loss for t in winners)
    total_loss = abs(sum(t.profit_loss for t in losers))

    # Equity and drawdown
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    drawdown = (eq - peak) / peak * 100
    max_dd = float(np.min(drawdown))

    # Returns for Sharpe/Sortino
    eq_nonzero = eq[eq > 0]
    if len(eq_nonzero) > 1:
        returns = np.diff(eq_nonzero) / eq_nonzero[:-1]
        avg_ret = float(np.mean(returns))
        std_ret = float(np.std(returns))
        downside_std = float(np.std(returns[returns < 0])) if np.any(returns < 0) else 0.001

        sharpe = (avg_ret / std_ret * np.sqrt(252 * 24)) if std_ret > 0 else 0  # Annualized (hourly data)
        sortino = (avg_ret / downside_std * np.sqrt(252 * 24)) if downside_std > 0 else 0
    else:
        sharpe = sortino = 0

    # Consecutive losses
    max_consec_loss = 0
    current_consec = 0
    for t in closed:
        if t.profit_loss <= 0:
            current_consec += 1
            max_consec_loss = max(max_consec_loss, current_consec)
        else:
            current_consec = 0

    # Holding time distribution
    holding_hours = []
    for t in closed:
        if t.exit_time and t.entry_time:
            hours = (t.exit_time - t.entry_time) / 3600000
            holding_hours.append(hours)

    # Monthly returns
    monthly_returns = {}
    for t in closed:
        month = datetime.fromtimestamp(t.entry_time / 1000).strftime("%Y-%m")
        monthly_returns.setdefault(month, 0)
        monthly_returns[month] += t.profit_loss

    final_equity = float(equity_curve[-1])

    # Exit type and side breakdowns
    long_trades = [t for t in closed if t.side == "LONG"]
    short_trades = [t for t in closed if t.side == "SHORT"]
    sl_exits = len([t for t in closed if t.exit_type == "STOP_LOSS"])
    tp_exits = len([t for t in closed if t.exit_type == "TAKE_PROFIT"])
    signal_exits = len([t for t in closed if t.exit_type == "SIGNAL"])
    long_winners = [t for t in long_trades if t.profit_loss > 0]
    short_winners = [t for t in short_trades if t.profit_loss > 0]

    return {
        "total_trades": len(closed),
        "winning_trades": len(winners),
        "losing_trades": len(losers),
        "win_rate": round(len(winners) / len(closed) * 100, 2),
        "total_return_pct": round((final_equity / initial_capital - 1) * 100, 2),
        "total_return_usd": round(final_equity - initial_capital, 2),
        "final_equity": round(final_equity, 2),
        "initial_capital": initial_capital,
        "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else float('inf'),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "sortino_ratio": round(float(sortino), 2),
        "avg_win_usd": round(total_profit / len(winners), 2) if winners else 0,
        "avg_loss_usd": round(-total_loss / len(losers), 2) if losers else 0,
        "avg_win_pct": round(np.mean([t.return_pct for t in winners]), 2) if winners else 0,
        "avg_loss_pct": round(np.mean([t.return_pct for t in losers]), 2) if losers else 0,
        "max_consecutive_losses": max_consec_loss,
        "avg_holding_hours": round(np.mean(holding_hours), 1) if holding_hours else 0,
        "monthly_returns": monthly_returns,
        # Position side breakdown
        "long_trades": len(long_trades),
        "short_trades": len(short_trades),
        "long_win_rate": round(len(long_winners) / len(long_trades) * 100, 2) if long_trades else 0,
        "short_win_rate": round(len(short_winners) / len(short_trades) * 100, 2) if short_trades else 0,
        # Exit type breakdown
        "signal_exits": signal_exits,
        "sl_exits": sl_exits,
        "tp_exits": tp_exits,
    }


def generate_charts(ohlcv: OHLCVData, trades: List[Trade],
                    equity_curve: List[float], equity_timestamps: List[int],
                    initial_capital: float) -> Dict[str, Any]:
    """Generate Plotly-compatible chart data."""
    timestamps_str = [datetime.fromtimestamp(t / 1000).strftime("%Y-%m-%d %H:%M") for t in equity_timestamps]
    candle_times = [datetime.fromtimestamp(c.timestamp / 1000).strftime("%Y-%m-%d %H:%M") for c in ohlcv.candles]

    # Equity curve chart
    equity_chart = {
        "data": [
            {
                "x": timestamps_str,
                "y": [round(v, 2) for v in equity_curve],
                "type": "scatter",
                "mode": "lines",
                "name": "Equity",
                "line": {"color": "#2196F3", "width": 2}
            },
            {
                "x": [timestamps_str[0], timestamps_str[-1]],
                "y": [initial_capital, initial_capital],
                "type": "scatter",
                "mode": "lines",
                "name": "Initial Capital",
                "line": {"color": "#999", "dash": "dash", "width": 1}
            }
        ],
        "layout": {
            "title": "Equity Curve",
            "xaxis": {"title": "Date"},
            "yaxis": {"title": "USD", "tickformat": ",.0f"},
            "hovermode": "x unified",
            "template": "plotly_dark",
            "height": 350,
        }
    }

    # Drawdown chart
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = ((eq - peak) / peak * 100).tolist()

    drawdown_chart = {
        "data": [{
            "x": timestamps_str,
            "y": [round(v, 2) for v in dd],
            "type": "scatter",
            "fill": "tozeroy",
            "name": "Drawdown",
            "line": {"color": "#f44336"},
            "fillcolor": "rgba(244,67,54,0.3)"
        }],
        "layout": {
            "title": "Drawdown",
            "xaxis": {"title": "Date"},
            "yaxis": {"title": "%", "ticksuffix": "%"},
            "hovermode": "x unified",
            "template": "plotly_dark",
            "height": 250,
        }
    }

    # K-line with trade markers (LONG/SHORT entries + signal/SL/TP exits)
    long_entry_times, long_entry_prices = [], []
    short_entry_times, short_entry_prices = [], []
    signal_exit_times, signal_exit_prices = [], []
    sl_exit_times, sl_exit_prices = [], []
    tp_exit_times, tp_exit_prices = [], []

    for t in trades:
        entry_str = datetime.fromtimestamp(t.entry_time / 1000).strftime("%Y-%m-%d %H:%M")
        if t.side == "LONG":
            long_entry_times.append(entry_str)
            long_entry_prices.append(t.entry_price)
        else:
            short_entry_times.append(entry_str)
            short_entry_prices.append(t.entry_price)

        if t.exit_time:
            exit_str = datetime.fromtimestamp(t.exit_time / 1000).strftime("%Y-%m-%d %H:%M")
            if t.exit_type == "STOP_LOSS":
                sl_exit_times.append(exit_str)
                sl_exit_prices.append(t.exit_price)
            elif t.exit_type == "TAKE_PROFIT":
                tp_exit_times.append(exit_str)
                tp_exit_prices.append(t.exit_price)
            else:
                signal_exit_times.append(exit_str)
                signal_exit_prices.append(t.exit_price)

    trade_markers = [
        {
            "x": long_entry_times, "y": long_entry_prices,
            "type": "scatter", "mode": "markers", "name": "Buy (Long)",
            "marker": {"symbol": "triangle-up", "size": 12, "color": "#00e676"}
        },
        {
            "x": signal_exit_times, "y": signal_exit_prices,
            "type": "scatter", "mode": "markers", "name": "Sell (Signal)",
            "marker": {"symbol": "triangle-down", "size": 12, "color": "#ff1744"}
        },
    ]
    if short_entry_times:
        trade_markers.append({
            "x": short_entry_times, "y": short_entry_prices,
            "type": "scatter", "mode": "markers", "name": "Short Entry",
            "marker": {"symbol": "triangle-down", "size": 12, "color": "#ff9800"}
        })
    if sl_exit_times:
        trade_markers.append({
            "x": sl_exit_times, "y": sl_exit_prices,
            "type": "scatter", "mode": "markers", "name": "Stop Loss",
            "marker": {"symbol": "x", "size": 10, "color": "#f44336"}
        })
    if tp_exit_times:
        trade_markers.append({
            "x": tp_exit_times, "y": tp_exit_prices,
            "type": "scatter", "mode": "markers", "name": "Take Profit",
            "marker": {"symbol": "star", "size": 10, "color": "#4caf50"}
        })

    kline_chart = {
        "data": [
            {
                "x": candle_times,
                "open": [c.open for c in ohlcv.candles],
                "high": [c.high for c in ohlcv.candles],
                "low": [c.low for c in ohlcv.candles],
                "close": [c.close for c in ohlcv.candles],
                "type": "candlestick",
                "name": ohlcv.symbol,
                "increasing": {"line": {"color": "#26a69a"}},
                "decreasing": {"line": {"color": "#ef5350"}},
            },
        ] + trade_markers,
        "layout": {
            "title": f"{ohlcv.symbol} - Trades",
            "xaxis": {"title": "Date", "rangeslider": {"visible": False}},
            "yaxis": {"title": "Price (USD)", "tickformat": ",.0f"},
            "hovermode": "x unified",
            "template": "plotly_dark",
            "height": 450,
        }
    }

    # Monthly returns heatmap
    metrics = calculate_metrics(trades, equity_curve, initial_capital)
    monthly = metrics.get("monthly_returns", {})
    if monthly:
        months = sorted(monthly.keys())
        values = [round(monthly[m], 2) for m in months]
        monthly_chart = {
            "data": [{
                "x": months,
                "y": values,
                "type": "bar",
                "name": "Monthly P&L",
                "marker": {
                    "color": ["#26a69a" if v >= 0 else "#ef5350" for v in values]
                }
            }],
            "layout": {
                "title": "Monthly Returns (USD)",
                "xaxis": {"title": "Month"},
                "yaxis": {"title": "USD", "tickformat": ",.0f"},
                "template": "plotly_dark",
                "height": 300,
            }
        }
    else:
        monthly_chart = None

    return {
        "equity_chart": equity_chart,
        "drawdown_chart": drawdown_chart,
        "kline_chart": kline_chart,
        "monthly_chart": monthly_chart,
    }
