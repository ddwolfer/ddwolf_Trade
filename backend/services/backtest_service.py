"""
Backtest Service - orchestrates the full backtest workflow.
"""
import threading
from typing import Dict, Optional
from models import BacktestConfig, BacktestResult
from services.data_service import fetch_klines
from services.strategy_engine import StrategyEngine
from services.report_service import calculate_metrics, generate_charts
from strategies.registry import StrategyRegistry

# In-memory store for backtest results
_results: Dict[str, BacktestResult] = {}
_lock = threading.Lock()


def run_backtest(config: BacktestConfig) -> BacktestResult:
    """Run a complete backtest synchronously."""
    result = BacktestResult(config=config)

    with _lock:
        _results[result.id] = result
        result.status = "running"

    try:
        # 1. Fetch data
        ohlcv = fetch_klines(
            symbol=config.symbol,
            interval=config.interval,
            start_date=config.start_date,
            end_date=config.end_date,
        )

        if not ohlcv.candles:
            result.status = "error"
            result.error = f"No data found for {config.symbol} from {config.start_date} to {config.end_date}"
            return result

        # 2. Create strategy
        strategy = StrategyRegistry.create(config.strategy_name, config.strategy_params)

        # 3. Run engine
        engine = StrategyEngine(
            commission_rate=config.commission_rate,
            slippage_rate=config.slippage_rate,
        )
        trades, equity_curve, equity_timestamps = engine.run(
            ohlcv, strategy, config.initial_capital,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
            trailing_stop_atr_period=config.trailing_stop_atr_period,
            trailing_stop_atr_mult=config.trailing_stop_atr_mult,
            # Leverage params
            max_leverage=config.max_leverage,
            leverage_mode=config.leverage_mode,
            fixed_leverage=config.fixed_leverage,
            funding_rate=config.funding_rate,
            maintenance_margin_rate=config.maintenance_margin_rate,
            interval=config.interval,
        )

        # 4. Calculate metrics
        metrics = calculate_metrics(trades, equity_curve, config.initial_capital)

        # 5. Generate charts
        charts = generate_charts(ohlcv, trades, equity_curve, equity_timestamps, config.initial_capital)

        # 6. Store result
        result.trades = trades
        result.metrics = metrics
        result.equity_curve = equity_curve
        result.equity_timestamps = equity_timestamps
        result.drawdown_curve = charts.get("drawdown_chart", {}).get("data", [{}])[0].get("y", [])
        result.status = "completed"
        result._charts = charts  # Store for later retrieval

    except Exception as e:
        result.status = "error"
        result.error = str(e)
        import traceback
        traceback.print_exc()

    return result


def run_backtest_async(config: BacktestConfig) -> str:
    """Run backtest in background thread. Returns backtest ID."""
    result = BacktestResult(config=config, status="queued")
    with _lock:
        _results[result.id] = result

    def _run():
        r = run_backtest(config)
        with _lock:
            _results[r.id] = r

    # Reuse ID
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return result.id


def get_result(backtest_id: str) -> Optional[BacktestResult]:
    """Get backtest result by ID."""
    return _results.get(backtest_id)


def list_results():
    """List all backtest results."""
    return list(_results.values())
