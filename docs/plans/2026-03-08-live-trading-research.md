# Binance Live Trading 接入研究報告

> 研究目的：評估將現有回測平台接入 Binance 真實交易環境的技術方案、架構變更、風險控制和實施路線。

---

## 一、現有架構分析

### 可直接複用的部分

| 元件 | 現狀 | 複用程度 |
|------|------|----------|
| **策略介面** | `generate_signal(ohlcv, index)` | 高 — 信號生成邏輯不需改變 |
| **指標計算** | `indicator_service.py`（RSI, MACD, BB, ATR, SuperTrend 等）| 高 — 完全複用 |
| **策略註冊** | `@StrategyRegistry.register` 自動發現 | 高 — 完全複用 |
| **數據模型** | Candle, TradeSignal, Trade | 中 — 需擴充新模型 |
| **Binance 連線** | `data_service.py` 已連 `/api/v3/klines` | 中 — 需加認證 |
| **SQLite 快取** | K 線資料快取 | 中 — 可擴充儲存訂單/部位 |

### 需要新增的部分

| 缺口 | 影響 | 工作量 |
|------|------|--------|
| 訂單管理（下單/撤單/狀態追蹤）| 核心功能 | 高 |
| WebSocket 即時數據流 | 即時行情 | 中 |
| API 認證（HMAC 簽名）| 安全性 | 中 |
| 風控系統（止損/倉位限制/熔斷）| 資金安全 | 高 |
| 帳戶狀態追蹤 | 餘額/部位同步 | 中 |
| 異步 Server（現有 http.server 不支援 WebSocket）| 架構升級 | 高 |
| 持久化（訂單/部位/資金曲線存 SQLite）| 當機恢復 | 低 |

---

## 二、Binance API 技術方案

### 2.1 API 類型選擇

| API | 用途 | 建議 |
|-----|------|------|
| **REST API** | 下單/撤單/查詢帳戶/歷史 K 線 | 主要使用 |
| **WebSocket Streams** | 即時行情 + 訂單/帳戶更新 | 必須使用 |
| **WebSocket API** | 透過 WebSocket 下單（低延遲）| 可選，進階優化 |
| **FIX API** | 機構級超低延遲 | 不需要 |

### 2.2 認證機制

- **API Key + Secret**：在 Binance 帳戶管理頁面建立
- **簽名方式**：HMAC-SHA256（最簡單）或 Ed25519（更安全）
- **權限設定**：只開 Read + Spot Trading，**絕不開提幣權限**
- **IP 白名單**：建議綁定 Bot 的固定 IP
- **2026 新規**：payload 需先 percent-encode 再簽名，否則返回 `-1022`

### 2.3 Python 套件比較

| 套件 | 維護者 | 優點 | 缺點 | 建議 |
|------|--------|------|------|------|
| `binance-connector` | Binance 官方 | API 相容性保證、易切 Testnet | 無內建 async | 首選 |
| `python-binance` | 社群 | 最多人用、有 async WebSocket | 非官方、可能落後 | 備選 |
| `ccxt` | CCXT 團隊 | 支援 100+ 交易所 | 較肥、Pro 版商用付費 | 未來多交易所時 |

**推薦**：`binance-connector-python`（官方套件，一行切換 Testnet）

```python
from binance.spot import Spot

# Testnet
client = Spot(api_key="...", api_secret="...",
              base_url="https://testnet.binance.vision")

# Production — 只改 base_url
client = Spot(api_key="...", api_secret="...",
              base_url="https://api.binance.com")
```

### 2.4 可用的訂單類型

| 類型 | 說明 | 回測對應 |
|------|------|----------|
| `MARKET` | 市價單，立即成交 | 目前回測模擬的方式 |
| `LIMIT` | 限價單，到價才成交 | 目前不支援 |
| `STOP_LOSS` | 到價觸發市價單（止損）| 目前不支援 |
| `STOP_LOSS_LIMIT` | 到價觸發限價單 | 目前不支援 |
| `TAKE_PROFIT` | 到價觸發市價單（止盈）| 目前不支援 |
| `OCO` | 一組止盈+止損，成交一個自動撤另一個 | 目前不支援 |
| `TRAILING_STOP` | 追蹤止損，用 BIPS 指定 | 目前不支援 |

### 2.5 Rate Limits

| 限制 | 範圍 | 預設值 |
|------|------|--------|
| REQUEST_WEIGHT | 每 IP / 分鐘 | 6,000 weight |
| ORDERS | 每帳戶 / 10 秒 | 50 單 |
| ORDERS | 每帳戶 / 24 小時 | 160,000 單 |

下單 weight = 1，查帳戶 weight = 20。需監控 `X-MBX-USED-WEIGHT-1M` header。

### 2.6 WebSocket Streams

**行情數據**（無需認證）：
```
wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1h/btcusdt@trade
```

**用戶數據**（需認證，即時訂單/帳戶更新）：
1. POST `/api/v3/userDataStream` → 取得 `listenKey`
2. 連接 `wss://stream.binance.com:9443/ws/<listenKey>`
3. 每 30 分鐘 PUT keepalive（60 分鐘過期）

事件類型：
- `executionReport` — 訂單狀態變更（NEW/FILLED/CANCELLED）
- `outboundAccountPosition` — 帳戶餘額變更

---

## 三、架構設計

### 3.1 架構模式：Hybrid（事件驅動 + REST 回退）

```
┌─────────────────────────────────────────────────────────────┐
│                     Live Trading Engine                      │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ WebSocket │───>│  Event   │───>│ Strategy │              │
│  │  Streams  │    │   Bus    │    │  Engine  │              │
│  └──────────┘    └────┬─────┘    └────┬─────┘              │
│                       │               │                     │
│                       v               v                     │
│               ┌──────────┐    ┌──────────┐                 │
│               │   Risk   │<───│  Signal  │                 │
│               │ Manager  │    │  Event   │                 │
│               └────┬─────┘    └──────────┘                 │
│                    │                                        │
│                    v                                        │
│  ┌──────────────────────────────────────────┐              │
│  │          Exchange Adapter (介面)          │              │
│  │                                          │              │
│  │  ┌─────────────┐  ┌─────────────┐       │              │
│  │  │   Paper     │  │  Binance    │       │              │
│  │  │  Adapter    │  │  Adapter    │       │              │
│  │  │ (模擬成交)   │  │ (真實下單)   │       │              │
│  │  └─────────────┘  └─────────────┘       │              │
│  └──────────────────────────────────────────┘              │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │  SQLite  │    │  Logger  │    │ Alerter  │              │
│  │  持久化   │    │  日誌系統  │    │ Telegram │              │
│  └──────────┘    └──────────┘    └──────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心設計決策

| 決策 | 方案 | 理由 |
|------|------|------|
| Exchange Adapter 模式 | 統一介面，Paper/Live 實現 | 一行切換，策略程式碼零修改 |
| Server 框架 | `aiohttp`（async HTTP + WebSocket）| 最小依賴，支援 async |
| 訂單執行 | 先 MARKET 為主，後加 LIMIT/STOP | 降低複雜度 |
| 即時數據 | WebSocket Klines + REST 回退 | 速度+可靠性 |
| 帳戶同步 | User Data Stream + 定期 REST reconcile | 即時+準確 |
| 持久化 | SQLite（擴充現有 `klines_cache.db`）| 零依賴 |

### 3.3 新增模組結構

```
backend/
├── live/                            # 新模組
│   ├── __init__.py
│   ├── engine.py                    # LiveTradingEngine（主迴圈）
│   ├── event_bus.py                 # 事件發布/訂閱
│   ├── config.py                    # 交易設定（mode, keys, limits）
│   ├── adapters/
│   │   ├── base_adapter.py          # ExchangeAdapter ABC
│   │   ├── paper_adapter.py         # PaperTradingAdapter
│   │   └── binance_adapter.py       # BinanceAdapter
│   ├── risk/
│   │   ├── risk_manager.py          # 風控檢查 + 熔斷
│   │   ├── position_sizer.py        # 倉位計算（Kelly/固定比例）
│   │   └── kill_switch.py           # 緊急停止
│   ├── state/
│   │   ├── portfolio.py             # 投資組合狀態
│   │   ├── position_manager.py      # 多部位管理
│   │   └── persistence.py           # SQLite 持久化
│   └── monitoring/
│       ├── logger.py                # 結構化日誌
│       ├── alerter.py               # Telegram 通知
│       └── health_check.py          # 健康檢查
├── strategies/                      # 現有 — 雙模式共用
└── services/                        # 現有 — indicator_service 共用
```

### 3.4 需要新增的資料模型

```python
@dataclass
class LiveOrder:
    order_id: str              # Binance orderId
    symbol: str
    side: str                  # BUY / SELL
    order_type: str            # MARKET / LIMIT / STOP_LOSS
    quantity: float
    price: float
    status: str                # NEW / FILLED / CANCELLED / REJECTED
    filled_quantity: float
    avg_fill_price: float
    commission: float
    created_time: int
    filled_time: int

@dataclass
class AccountState:
    total_balance: float       # USD 總值
    available_balance: float   # 可用餘額
    unrealized_pnl: float      # 未實現盈虧
    update_time: int

@dataclass
class Position:
    symbol: str
    side: str                  # LONG
    quantity: float
    entry_price: float
    entry_time: int
    stop_loss_price: float
    take_profit_price: float
    unrealized_pnl: float
    status: str                # OPEN / CLOSED
```

---

## 四、風控系統設計

### 4.1 四層防護

| 層級 | 功能 | 觸發動作 |
|------|------|----------|
| **L1 下單前檢查** | 倉位大小、重複訂單、價格合理性 | 拒絕訂單 |
| **L2 持倉監控** | 止損/止盈、最大持倉時間 | 強制平倉 |
| **L3 組合熔斷** | 日虧 > 3%、回撤 > 10%、日交易數上限 | 暫停交易 24h |
| **L4 緊急停止** | Kill Switch（API/鍵盤/檔案觸發）| 撤所有單 + 平所有倉 |

### 4.2 關鍵風控參數

| 參數 | 建議值 | 說明 |
|------|--------|------|
| 單筆最大倉位 | 總資金的 2% | 防止單筆爆倉 |
| 最大同時持倉 | 3 個 | 分散風險 |
| 單日最大虧損 | 3-5% | 觸發暫停 |
| 最大回撤 | 10% | 觸發冷靜期 |
| 止損 | -3% per trade | 限制單筆損失 |
| 每日最大交易數 | 50 | 防止過度交易 |

---

## 五、從回測到實盤的常見陷阱

| 陷阱 | 我們的現況 | 解法 |
|------|-----------|------|
| **前視偏差** | `generate_signal()` 收到完整 `ohlcv`，可能讀到未來數據 | Live 模式只傳到 index 為止的數據 |
| **即時成交假設** | 回測用 `candle.close` 即時成交 | 加入執行延遲模擬，用下一根 K 棒 open |
| **全倉進出** | 每次 100% 資金進場 | 改成 fractional position sizing（1-2%） |
| **無部分成交** | 假設全部成交 | 追蹤 filled_quantity，處理部分成交 |
| **固定滑點** | 固定 0.05% | 改用動態滑點（依成交量/波動率）|
| **單一倉位** | 同時只持有 1 個部位 | 支援多部位管理 |
| **無當機恢復** | 全存記憶體 | SQLite 持久化 + 重啟 reconcile |
| **WebSocket 斷線** | 沒有 WebSocket | 自動重連 + 指數退避 |

---

## 六、Binance Testnet 測試環境

| 項目 | 細節 |
|------|------|
| URL | https://testnet.binance.vision |
| REST endpoint | `https://testnet.binance.vision/api` |
| WebSocket | `wss://testnet.binance.vision/ws` |
| 註冊方式 | 用 GitHub 帳號登入 |
| 資金 | 虛擬資金，自動發放 |
| 限制 | 只支援 `/api/*`，不支援 `/sapi/*` |
| 注意 | 會定期重置，流動性與正式環境不同 |

### 遷移路徑

```
回測引擎（現在）──> Paper Trading ──> Testnet ──> 正式環境
     │                  │              │            │
  歷史數據           即時行情+      虛擬資金+      真實資金
  模擬成交          模擬成交       交易所撮合     交易所撮合
  無網路延遲        有網路延遲      有 Rate Limit   完全真實
```

---

## 七、實施路線圖

### Phase 1：基礎建設（1-2 週）

- [ ] 建立 `backend/live/` 模組結構
- [ ] 實作 `ExchangeAdapter` 介面（ABC）
- [ ] 實作 `PaperTradingAdapter`（模擬成交）
- [ ] 新增 `LiveOrder`, `AccountState`, `Position` 資料模型
- [ ] WebSocket 基礎建設（kline stream 接收）
- [ ] SQLite 擴充（orders, positions, equity_snapshots 表）

### Phase 2：策略適配（1 週）

- [ ] 建立 `LiveTradingEngine`（用 WebSocket 驅動，非歷史遍歷）
- [ ] 適配現有策略到 live 模式（滑動視窗取代全量數據）
- [ ] 即時指標計算快取修正

### Phase 3：風控系統（1 週）

- [ ] 實作 `RiskManager`（下單前檢查 + 熔斷）
- [ ] 實作 `PositionSizer`（fractional sizing）
- [ ] 實作 `KillSwitch`（API endpoint + 檔案觸發）
- [ ] 止損/止盈邏輯（用 Binance 原生 STOP_LOSS/OCO）

### Phase 4：Binance 接入（1-2 週）

- [ ] 安裝 `binance-connector-python`
- [ ] 實作 `BinanceAdapter`（REST 下單 + WebSocket user data stream）
- [ ] API 認證（HMAC-SHA256 簽名）
- [ ] Rate Limiter
- [ ] 連線健康監控 + 自動重連

### Phase 5：監控與通知（1 週）

- [ ] 結構化日誌系統
- [ ] Telegram 通知（訂單成交、風控觸發、異常）
- [ ] 帳戶狀態 Dashboard（Web UI 擴充）
- [ ] 每日績效報告自動發送

### Phase 6：測試與上線（1-2 週）

- [ ] Paper Trading 完整測試（跑 1 週）
- [ ] Binance Testnet 端對端測試
- [ ] 最小資金正式上線（$100-500）
- [ ] 單策略先跑，觀察 1 週再加策略

### 預估總工期：6-10 週

---

## 八、新增依賴

| 套件 | 用途 | 大小 |
|------|------|------|
| `binance-connector` | Binance 官方 API 客戶端 | 輕量 |
| `aiohttp` | Async HTTP + WebSocket server | 輕量 |
| `websockets` | WebSocket 客戶端 | 輕量 |

目前專案只依賴 `pandas` + `numpy`，新增 3 個套件。

---

## 九、安全注意事項

1. API Key/Secret **絕不寫在程式碼裡**，用環境變數或加密檔案
2. 只開 Read + Spot Trading 權限，**永遠不開提幣**
3. 綁定 IP 白名單
4. 所有私有 API 呼叫必須 HMAC 簽名 + timestamp
5. listenKey 每 30 分鐘 keepalive
6. 絕不在日誌中印出 API Key/Secret
7. 先 Testnet 測完再上正式環境
8. 初始上線用最小資金（$100-500）

---

## 十、結論

現有回測平台的**策略層**設計良好，`generate_signal()` 介面可以直接複用。主要工作在**執行層**：

1. **最大挑戰**：從同步遍歷改為事件驅動的即時引擎
2. **最重要功能**：風控系統（沒有風控的實盤 = 賭博）
3. **最安全路徑**：Paper Trading → Testnet → 最小資金上線
4. **建議起手**：先做 Phase 1（Paper Trading），用真實行情 + 模擬成交驗證整個流程
