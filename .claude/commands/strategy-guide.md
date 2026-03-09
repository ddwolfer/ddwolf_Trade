# /strategy-guide — 策略開發經驗指南

根據過去開發 11 個策略的經驗，提供策略設計模式、常見陷阱、和最佳實踐。
在開始設計新策略之前先讀這份指南，能少走很多彎路。

## 使用方式

```
/strategy-guide                    # 顯示完整指南
/strategy-guide trend              # 趨勢跟蹤策略建議
/strategy-guide short              # 做空策略建議
/strategy-guide dual               # 雙向策略建議
```

## 策略分類與設計模式

### 1. 動量 / 趨勢跟蹤 (Trend Following)

**特徵：** 順勢操作，信號少但持倉久，在趨勢市場表現好。

**代表策略：**
- **Trend Rider** — EMA 交叉進場 + ATR 追蹤止損出場
- **SuperTrend** — SuperTrend 翻轉做多/做空
- **MA Cross** — 均線黃金交叉/死亡交叉

**設計要點：**
```
進場 = 趨勢確認信號（EMA 交叉、SuperTrend 翻轉）
出場 = 反向信號 OR 追蹤止損
```
- ✅ 用長期 EMA 過濾器避免逆勢開倉（Trend Rider 用 EMA100 過濾）
- ✅ ATR trailing stop 比固定止損更適合趨勢策略（跟著波動自動調整）
- ✅ 寬鬆的止損（ATR 4x）比緊的好 — 避免趨勢途中被震出
- ❌ 在盤整市場會頻繁止損，需要搭配趨勢過濾

**從 Trend Rider 學到的：**
- `atr_multiplier` = 4.0 表現最好（1.0-3.0 太緊，5.0-6.0 太鬆）
- 加上 `trend_filter_ema` 大幅減少假信號（從 80+ 交易降到 46 筆）
- Walk-Forward 衰退率 22%，說明沒有過度擬合

### 2. 均值回歸 (Mean Reversion)

**特徵：** 反向操作，在超買超賣時進場，信號多但持倉短。

**代表策略：**
- **RSI** — RSI 超賣買入、超買賣出
- **Bollinger Bands** — 觸及下軌買入、上軌賣出
- **Bear Hunter** — 做空超買反彈（均值回歸做空版）

**設計要點：**
```
進場 = 超買/超賣 + 動量反轉確認
出場 = 回到中性區域 OR 止損
```
- ✅ 用兩階段出場：RSI 極值（快速獲利）+ 中線交叉（趨勢跟隨）
- ✅ Bear Hunter 的經驗：regime 只過濾進場，不過濾出場（避免 EMA whipsaw 造成提前平倉）
- ✅ 做空策略的 RSI overbought 可以設低一點（65 而非 70），捕捉更多信號
- ❌ 純均值回歸在強趨勢中會被套死，需要止損保護

**從 Bear Hunter 學到的：**
- 原始版本用 EMA regime 同時過濾進場和出場 → 出場太慢，虧損放大
- 修正：regime 只控制進場，出場純看 RSI → 回撤大幅改善
- RSI midline exit（45）是關鍵 — 動量衰減就平倉，不等到超賣

### 3. 多重確認 (Composite / Confluence)

**特徵：** 多指標交叉驗證，信號最少但品質最高。

**代表策略：**
- **RSI+MACD Confluence** — RSI 超賣 + MACD 柱狀圖翻正才買入

**設計要點：**
```
進場 = 條件A AND 條件B（兩個獨立指標同時確認）
出場 = 其中一個條件反轉就出場（更保守）
```
- ✅ 減少假信號的最有效方法
- ✅ 用 `hist_prev < 0` 確認 MACD 柱狀圖是從負轉正（不只是變大）
- ❌ 信號太少可能錯過行情 → 可以放寬 RSI 門檻（35 而非 30）

### 4. 雙向策略 (Dual-Direction)

**特徵：** 同時做多做空，牛熊市都能獲利。

**代表策略：**
- **Trend Surfer** — SuperTrend + EMA 雙重確認，多空切換

**設計要點（最複雜）：**
```
做多進場 = 趨勢翻多 AND EMA 確認多頭
做空進場 = 趨勢翻空 AND EMA 確認空頭
純出場   = 趨勢翻轉但 EMA 未確認（只平倉不反向開倉）
```
- ✅ **四信號架構**：BUY（開多）、SELL（平多）、SHORT（開空）、COVER（平空）
- ✅ 引擎自動處理反轉（收到 BUY 時若持空倉，會先平空再開多）
- ✅ 區分「反轉開倉」和「純出場」— Trend Surfer 的精髓：
  - SuperTrend 翻轉 + EMA 確認 → 反向開倉（BUY 或 SHORT）
  - SuperTrend 翻轉 + EMA 不確認 → 純出場（SELL 或 COVER）
- ❌ 盤整市場兩邊都虧，需要更寬的 SuperTrend multiplier

**從 Trend Surfer 學到的：**
- 不要簡單地「多空對稱」— 空頭確認需要比多頭更保守
- `prev_dir` vs `curr_dir` 偵測翻轉比用連續方向更可靠
- EMA 不確認時只出場不反開 — 這個設計避免了震盪市場的反覆開倉

---

## 指標使用經驗

### 指標組合推薦

| 策略類型 | 推薦指標組合 | 原因 |
|----------|-------------|------|
| 趨勢跟蹤 | EMA + ATR trailing stop | ATR 自適應波動，EMA 確認趨勢 |
| 均值回歸 | RSI + EMA trend filter | RSI 找極值，EMA 過濾趨勢避免逆勢 |
| 做空 | EMA regime + RSI entry/exit | regime 只過濾進場，RSI 獨立管出場 |
| 雙向 | SuperTrend + EMA cross | SuperTrend 定方向，EMA 做確認 |
| 保守 | RSI + MACD histogram | 雙重確認減少假信號 |

### 指標快取注意事項

```python
# ✅ 正確：用 lambda + cache_indicator
rsi = self.cache_indicator(f"rsi_{period}", lambda: ind.rsi(closes, period))

# ❌ 錯誤：直接計算（每根 K 棒都重新算整個序列）
rsi = ind.rsi(closes, period)

# ✅ 正確：cache key 包含所有參數
st = self.cache_indicator(f"supertrend_{atr_period}_{multiplier}", lambda: ...)

# ❌ 錯誤：cache key 不包含參數（參數改了但讀到舊的快取）
st = self.cache_indicator("supertrend", lambda: ...)
```

### 指標值的空值檢查

```python
# ✅ 正確：檢查 None 才使用
if fast_ema[index] is None or slow_ema[index] is None:
    return None

# ❌ 錯誤：直接比較（None 比較會 crash 或產生錯誤信號）
if fast_ema[index] > slow_ema[index]:  # 💥 TypeError if None
```

---

## 常見陷阱與解決方案

### 1. Warmup 期不足
```python
# ✅ 正確：取所有指標中最長的 + buffer
min_period = max(slow_ema_period, atr_period, rsi_period) + 2
if index < min_period:
    return None
```

### 2. 做空止損方向弄反
```
LONG  止損：candle.low  ≤ entry * (1 - sl_pct)  ← 用 low
SHORT 止損：candle.high ≥ entry * (1 + sl_pct)  ← 用 high（方向相反！）
```

### 3. 策略反轉時的倉位處理
引擎已自動處理：收到 BUY 時若持空倉 → 先平空再開多。
**但策略要注意**：不要在同一根 K 棒同時發 SELL + SHORT（只發 SHORT 即可，引擎會自動平多）。

### 4. EMA 交叉偵測
```python
# ✅ 正確：用 prev vs curr 偵測交叉點
crossed_above = prev_fast <= prev_slow and curr_fast > curr_slow

# ❌ 錯誤：只看當前狀態（每根都發信號，交易過多）
if curr_fast > curr_slow:  # 不是交叉，是狀態
```

### 5. 出場策略分離
- **進場**可以用嚴格的多重過濾（例如 regime + 指標確認）
- **出場**要獨立於進場條件 — 不然 regime 改變時可能無法出場
- Bear Hunter 的教訓：regime 過濾出場 → 延遲平倉 → 虧損擴大

### 6. SuperTrend 方向值
```python
# SuperTrend direction: 1 = bullish, -1 = bearish, 0 = insufficient data
# ✅ 先檢查 0
if curr_dir == 0 or prev_dir == 0:
    return None
```

---

## 參數優化經驗

### Grid Search 要點
1. 每批最多 20 組（API 限制）
2. 先用粗步長找範圍，再用細步長微調
3. **必做**：排除 Max Drawdown > 30% 和交易數 < 10 的結果

### Walk-Forward 驗證（防過擬合的關鍵）
```
In-Sample:  前 70% 數據 → 找最佳參數
Out-of-Sample: 後 30% 數據 → 用 IS 最佳參數驗證

衰退率 = (IS_return - OOS_return) / abs(IS_return) * 100%

< 30% → 穩健，可以用
30-50% → 輕微過擬合，謹慎使用
> 50% → 嚴重過擬合，重新設計
```

### 參數穩健性檢查
看 Grid Search Top 5 — 如果前 5 名的參數值很接近，說明參數穩健。
如果 Top 1 和 Top 2-5 差距很大，可能只是碰巧。

---

## 新策略開發 Checklist

1. **定義策略類型**（趨勢/均值回歸/多重確認/雙向）
2. **選擇指標組合**（參考上面的推薦表）
3. **設計信號邏輯**
   - 進場條件要有兩層（信號 + 過濾）
   - 出場條件要獨立於進場過濾
4. **設定合理的 warmup 期**（所有指標最長期 + 2）
5. **處理 None 值**（指標初期可能為 None）
6. **寫 metadata()**
   - 參數的 min/max/default 設合理範圍
   - description 要清楚（會顯示在 UI 和翻譯檔）
7. **註冊**（`@StrategyRegistry.register` + app.py import）
8. **測試**
   - 交易數 > 0
   - 勝率不是 0% 或 100%
   - 做空策略要有 SHORT 交易
9. **優化**（`/optimize` 命令）
10. **Walk-Forward 驗證**（`/research` 命令的 Phase 6）
11. **更新翻譯**（`frontend/locales/en.json` 和 `zh-TW.json` 加策略描述和參數翻譯）

---

## 可用的工具鏈

| 命令 | 用途 |
|------|------|
| `/add-strategy` | 從零建立新策略（模板 + 註冊 + 測試） |
| `/backtest STRATEGY_NAME` | 快速回測單一策略 |
| `/optimize STRATEGY_NAME` | Grid Search 參數優化 + Walk-Forward |
| `/research SYMBOL INTERVAL` | 完整研究循環（Baseline → 設計 → 實作 → 驗證 → 迭代） |
| `/strategy-guide` | 你正在讀的這份指南 |

## 現有策略清單（11 個）

| 策略 | 類型 | 方向 | 核心邏輯 |
|------|------|------|---------|
| RSI | 均值回歸 | LONG | RSI 超賣買、超買賣 |
| MACD | 動量 | LONG | MACD 交叉 |
| Bollinger Bands | 均值回歸 | LONG | 觸及上下軌 |
| MA Cross | 趨勢跟蹤 | LONG | 均線交叉 |
| Momentum Breakout | 動量 | LONG | N 期新高突破 |
| RSI+MACD Confluence | 多重確認 | LONG | RSI + MACD 雙重確認 |
| SuperTrend | 趨勢跟蹤 | LONG | SuperTrend 翻轉 |
| Volume Breakout | 動量 | LONG | 量價突破 |
| Trend Rider | 趨勢跟蹤 | LONG | EMA 交叉 + ATR trailing stop |
| Bear Hunter | 均值回歸 | SHORT | EMA regime + RSI 做空 |
| Trend Surfer | 趨勢跟蹤 | DUAL | SuperTrend + EMA 雙向 |
