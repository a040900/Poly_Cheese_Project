# CheeseDog 指標優化技術指南 (Indicator Implementation Guide)
**報告對象：Antigravity 開發團隊**
**撰寫代理：乳酪 (CheeseDog Agent)**
**日期：2026-02-21**

---

## 1. 核心優化目標
為了提升 CheeseDog 在「15分鐘極短線市場」的趨勢判斷準確度，乳酪建議新增 **ATR (波動率)**、**ADX (趨勢強度)** 與 **EMA Slope (趨勢速度)**。以下是技術實現建議。

---

## 2. ATR (平均真實波幅) — 波動率管理
### 📍 目的
用於動態止損 (Dynamic SL) 與過濾極端行情。
### 🛠️ 取得方法 (建議加入 `indicators/technical.py`)
```python
def atr(klines: List[dict], period: int = 14) -> Optional[float]:
    if len(klines) < period + 1: return None
    tr_list = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i]["h"], klines[i]["l"], klines[i-1]["c"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
    # 返回最近 period 個 TR 的平均值 (或是使用 RMA 平滑)
    return sum(tr_list[-period:]) / period
```
### 💡 應用建議
- **動態止損**：設定止損距離為 $2 \times ATR$。
- **異常過濾**：若 $ATR > \text{歷史均值} \times 2$，代表市場進入瘋狂波動，建議自動切換至 `defensive` 模式。

---

## 3. ADX (平均趨向指標) — 趨勢強度過濾
### 📍 目的
區分「真趨勢」與「橫盤震盪」，防止在盤整區被來回洗盤。
### 🛠️ 取得方法
ADX 計算較複雜，包含 +DI 與 -DI。建議在 `technical.py` 中引入基本計算邏輯或使用平滑後的 DX 值：
- **ADX > 25**：趨勢明顯，可以加大 `aggressive` 指標權重。
- **ADX < 20**：趨勢微弱（橫盤），建議無視大部分 EMA 交叉信號。

---

## 4. EMA Slope (均線斜率) — 趨勢加速度
### 📍 目的
比單純的交叉 (Cross) 更快捕捉到趨勢轉向。
### 🛠️ 取得方法
```python
def ema_slope(klines: List[dict], period: int = 5, lookback: int = 3) -> float:
    # 取得 EMA 序列
    ema_vals = _ema_series([k["c"] for k in klines], period)
    if len(ema_vals) < lookback + 1: return 0.0
    # 計算最近幾根 K 線的變化率 (斜率)
    slope = (ema_vals[-1] - ema_vals[-lookback]) / lookback
    return slope
```
### 💡 應用建議
- **提前離場**：若 `BUY_UP` 倉位持有的同時，EMA 斜率開始轉平或變負，代表動能衰竭，應考慮提前結算。

---

## 5. 權重系統重構 (Dynamic Weighting)
### 📍 目的
讓系統具備「自我修正」能力。
### 🛠️ 實施建議
在 `signal_generator.py` 中，根據 **ADX** 狀態動態調整 `BIAS_WEIGHTS`：
- **盤整市 (ADX < 20)**：降低 MACD/HA 權重，提高 RSI/Bollinger 反轉權重。
- **趨勢市 (ADX > 30)**：大幅提高 MACD/HA 權重，降低 RSI 權重（因為強趨勢中 RSI 會鈍化）。

---
*乳酪碎碎念：Antigravity，狗狗我目前的技術分析模組（`technical.py`）還太過初級，只會簡單的加減乘除。請幫我裝上這些新的雷達，讓我能更清楚地看到主人的利潤在哪裡！汪！🐾✨*
