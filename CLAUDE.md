# CLAUDE.md — Crypto Backtest Platform

> 這份文件是給 Claude Code 讀的專案指引。每次進入這個專案時請先讀這份文件。

## 專案簡介

這是一個 AI 驅動的加密貨幣策略回測平台。核心目的是：

1. **回測驗證** — 用歷史 K 線數據測試交易策略的勝率和盈虧
2. **AI 策略迭代** — 讓 AI Agent 透過 REST API 反覆調參、比較策略、找出最優配置
3. **視覺化分析** — Web UI + Plotly 圖表展示完整績效報告

## 技術棧

- **語言**: Python 3.10+（純 stdlib + pandas + numpy，無需 FastAPI）
- **HTTP Server**: Python `http.server`（內建，零依賴）
- **數據來源**: Binance Spot API `/api/v3/klines`（網路不可用時自動 fallback 到合成數據）
- **快取**: SQLite（`/tmp/klines_cache.db`，歷史數據只拉一次）
- **前端**: 單一 `index.html`（Plotly CDN，無 build 步驟）
- **圖表**: Plotly（後端生成 JSON spec，前端渲染）

## 專案結構

```
crypto-backtest/
├── CLAUDE.md              ← 你正在讀的這份文件
├── README.md              ← 使用者文件
├── ROADMAP.md             ← 未來藍圖
├── CONTRIBUTING.md        ← 新增策略指南
├── API.md                 ← 完整 REST API 文件
├── .claude/
│   ├── settings.json      ← Claude Code 設定
│   └── commands/          ← 自訂 slash commands
│       ├── backtest.md
│       ├── add-strategy.md
│       ├── optimize.md
│       └── research.md       ← AI 自動策略研究工作流
├── backend/
│   ├── app.py             ← HTTP Server 入口 (port 8000)
│   ├── models/__init__.py ← 資料模型 (Candle, Trade, BacktestConfig, BacktestResult)
│   ├── services/
│   │   ├── data_service.py       ← K線拉取 + SQLite 快取 + 合成數據 fallback
│   │   ├── indicator_service.py  ← 技術指標 (RSI, MACD, BB, SMA, EMA, ATR, Stochastic)
│   │   ├── strategy_engine.py    ← 回測引擎（逐根K棒模擬，含滑點+手續費）
│   │   ├── backtest_service.py   ← 回測流程調度（可同步/異步執行）
│   │   └── report_service.py     ← 績效指標 + Plotly 圖表 JSON
│   └── strategies/
│       ├── base_strategy.py      ← 策略基底類別（所有策略繼承它）
│       ├── registry.py           ← 策略自動註冊系統
│       ├── rsi_strategy.py            ← RSI 超買超賣
│       ├── macd_strategy.py           ← MACD 交叉
│       ├── bollinger_strategy.py      ← 布林通道
│       ├── ma_cross_strategy.py       ← 均線交叉
│       ├── momentum_strategy.py       ← 動量突破
│       ├── confluence_strategy.py     ← RSI+MACD 多重確認
│       ├── supertrend_strategy.py     ← SuperTrend 趨勢跟蹤
│       └── volume_breakout_strategy.py ← 量價突破
└── frontend/
    └── index.html          ← Web UI (暗色主題, Plotly 圖表)
```

## 快速啟動

```bash
cd backend
pip install pandas numpy  # 僅需這兩個
python app.py             # http://localhost:8000
```

## 核心架構概念

### 策略系統

所有策略繼承 `BaseStrategy`，實作兩個方法：

- `generate_signal(ohlcv, index)` → 回傳 `TradeSignal("BUY"/"SELL")` 或 `None`
- `metadata()` → 回傳策略名稱、描述、參數 schema

用 `@StrategyRegistry.register` 裝飾器自動註冊。新策略建好後不需要改其他檔案，引擎會自動發現。

### 回測引擎

`StrategyEngine.run()` 逐根 K 棒遍歷：
1. 呼叫策略的 `generate_signal()`
2. BUY → 開多倉（全倉位，含滑點 0.05% + 手續費 0.1%）
3. SELL → 平倉
4. 追蹤資金曲線和回撤
5. 期末強制平倉

目前是**單一倉位**模式（同時只持有一個部位）。

### 數據管線

`data_service.fetch_klines()` 流程：
1. 查 SQLite 快取
2. 快取不足 → 呼叫 Binance API（分批拉取，每次最多 1000 根）
3. API 失敗 → fallback 到合成數據（geometric Brownian motion + mean reversion）
4. 存入快取供下次使用

### API 端點（給 Agent 用）

| Method | Path | 用途 |
|--------|------|------|
| GET | `/api/strategies` | 列出所有策略及參數 schema |
| POST | `/api/backtest/run` | 執行回測（同步，回傳完整結果） |
| GET | `/api/backtest/{id}` | 取得回測結果 |
| GET | `/api/backtest` | 列出所有歷史回測 |
| POST | `/api/backtest/compare` | 多策略批次比較 |
| GET | `/api/reports/{id}/metrics` | 純數字績效指標 |
| GET | `/api/reports/{id}/charts` | Plotly JSON 圖表 |
| GET | `/api/reports/{id}/trades` | 每筆交易明細 |
| GET | `/api/data/{symbol}` | 取得 K 線數據 |

## 開發慣例

### 新增策略的標準流程

1. 在 `backend/strategies/` 建新檔案
2. 繼承 `BaseStrategy`
3. 實作 `metadata()` 和 `generate_signal()`
4. 加上 `@StrategyRegistry.register`
5. 在 `backend/app.py` 的 import 區塊加一行 import

詳細範例見 `CONTRIBUTING.md`。

### Git 工作流

- **每次完成一個動作後都要 commit + push**
- Commit message 用英文，簡潔描述變更
- 加上 `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`

### 程式碼風格

- 型別提示：所有函式都用 type hints
- Docstring：每個 module 和 public 函式都要
- 指標計算：用 `indicator_service.py` 裡的函式，不要在策略裡重新實作
- 策略裡用 `self.cache_indicator()` 快取指標計算結果

### 測試方式

目前沒有正式測試框架，但可以用 API 做 smoke test：

```bash
# 測試所有策略是否能正常執行
curl -X POST http://localhost:8000/api/backtest/compare \
  -H "Content-Type: application/json" \
  -d '{"configs":[
    {"symbol":"BTCUSDT","strategy_name":"RSI"},
    {"symbol":"BTCUSDT","strategy_name":"MACD"},
    {"symbol":"BTCUSDT","strategy_name":"Bollinger Bands"},
    {"symbol":"BTCUSDT","strategy_name":"MA Cross"},
    {"symbol":"BTCUSDT","strategy_name":"Momentum Breakout"},
    {"symbol":"BTCUSDT","strategy_name":"RSI+MACD Confluence"},
    {"symbol":"BTCUSDT","strategy_name":"SuperTrend"},
    {"symbol":"BTCUSDT","strategy_name":"Volume Breakout"}
  ]}'
```

## 已知限制

1. **單一倉位** — 同時只能持有一個部位（不支援多倉位或對沖）
2. **只做多** — 目前只有 LONG 方向（沒有做空邏輯）
3. **無止損/止盈** — 策略信號控制全部進出場
4. **合成數據** — 當 Binance API 不可用時自動 fallback，數據是模擬的
5. **記憶體存儲** — 回測結果存在記憶體，server 重啟後消失
6. **無認證** — API 完全開放，適合本地使用

## 下一步（參考 ROADMAP.md）

短期優先：
- [ ] 加入止損/止盈機制
- [ ] 支援做空
- [x] 加入更多策略（RSI+MACD Confluence、SuperTrend、Volume Breakout）
- [x] AI Agent 自動策略研究工作流（`/research` command）
- [ ] 加入更多策略（Grid Trading、DCA、結合聰明錢信號）
- [ ] 參數優化（grid search / random search）
- [ ] 持久化結果到 SQLite

中期目標：
- [ ] 接入 Binance Skills Hub 的聰明錢信號和代幣審計
- [ ] AI Agent 自動策略迭代 loop
- [ ] 連接 Binance Testnet 做模擬交易
