# CLAUDE.md — Live Trading Module

> `backend/live/` 模組的局部開發指引。

## 架構概覽

- `ExchangeAdapter` ABC → `PaperTradingAdapter`（模擬）/ 未來 `BinanceAdapter`（真實）
- `LiveTradingEngine` 在 daemon thread 中運行策略，透過 `threading.Event` 控制停止
- `TradingPersistence` 用 SQLite 持久化 orders/positions/equity
- `SessionManager` 管理多個 engine 的生命週期

## 常見陷阱

<!-- 以下由 /lesson-common 自動萃取 — 2026-03-09 -->
- **[死鎖]** `PaperTradingAdapter.close_all_positions()` 必須先 snapshot 持倉列表（`list(self._positions.values())`），再逐一呼叫 `place_order(SELL)`。不能在持有 `self._lock` 的情況下呼叫 `place_order`，因為 `place_order` 也會 acquire `self._lock` → 死鎖
- **[SQLite 多線程]** `TradingPersistence` 使用 `threading.local()` 建立 thread-local connections。不能在多線程間共用同一個 SQLite connection，否則會 `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`
- **[重啟恢復]** `SessionManager.__init__()` 中必須呼叫 `_recover_interrupted()` 把 DB 裡 state="running" 的 session 標記為 "interrupted"，否則孤立 session 永遠顯示 running 狀態
- **[PnL 公式差異]** 回測引擎 `StrategyEngine` 用 `qty = (capital - capital * rate) / fill_price`，而 `PaperTradingAdapter` 用 `qty = (cash / (1 + rate)) / fill_price`。兩者結果差約 0.1%，比對時需用容差（2%）
- **[Lock 原則]** 所有共享狀態（`_positions`, `_orders`, `_cash`, `_equity`）都必須在 `self._lock` 保護下讀寫。即使是讀取操作也要加鎖，因為 engine thread 和 API thread 會並行存取
