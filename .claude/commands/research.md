# /research — AI 自動策略研究工作流

針對指定幣種/週期，自動完成「研究 → 實作 → 驗證 → 迭代」的完整循環。

## 使用方式

```
/research BTCUSDT 1h
/research ETHUSDT 4h 2023-01-01 2024-01-01
```

## 參數

- `$ARGUMENTS` 格式：`SYMBOL INTERVAL [START_DATE] [END_DATE]`
- 預設：BTCUSDT 1h 2024-01-01 2025-01-01

## 執行流程

### Phase 1: 環境確認
1. 確認 server 正在運行（port 8000），如果沒有就啟動：
   ```bash
   cd backend && nohup python app.py &
   ```
2. 拉取目前所有策略：
   ```bash
   curl -s http://localhost:8000/api/strategies
   ```

### Phase 2: Baseline 建立
1. 對所有現有策略跑回測（用 `/api/backtest/compare`）
2. 記錄 baseline 指標表格（報酬、夏普、回撤、勝率、交易數）
3. 計算 Buy & Hold 基準：用 `/api/data/{SYMBOL}` 取得首尾價格算漲跌幅
4. 計算 DCA 基準（Weekly + Monthly）：用同樣的 K 線數據模擬定投

### Phase 3: 策略研究
1. 根據 baseline 結果分析不足之處（例如：回撤太大、勝率太低、信號太少）
2. 搜尋適合該幣種/週期的策略思路（考慮該幣種的波動特性）
3. 決定新策略的方向：
   - 如果現有策略回撤太大 → 偏向保守/組合指標策略
   - 如果現有策略信號太少 → 偏向靈敏度更高的策略
   - 如果現有策略趨勢捕捉差 → 偏向趨勢跟蹤策略
4. 設計策略邏輯（進場、出場條件）

### Phase 4: 策略實作
1. 在 `backend/strategies/` 建立新策略檔案，遵循 BaseStrategy 模板
2. 加上 `@StrategyRegistry.register` 裝飾器
3. 在 `backend/app.py` 的 import 行加入新策略
4. 重啟 server 並確認策略出現在 `/api/strategies`

### Phase 5: 回測驗證
1. 用預設參數跑一次回測
2. 用 grid search 做參數優化（每次最多 20 組）：
   - 按 Sharpe Ratio 排序
   - 剔除 Max Drawdown > 30% 的組合
   - 剔除交易次數 < 10 的組合
3. 用最佳參數再跑一次回測
4. 跟所有策略做完整比較

### Phase 6: Walk-Forward 驗證
1. 用前 70% 數據做 in-sample 優化（找最佳參數）
2. 用後 30% 數據做 out-of-sample 驗證
3. 計算 OOS 衰退率 = (IS_return - OOS_return) / IS_return
4. 如果 OOS 衰退 > 50%，警告過度擬合

### Phase 7: 迭代優化（最多 2 輪）
如果策略不符合門檻，進行調整：
- 修改策略邏輯（例如增加過濾條件）
- 調整參數範圍
- 嘗試不同的指標組合
- 回到 Phase 5 重新驗證

#### 通過門檻
| 指標 | 門檻 |
|------|------|
| 交易數 | >= 10 |
| 夏普比率 | > 0.5 |
| 最大回撤 | < 30% |
| OOS 衰退 | < 50% |
| 勝率 | > 40% |

### Phase 8: 最終報告 + 存檔

#### 8a. 更新策略預設參數
將最佳參數寫入策略檔案的 `metadata()` 的 `default` 值，這樣 UI 選策略時自動帶入。

#### 8b. 儲存研究報告
將完整報告寫入 `docs/research/YYYY-MM-DD-{strategy-name}.md`，格式如下：
```markdown
# Research Report: {Strategy Name}
- **Date:** YYYY-MM-DD
- **Symbol:** {SYMBOL}
- **Interval:** {INTERVAL}
- **Period:** {START} ~ {END}
- **Status:** PASSED / FAILED

## Strategy Logic
（進出場邏輯描述）

## Optimized Parameters
（JSON 格式的最佳參數）

## Performance (Full Period)
（Return, Win Rate, PF, Sharpe, MaxDD, Trades）

## Benchmark Comparison
（vs Buy & Hold, DCA Weekly, DCA Monthly, 其他策略）

## Walk-Forward Validation
（IS vs OOS, Decay rate）

## Quality Gates
（每項門檻通過/失敗）

## Confidence: High / Medium-High / Medium / Low

## Known Limitations

## Grid Search Top 5
```

#### 8c. 最終輸出
在對話中輸出簡潔的結論摘要，包含：
1. 策略名稱和邏輯描述
2. 最佳參數組合
3. 完整績效指標（含 IS 和 OOS）
4. 與所有現有策略 + DCA + Buy & Hold 的比較表
5. 信心評級（高/中/低）和使用建議
6. 已知限制和適用行情類型
7. 報告存檔路徑

## 注意事項
- 每次 compare API 最多放 20 個 config
- 參數組合超過 100 個時用 random search
- 合成數據時要特別註明，結果僅供參考
- 新策略用 `self.cache_indicator()` 快取指標
- 指標計算用 `services/indicator_service.py` 裡的函式
- 每個 Phase 完成後都要 commit + push
- DCA 基準計算方式：Weekly（每 168 根 1h K 棒投入等額）、Monthly（每 720 根）
- 報告存檔路徑：`docs/research/YYYY-MM-DD-{strategy-name}.md`
- 最佳參數同時更新到策略檔案的 `metadata()` default 值，確保 UI 預設就是最佳參數

## 現有研究報告
- `docs/research/2026-03-09-trend-rider.md` — Trend Rider (+68%, beats DCA)
