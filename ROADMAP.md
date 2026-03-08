# Roadmap

Crypto Backtest Platform 的未來發展藍圖。

## v0.1 — 基礎回測 (已完成)

- [x] 5 個內建策略（RSI、MACD、Bollinger Bands、MA Cross、Momentum Breakout）
- [x] Binance K 線數據 + SQLite 快取
- [x] 合成數據 fallback
- [x] 逐根 K 棒回測引擎（滑點 + 手續費）
- [x] 完整績效指標（Sharpe、Sortino、MDD、勝率、盈虧比）
- [x] Plotly 互動式圖表（K 線、資金曲線、回撤、月報酬）
- [x] Web UI + REST API
- [x] 多策略比較 API

## v0.2 — 策略強化

- [ ] **多時間框架分析** — 例如用 4h 判斷趨勢方向，1h 進場
- [x] **止損/止盈** — 固定比例止損/止盈（透過 `stop_loss_pct` / `take_profit_pct` 設定）
- [ ] **槓桿支援** — 合約交易槓桿倍數（2x~10x），需搭配止損機制使用
- [ ] **倉位管理** — 支援分批進場/出場、固定風險比例下注（Kelly Criterion）
- [x] **做空支援** — SHORT/COVER 信號，回測引擎完整支援空倉邏輯
- [ ] **策略組合** — 多策略信號投票機制（2/3 策略同意才進場）
- [ ] **更多內建策略** — Ichimoku Cloud、VWAP、Volume Profile、SuperTrend

## v0.3 — AI 優化引擎

- [ ] **參數網格搜尋** — 自動遍歷參數空間找最佳組合
- [ ] **Walk-Forward 驗證** — In-sample 優化 + Out-of-sample 驗證，防止過擬合
- [ ] **AI 策略研究員** — Claude 自動分析回測結果，建議參數調整方向
- [ ] **過擬合偵測** — 比較 in-sample 與 out-of-sample 表現差異
- [ ] **蒙地卡羅模擬** — 用隨機打亂交易順序評估策略穩健性
- [ ] **Random Search** — 參數組合太多時用隨機搜尋替代窮舉

## v0.4 — 數據與市場

- [ ] **更多交易所** — Bybit、OKX、Hyperliquid（DEX）
- [ ] **鏈上數據整合** — DeFi 協議 TVL、資金費率、大戶持倉
- [ ] **鏈上 K 線** — 透過 dquery.sintral.io 取得 DeFi 代幣價格
- [ ] **新聞/情緒指標** — Fear & Greed Index、社群聲量
- [ ] **即時數據** — WebSocket 串流 K 線（為實盤做準備）

## v0.5 — 進階報告

- [ ] **策略相關性矩陣** — 分析策略之間的報酬相關性
- [ ] **風險分析報告** — VaR、CVaR、Calmar Ratio
- [ ] **交易成本分析** — 不同手續費/滑點下的敏感度分析
- [ ] **基準比較** — 與 Buy & Hold、SPY 等基準策略比較
- [ ] **PDF 報告匯出** — 生成完整的回測報告 PDF
- [ ] **回測結果持久化** — 存入 SQLite，支援歷史查詢

## v0.6 — 實盤橋接

- [x] **Paper Trading** — 用即時數據模擬交易（不下真單）
- [ ] **Binance API 整合** — 透過 Binance Skills 下單（需用戶授權）
- [ ] **風控模組** — 單日最大虧損限制、單筆最大倉位限制
- [ ] **告警系統** — 策略信號通知（Telegram / Discord / Email）
- [ ] **交易日誌** — 記錄每筆實盤交易與對應的回測預期

## v1.0 — 生產環境

- [ ] **使用者系統** — 多用戶支援、API Key 管理
- [ ] **策略市場** — 社群共享策略（含績效驗證）
- [ ] **排程回測** — 定時自動執行回測並產生報告
- [ ] **Dashboard** — 即時監控多策略運行狀態
- [ ] **Docker 部署** — 一鍵啟動的容器化方案

## 貢獻

歡迎提交 PR 或開 Issue 討論功能需求。詳見 [CONTRIBUTING.md](CONTRIBUTING.md)。
