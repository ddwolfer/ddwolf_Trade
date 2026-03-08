# Crypto Backtest Platform

AI 驅動的加密貨幣策略回測平台。提供 Web UI 和 REST API 兩種介面。

## 功能

- **5 個內建策略** — RSI、MACD、Bollinger Bands、MA Cross、Momentum Breakout
- **完整績效報告** — 勝率、Sharpe Ratio、Sortino Ratio、最大回撤、盈虧比、月報酬分布
- **互動式圖表** — K 線 + 交易標記、資金曲線、回撤圖、月報酬柱狀圖
- **REST API** — 給 AI Agent 用的純 JSON API，支援批次比較
- **可擴展** — 新增策略只需一個 Python 檔案

## 快速開始

```bash
# 1. 安裝依賴（僅需 pandas + numpy）
pip install pandas numpy

# 2. 啟動 server
cd backend
python app.py

# 3. 開啟瀏覽器
# http://localhost:8000
```

## Web UI

左側選擇策略、調整參數、設定日期範圍，按下 Run Backtest。右側顯示完整績效指標和互動式圖表。

## API 使用

### 列出策略

```bash
curl http://localhost:8000/api/strategies
```

### 執行回測

```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "interval": "1h",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01",
    "initial_capital": 10000,
    "strategy_name": "RSI",
    "strategy_params": {"period": 14, "overbought": 70, "oversold": 30}
  }'
```

### 多策略比較

```bash
curl -X POST http://localhost:8000/api/backtest/compare \
  -H "Content-Type: application/json" \
  -d '{
    "configs": [
      {"symbol":"BTCUSDT","strategy_name":"RSI"},
      {"symbol":"BTCUSDT","strategy_name":"MACD"},
      {"symbol":"BTCUSDT","strategy_name":"MA Cross"}
    ]
  }'
```

完整 API 文件見 [API.md](API.md)。

## 新增策略

在 `backend/strategies/` 建新檔案，繼承 `BaseStrategy` 即可。詳見 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 數據來源

- **主要**: Binance Spot API（自動快取到 SQLite）
- **Fallback**: 合成數據（當 API 不可用時自動切換）

支援幣對：BTCUSDT、ETHUSDT、BNBUSDT、SOLUSDT、XRPUSDT、DOGEUSDT（可自行新增）

## 技術細節

- Python 3.10+ / 純 stdlib HTTP server
- pandas + numpy（唯二外部依賴）
- Plotly（CDN，無 build）
- SQLite 快取

## 授權

MIT
