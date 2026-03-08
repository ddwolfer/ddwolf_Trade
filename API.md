# REST API 文件

Base URL: `http://localhost:8000/api`

所有回應均為 JSON 格式，支援 CORS。

---

## 策略

### GET /api/strategies

列出所有可用策略及其參數 schema。

**回應範例：**

```json
{
  "strategies": [
    {
      "name": "RSI",
      "description": "RSI 超買超賣策略：RSI 低於 oversold 買入，高於 overbought 賣出",
      "version": "1.0",
      "params": {
        "period": {
          "type": "int",
          "default": 14,
          "min": 5,
          "max": 50,
          "description": "RSI 計算週期"
        },
        "overbought": {
          "type": "int",
          "default": 70,
          "min": 60,
          "max": 90,
          "description": "超買閾值"
        },
        "oversold": {
          "type": "int",
          "default": 30,
          "min": 10,
          "max": 40,
          "description": "超賣閾值"
        }
      }
    }
  ]
}
```

---

## 回測

### POST /api/backtest/run

執行單次回測。

**請求 Body：**

| 欄位 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `symbol` | string | `"BTCUSDT"` | 交易對 |
| `interval` | string | `"1h"` | K 線週期（1m, 5m, 15m, 1h, 4h, 1d） |
| `start_date` | string | `"2024-01-01"` | 開始日期（YYYY-MM-DD） |
| `end_date` | string | `"2025-01-01"` | 結束日期（YYYY-MM-DD） |
| `initial_capital` | number | `10000` | 初始資金（USD） |
| `strategy_name` | string | `"RSI"` | 策略名稱 |
| `strategy_params` | object | `{}` | 策略參數（不傳則用預設值） |
| `commission_rate` | number | `0.001` | 手續費率（0.1%） |
| `slippage_rate` | number | `0.0005` | 滑點率（0.05%） |
| `stop_loss_pct` | number | `null` | 止損百分比（例如 `0.05` 表示 5% 止損，不設定則不啟用） |
| `take_profit_pct` | number | `null` | 止盈百分比（例如 `0.1` 表示 10% 止盈，不設定則不啟用） |

**請求範例：**

```json
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "start_date": "2024-01-01",
  "end_date": "2025-01-01",
  "initial_capital": 10000,
  "strategy_name": "RSI",
  "strategy_params": {
    "period": 14,
    "overbought": 70,
    "oversold": 30
  }
}
```

**回應範例：**

```json
{
  "id": "bt_abc12345",
  "status": "COMPLETED",
  "config": {
    "symbol": "BTCUSDT",
    "interval": "1h",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01",
    "initial_capital": 10000,
    "strategy_name": "RSI",
    "strategy_params": {"period": 14, "overbought": 70, "oversold": 30},
    "commission_rate": 0.001,
    "slippage_rate": 0.0005,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.1
  },
  "metrics": {
    "total_trades": 24,
    "winning_trades": 20,
    "losing_trades": 4,
    "win_rate": 83.33,
    "total_return_pct": 79.9,
    "total_return_usd": 7990.0,
    "final_equity": 17990.0,
    "initial_capital": 10000,
    "profit_factor": 12.5,
    "max_drawdown_pct": -8.5,
    "sharpe_ratio": 2.1,
    "sortino_ratio": 3.4,
    "avg_win_usd": 420.0,
    "avg_loss_usd": -105.0,
    "avg_win_pct": 4.2,
    "avg_loss_pct": -1.05,
    "max_consecutive_losses": 2,
    "avg_holding_hours": 36.5,
    "monthly_returns": {
      "2024-01": 850.0,
      "2024-02": 620.0
    }
  },
  "trades": [
    {
      "id": "t_001",
      "action": "BUY",
      "entry_price": 42000.0,
      "exit_price": 44100.0,
      "entry_time": 1704067200000,
      "exit_time": 1704196800000,
      "quantity": 0.238,
      "profit_loss": 499.8,
      "return_pct": 5.0,
      "status": "CLOSED"
    }
  ],
  "equity_curve": [10000, 10050, 10120, ...],
  "equity_timestamps": [1704067200000, 1704070800000, ...]
}
```

> **信號類型說明：** 策略可發出四種信號 — `BUY`（開多倉）、`SELL`（平多倉）、`SHORT`（開空倉）、`COVER`（平空倉）。交易記錄的 `action` 欄位會反映對應信號。若設定了 `stop_loss_pct` 或 `take_profit_pct`，引擎會在觸發時自動平倉，交易記錄中會標註觸發原因。
```

### GET /api/backtest

列出所有已執行的回測（摘要）。

**回應範例：**

```json
{
  "backtests": [
    {
      "id": "bt_abc12345",
      "status": "COMPLETED",
      "config": {
        "symbol": "BTCUSDT",
        "strategy_name": "RSI",
        "interval": "1h"
      },
      "metrics_summary": {
        "total_return_pct": 79.9,
        "win_rate": 83.33,
        "total_trades": 24
      }
    }
  ]
}
```

### GET /api/backtest/{id}

取得特定回測的完整結果（格式同 POST /api/backtest/run 的回應）。

### POST /api/backtest/compare

批次執行多個回測並比較結果。

**請求 Body：**

```json
{
  "configs": [
    {
      "symbol": "BTCUSDT",
      "strategy_name": "RSI",
      "strategy_params": {"period": 14, "overbought": 70, "oversold": 30}
    },
    {
      "symbol": "BTCUSDT",
      "strategy_name": "MACD"
    },
    {
      "symbol": "BTCUSDT",
      "strategy_name": "MA Cross",
      "strategy_params": {"fast_period": 10, "slow_period": 30}
    }
  ]
}
```

每個 config 的欄位同 `/api/backtest/run`，未指定的欄位使用預設值。

**回應範例：**

```json
{
  "results": [
    {
      "id": "bt_001",
      "strategy": "RSI",
      "params": {"period": 14, "overbought": 70, "oversold": 30},
      "metrics": { ... }
    },
    {
      "id": "bt_002",
      "strategy": "MACD",
      "params": {},
      "metrics": { ... }
    }
  ]
}
```

> 注意：每次 compare 最多放 20 個 config，避免 server 過載。

---

## 報告

### GET /api/reports/{id}/metrics

取得純數字績效指標（不含交易記錄和圖表）。

**回應：** 同 backtest 結果中的 `metrics` 物件。

### GET /api/reports/{id}/charts

取得 Plotly 相容的圖表 JSON。

**回應範例：**

```json
{
  "equity_chart": {
    "data": [...],
    "layout": {"title": "Equity Curve", ...}
  },
  "drawdown_chart": {
    "data": [...],
    "layout": {"title": "Drawdown", ...}
  },
  "kline_chart": {
    "data": [...],
    "layout": {"title": "BTCUSDT - Trades", ...}
  },
  "monthly_chart": {
    "data": [...],
    "layout": {"title": "Monthly Returns (USD)", ...}
  }
}
```

前端可直接用 `Plotly.newPlot(element, chart.data, chart.layout)` 渲染。

### GET /api/reports/{id}/trades

取得每筆交易明細。

**回應範例：**

```json
{
  "trades": [
    {
      "id": "t_001",
      "action": "BUY",
      "entry_price": 42000.0,
      "exit_price": 44100.0,
      "entry_time": 1704067200000,
      "exit_time": 1704196800000,
      "quantity": 0.238,
      "profit_loss": 499.8,
      "return_pct": 5.0,
      "status": "CLOSED"
    }
  ]
}
```

---

## 數據

### GET /api/data/{symbol}

取得 K 線數據。

**Query 參數：**

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `interval` | `"1h"` | K 線週期 |
| `start_date` | `"2024-01-01"` | 開始日期 |
| `end_date` | `"2025-01-01"` | 結束日期 |
| `limit` | `500` | 回傳最多幾根 K 棒 |

**範例：**

```
GET /api/data/BTCUSDT?interval=4h&start_date=2024-06-01&end_date=2024-12-01&limit=100
```

**回應範例：**

```json
{
  "symbol": "BTCUSDT",
  "interval": "4h",
  "count": 100,
  "candles": [
    {
      "timestamp": 1717200000000,
      "open": 67500.0,
      "high": 68200.0,
      "low": 67100.0,
      "close": 67800.0,
      "volume": 1234.56
    }
  ]
}
```

---

## Paper Trading（模擬交易）

Paper Trading 讓你用模擬資金測試策略的即時表現，無需真實下單。Session 在背景線程中逐根 K 棒執行策略信號，所有訂單、持倉、資金曲線均持久化到 SQLite。

### POST /api/paper/deploy

部署一個新的 Paper Trading session。

**請求 Body：**

| 欄位 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `symbol` | string | `"BTCUSDT"` | 交易對 |
| `interval` | string | `"1h"` | K 線週期 |
| `strategy_name` | string | `"RSI"` | 策略名稱 |
| `strategy_params` | object | `{}` | 策略參數 |
| `initial_capital` | number | `10000` | 初始資金（USD） |
| `commission_rate` | number | `0.001` | 手續費率（0.1%） |
| `slippage_rate` | number | `0.0005` | 滑點率（0.05%） |
| `data_start_date` | string | `"2024-01-01"` | 數據開始日期 |
| `data_end_date` | string | `"2025-01-01"` | 數據結束日期 |
| `tick_interval_seconds` | number | `1.0` | 每根 K 棒處理間隔（秒） |

**請求範例：**

```json
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "strategy_name": "RSI",
  "strategy_params": {"period": 14, "overbought": 70, "oversold": 30},
  "initial_capital": 10000
}
```

**回應範例：**

```json
{
  "session_id": "a1b2c3d4",
  "state": "running",
  "config": {
    "session_id": "a1b2c3d4",
    "symbol": "BTCUSDT",
    "interval": "1h",
    "strategy_name": "RSI",
    "strategy_params": {"period": 14, "overbought": 70, "oversold": 30},
    "initial_capital": 10000.0,
    "commission_rate": 0.001,
    "slippage_rate": 0.0005
  },
  "candles_processed": 0,
  "signals_generated": 0,
  "account": {
    "total_equity": 10000.0,
    "available_cash": 10000.0,
    "unrealized_pnl": 0.0,
    "realized_pnl": 0.0
  },
  "open_positions": []
}
```

### POST /api/paper/{id}/stop

停止指定 session。

**回應範例：**

```json
{
  "session_id": "a1b2c3d4",
  "state": "stopped",
  "candles_processed": 150,
  "signals_generated": 8,
  "account": {
    "total_equity": 10450.0,
    "available_cash": 10450.0,
    "unrealized_pnl": 0.0,
    "realized_pnl": 450.0
  },
  "open_positions": []
}
```

### POST /api/paper/{id}/close-all

緊急平倉指定 session 的所有持倉。

**回應範例：**

```json
{
  "session_id": "a1b2c3d4",
  "closed_orders": [
    {
      "order_id": "ord_abc123",
      "session_id": "a1b2c3d4",
      "symbol": "BTCUSDT",
      "side": "SELL",
      "order_type": "MARKET",
      "quantity": 0.15,
      "price": 65000.0,
      "status": "FILLED",
      "reason": "Emergency close via API"
    }
  ]
}
```

### GET /api/paper

列出所有 Paper Trading sessions（含活躍和歷史）。

**回應範例：**

```json
{
  "sessions": [
    {
      "session_id": "a1b2c3d4",
      "state": "running",
      "config": {"symbol": "BTCUSDT", "strategy_name": "RSI"},
      "candles_processed": 150,
      "signals_generated": 8,
      "account": {"total_equity": 10450.0},
      "open_positions": []
    },
    {
      "session_id": "e5f6g7h8",
      "state": "stopped",
      "config": {"symbol": "ETHUSDT", "strategy_name": "MACD"},
      "candles_processed": 200,
      "signals_generated": 12,
      "account": {"total_equity": 9800.0},
      "open_positions": []
    }
  ]
}
```

### GET /api/paper/{id}

取得指定 session 的詳細狀態（格式同 deploy 回應）。

### GET /api/paper/{id}/orders

取得指定 session 的所有訂單記錄。

**回應範例：**

```json
{
  "session_id": "a1b2c3d4",
  "orders": [
    {
      "order_id": "ord_001",
      "session_id": "a1b2c3d4",
      "symbol": "BTCUSDT",
      "side": "BUY",
      "order_type": "MARKET",
      "quantity": 0.15,
      "price": 64000.0,
      "status": "FILLED",
      "filled_quantity": 0.15,
      "avg_fill_price": 64032.0,
      "commission": 9.6,
      "created_time": 1704067200000,
      "filled_time": 1704067200000,
      "created_time_str": "2024-01-01 08:00:00",
      "filled_time_str": "2024-01-01 08:00:00",
      "reason": ""
    }
  ]
}
```

### GET /api/paper/{id}/positions

取得指定 session 的所有持倉（含已平倉）。

**回應範例：**

```json
{
  "session_id": "a1b2c3d4",
  "positions": [
    {
      "position_id": "pos_001",
      "session_id": "a1b2c3d4",
      "symbol": "BTCUSDT",
      "side": "LONG",
      "quantity": 0.15,
      "entry_price": 64032.0,
      "entry_time": 1704067200000,
      "exit_price": 65500.0,
      "exit_time": 1704153600000,
      "unrealized_pnl": 0.0,
      "realized_pnl": 220.2,
      "status": "CLOSED",
      "entry_time_str": "2024-01-01 08:00:00",
      "exit_time_str": "2024-01-02 08:00:00"
    }
  ]
}
```

### GET /api/paper/{id}/equity

取得指定 session 的資金曲線數據（可用於繪圖）。

**回應範例：**

```json
{
  "session_id": "a1b2c3d4",
  "equity_curve": [10000.0, 10050.0, 10120.0, 10080.0, 10450.0],
  "timestamps": [1704067200000, 1704070800000, 1704074400000, 1704078000000, 1704081600000],
  "cash_curve": [10000.0, 4020.0, 4020.0, 4020.0, 10450.0]
}
```

---

## 支援的交易對

`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`, `DOGEUSDT`

可在 `data_service.py` 中新增更多。

## 支援的 K 線週期

`1m`, `5m`, `15m`, `1h`, `4h`, `1d`

## 錯誤處理

所有錯誤回傳 HTTP 4xx 狀態碼：

```json
{
  "error": "錯誤說明"
}
```

常見錯誤：

| 狀態碼 | 說明 |
|--------|------|
| 400 | 參數錯誤（如策略不存在、日期格式錯誤） |
| 404 | 回測 ID 或端點不存在 |

## 數據來源

- **主要**: Binance Spot API（自動快取到 SQLite）
- **Fallback**: 合成數據（API 不可用時自動切換，使用幾何布朗運動模擬）
