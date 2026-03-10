#!/usr/bin/env python3
"""
Crypto Backtest Platform - HTTP Server
Pure stdlib HTTP server with JSON REST API + static file serving.
"""
import sys
import os
import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from models import BacktestConfig
from services import backtest_service
from services.report_service import generate_charts
from services.data_service import fetch_klines
from services.regime_service import detect_regime

# Import strategies to trigger registration
from strategies import rsi_strategy, macd_strategy, bollinger_strategy, ma_cross_strategy, momentum_strategy, confluence_strategy, supertrend_strategy, volume_breakout_strategy, trend_rider_strategy, bear_hunter_strategy, trend_surfer_strategy, scalp_sniper_strategy
from strategies.registry import StrategyRegistry

# Live/paper trading
from live.session_manager import SessionManager
from live.models import TradingSessionConfig

_session_manager = SessionManager()
# Recover any sessions that were "running" when the server last shut down.
# SessionManager.__init__ already calls _recover_interrupted(), but we
# also expose a public method so the recovery can be triggered explicitly.
_recovered = _session_manager.recover_interrupted()
if _recovered:
    print(f"[Recovery] Marked {_recovered} interrupted session(s) from previous run.")


class BacktestHandler(SimpleHTTPRequestHandler):
    """HTTP handler for both API and static files."""

    def __init__(self, *args, **kwargs):
        # Serve frontend from the frontend directory
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        super().__init__(*args, directory=frontend_dir, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api_get(path, parse_qs(parsed.query))
        else:
            # Serve static files (frontend)
            if path == "/":
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            self._handle_api_post(path, data)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

    def _handle_api_get(self, path: str, params: dict):
        """Route GET /api/* requests."""

        # GET /api/strategies
        if path == "/api/strategies":
            strategies = StrategyRegistry.list_all()
            self._send_json({"strategies": strategies})

        # GET /api/backtest - list all
        elif path == "/api/backtest":
            results = backtest_service.list_results()
            self._send_json({
                "backtests": [{
                    "id": r.id,
                    "status": r.status,
                    "config": {
                        "symbol": r.config.symbol,
                        "strategy_name": r.config.strategy_name,
                        "interval": r.config.interval,
                    } if r.config else None,
                    "metrics_summary": {
                        "total_return_pct": r.metrics.get("total_return_pct"),
                        "win_rate": r.metrics.get("win_rate"),
                        "total_trades": r.metrics.get("total_trades"),
                    } if r.metrics else None,
                } for r in results]
            })

        # GET /api/backtest/{id}
        elif path.startswith("/api/backtest/") and not path.endswith("/compare"):
            bid = path.split("/")[-1]
            result = backtest_service.get_result(bid)
            if result:
                self._send_json(result.to_dict())
            else:
                self._send_json({"error": "Backtest not found"}, 404)

        # GET /api/reports/{id}/metrics
        elif "/reports/" in path and path.endswith("/metrics"):
            bid = path.split("/")[3]
            result = backtest_service.get_result(bid)
            if result:
                self._send_json(result.metrics)
            else:
                self._send_json({"error": "Not found"}, 404)

        # GET /api/reports/{id}/charts
        elif "/reports/" in path and path.endswith("/charts"):
            bid = path.split("/")[3]
            result = backtest_service.get_result(bid)
            if result and hasattr(result, '_charts'):
                self._send_json(result._charts)
            elif result:
                # Regenerate charts
                ohlcv = fetch_klines(
                    result.config.symbol, result.config.interval,
                    result.config.start_date, result.config.end_date
                )
                charts = generate_charts(
                    ohlcv, result.trades, result.equity_curve,
                    result.equity_timestamps, result.config.initial_capital
                )
                self._send_json(charts)
            else:
                self._send_json({"error": "Not found"}, 404)

        # GET /api/reports/{id}/trades
        elif "/reports/" in path and path.endswith("/trades"):
            bid = path.split("/")[3]
            result = backtest_service.get_result(bid)
            if result:
                self._send_json({"trades": [t.to_dict() for t in result.trades]})
            else:
                self._send_json({"error": "Not found"}, 404)

        # GET /api/regime/{symbol}
        elif path.startswith("/api/regime/"):
            symbol = path.split("/")[-1]
            tf_param = params.get("timeframes", ["1h,4h,1d"])[0]
            timeframes = [t.strip() for t in tf_param.split(",")]
            try:
                result = detect_regime(symbol, timeframes)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 400)

        # GET /api/data/{symbol}/depth
        elif path.startswith("/api/data/") and path.endswith("/depth"):
            parts = path.split("/")
            symbol = parts[3]  # /api/data/BTCUSDT/depth
            limit = int(params.get("levels", params.get("limit", ["20"]))[0])
            from services.data_service import fetch_depth
            depth = fetch_depth(symbol, limit)
            self._send_json(depth.to_dict())

        # GET /api/data/{symbol}
        elif path.startswith("/api/data/"):
            symbol = path.split("/")[-1]
            interval = params.get("interval", ["1h"])[0]
            start = params.get("start_date", ["2024-01-01"])[0]
            end = params.get("end_date", ["2025-01-01"])[0]
            limit = int(params.get("limit", ["500"])[0])

            ohlcv = fetch_klines(symbol, interval, start, end)
            candles = ohlcv.candles[-limit:] if len(ohlcv.candles) > limit else ohlcv.candles
            self._send_json({
                "symbol": symbol,
                "interval": interval,
                "count": len(candles),
                "candles": [c.to_dict() for c in candles]
            })

        # GET /api/paper — List all paper trading sessions
        elif path == "/api/paper" or path == "/api/paper/":
            sessions = _session_manager.list_sessions()
            self._send_json({"sessions": sessions})

        # GET /api/paper/{id}/orders
        elif path.startswith("/api/paper/") and path.endswith("/orders"):
            parts = path.split("/")
            session_id = parts[3]
            orders = _session_manager.get_orders(session_id)
            self._send_json({"orders": orders})

        # GET /api/paper/{id}/positions
        elif path.startswith("/api/paper/") and path.endswith("/positions"):
            parts = path.split("/")
            session_id = parts[3]
            positions = _session_manager.get_positions(session_id)
            self._send_json({"positions": positions})

        # GET /api/paper/{id}/equity
        elif path.startswith("/api/paper/") and path.endswith("/equity"):
            parts = path.split("/")
            session_id = parts[3]
            curve = _session_manager.get_equity_curve(session_id)
            self._send_json(curve)

        # GET /api/paper/{id} — Get session status (must be after sub-resource routes)
        elif path.startswith("/api/paper/") and path.count("/") == 3:
            session_id = path.split("/")[3]
            if session_id:
                try:
                    status = _session_manager.get_status(session_id)
                    self._send_json(status)
                except ValueError as e:
                    self._send_json({"error": str(e)}, 404)
            else:
                self._send_json({"error": "Missing session ID"}, 400)

        else:
            self._send_json({"error": "Unknown endpoint"}, 404)

    def _handle_api_post(self, path: str, data: dict):
        """Route POST /api/* requests."""

        # POST /api/backtest/run
        if path == "/api/backtest/run":
            try:
                config = BacktestConfig(
                    symbol=data.get("symbol", "BTCUSDT"),
                    interval=data.get("interval", "1h"),
                    start_date=data.get("start_date", "2024-01-01"),
                    end_date=data.get("end_date", "2025-01-01"),
                    initial_capital=float(data.get("initial_capital", 10000)),
                    strategy_name=data.get("strategy_name", "RSI"),
                    strategy_params=data.get("strategy_params", {}),
                    commission_rate=float(data.get("commission_rate", 0.001)),
                    slippage_rate=float(data.get("slippage_rate", 0.0005)),
                    stop_loss_pct=float(data.get("stop_loss_pct", 0)),
                    take_profit_pct=float(data.get("take_profit_pct", 0)),
                    trailing_stop_atr_period=int(data.get("trailing_stop_atr_period", 0)),
                    trailing_stop_atr_mult=float(data.get("trailing_stop_atr_mult", 3.0)),
                    max_leverage=float(data.get("max_leverage", 10.0)),
                    leverage_mode=data.get("leverage_mode", "dynamic"),
                    fixed_leverage=float(data.get("fixed_leverage", 1.0)),
                    funding_rate=float(data.get("funding_rate", 0.0001)),
                    maintenance_margin_rate=float(data.get("maintenance_margin_rate", 0.005)),
                )

                # Run synchronously for simplicity (most backtests are fast)
                result = backtest_service.run_backtest(config)
                self._send_json(result.to_dict())

            except Exception as e:
                self._send_json({"error": str(e)}, 400)

        # POST /api/backtest/compare
        elif path == "/api/backtest/compare":
            try:
                configs = data.get("configs", [])
                results = []
                for cfg_data in configs:
                    config = BacktestConfig(
                        symbol=cfg_data.get("symbol", "BTCUSDT"),
                        interval=cfg_data.get("interval", "1h"),
                        start_date=cfg_data.get("start_date", "2024-01-01"),
                        end_date=cfg_data.get("end_date", "2025-01-01"),
                        initial_capital=float(cfg_data.get("initial_capital", 10000)),
                        strategy_name=cfg_data.get("strategy_name", "RSI"),
                        strategy_params=cfg_data.get("strategy_params", {}),
                        stop_loss_pct=float(cfg_data.get("stop_loss_pct", 0)),
                        take_profit_pct=float(cfg_data.get("take_profit_pct", 0)),
                        trailing_stop_atr_period=int(cfg_data.get("trailing_stop_atr_period", 0)),
                        trailing_stop_atr_mult=float(cfg_data.get("trailing_stop_atr_mult", 3.0)),
                        max_leverage=float(cfg_data.get("max_leverage", 10.0)),
                        leverage_mode=cfg_data.get("leverage_mode", "dynamic"),
                        fixed_leverage=float(cfg_data.get("fixed_leverage", 1.0)),
                        funding_rate=float(cfg_data.get("funding_rate", 0.0001)),
                        maintenance_margin_rate=float(cfg_data.get("maintenance_margin_rate", 0.005)),
                    )
                    result = backtest_service.run_backtest(config)
                    results.append({
                        "id": result.id,
                        "strategy": config.strategy_name,
                        "params": config.strategy_params,
                        "metrics": result.metrics,
                    })
                self._send_json({"results": results})
            except Exception as e:
                self._send_json({"error": str(e)}, 400)

        # POST /api/paper/deploy — Start paper trading session
        elif path == "/api/paper/deploy" or path == "/api/paper/deploy/":
            try:
                config = TradingSessionConfig(
                    symbol=data.get("symbol", "BTCUSDT"),
                    interval=data.get("interval", "1h"),
                    strategy_name=data.get("strategy_name", "RSI"),
                    strategy_params=data.get("strategy_params", {}),
                    initial_capital=float(data.get("initial_capital", 10000)),
                    commission_rate=float(data.get("commission_rate", 0.001)),
                    slippage_rate=float(data.get("slippage_rate", 0.0005)),
                    data_start_date=data.get("data_start_date", "2024-01-01"),
                    data_end_date=data.get("data_end_date", "2025-01-01"),
                    tick_interval_seconds=float(data.get("tick_interval_seconds", 1.0)),
                    mode=data.get("mode", "simulated"),
                    # Leverage params
                    max_leverage=float(data.get("max_leverage", 10.0)),
                    leverage_mode=data.get("leverage_mode", "dynamic"),
                    fixed_leverage=float(data.get("fixed_leverage", 1.0)),
                    funding_rate=float(data.get("funding_rate", 0.0001)),
                    maintenance_margin_rate=float(data.get("maintenance_margin_rate", 0.005)),
                    stop_loss_pct=float(data.get("stop_loss_pct", 0.0)),
                    take_profit_pct=float(data.get("take_profit_pct", 0.0)),
                )
                result = _session_manager.deploy(config)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 400)

        # POST /api/paper/{id}/stop — Stop session
        elif path.startswith("/api/paper/") and path.endswith("/stop"):
            parts = path.split("/")
            session_id = parts[3]
            try:
                result = _session_manager.stop_session(session_id)
                self._send_json(result)
            except ValueError as e:
                self._send_json({"error": str(e)}, 404)

        # POST /api/paper/{id}/close-all — Emergency close positions
        elif path.startswith("/api/paper/") and path.endswith("/close-all"):
            parts = path.split("/")
            session_id = parts[3]
            try:
                orders = _session_manager.close_all_positions(session_id)
                self._send_json({"orders": orders})
            except ValueError as e:
                self._send_json({"error": str(e)}, 404)

        else:
            self._send_json({"error": "Unknown endpoint"}, 404)

    def log_message(self, format, *args):
        """Suppress default logging for cleaner output."""
        if "/api/" in str(args):
            print(f"[API] {args[0]}")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = HTTPServer(("0.0.0.0", port), BacktestHandler)
    print(f"""
╔══════════════════════════════════════════════╗
║   Crypto Backtest Platform                   ║
║   Server running on http://localhost:{port}     ║
║                                              ║
║   Web UI:  http://localhost:{port}              ║
║   API:     http://localhost:{port}/api/          ║
║                                              ║
║   Strategies: {len(StrategyRegistry.list_all()):2d} loaded                     ║
╚══════════════════════════════════════════════╝
    """)

    for s in StrategyRegistry.list_all():
        print(f"  - {s['name']}: {s['description'][:60]}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
