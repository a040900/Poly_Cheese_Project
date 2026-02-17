# 🧀 CheeseDog 專案進度記錄

**最後更新**: 2026-02-17 23:31 (台灣時間)  
**專案版本**: 2.0.0  
**當前階段**: Phase 2 - 智能學習與架構優化  

---

## 📍 當前狀態

### ✅ Phase 1 已完成 (v1.0.0)
- **數據獲取**: Binance WebSocket/REST, Polymarket WebSocket/REST, Chainlink 鏈上價格
- **指標系統**: 9 種技術指標 (EMA, OBI, MACD, CVD, HA, VWAP, RSI, POC, Walls)
- **信號引擎**: 綜合趨勢評分系統，支援 3 種交易模式 (積極/平衡/保守)
- **模擬交易**: 虛擬帳戶、自動結算、PnL 追蹤
- **Web Dashboard**: 實時數據推播、明暗主題、交易記錄顯示
- **VPS 部署**: 透過 Tailscale 反向代理成功部署 (`/polycheese` → port 8888)

### 🚀 Phase 2 進行中 (v2.0.0)

#### ✅ 已完成
1. **步驟 9: 手續費模型精準化** (2026-02-17)
   - 創建 `backend/app/strategy/fees.py` 獨立手續費模組
   - 實作 Polymarket 15m 市場浮動費率 (借鏡 NautilusTrader)
     - Buy 端: 0.2% - 1.6% (從 Token 扣除)
     - Sell 端: 0.8% - 3.7% (從 USDC 扣除)
   - 費率根據合約價格動態計算 (越極端價格費率越高)
   - 模擬器已整合新手續費模型

2. **CPU 效能優化** (2026-02-17)
   - 訂單簿輪詢間隔: 2 秒 → 5 秒
   - 交易數據緩衝: 5000 筆 → 2000 筆
   - 預期 CPU 使用率從 50% 降至 30% 以下

3. **UI Bug 修復**
   - 反向代理路徑問題 (CSS/JS 相對路徑)
   - WebSocket/API 自動偵測 sub-path
   - BTC 卡片「連線中...」卡住問題 → 顯示「Binance 即時」
   - 交易記錄列表渲染 (未平倉/已結算，含盈虧和狀態)

#### 🔜 待完成 (Phase 2 剩餘步驟)
- **步驟 10**: 元件狀態機 (INITIALIZING → READY → RUNNING → STOPPED → DEGRADED/FAULTED)
- **步驟 11**: 事件驅動 MessageBus ⭐ (優先，取代 10 秒輪詢，降低 CPU)
- **步驟 12**: 績效追蹤 + 回測引擎
- **步驟 13**: LLM 智能整合 (宿主 AI 代理模式)
- **步驟 14**: Dashboard 增強 (績效圖表、指標貢獻度視覺化)

---

## 🗂️ 專案結構概覽

```
cheeseproject/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 主程式
│   │   ├── config.py            # 全域設定 (已調整輪詢間隔)
│   │   ├── database.py          # SQLite 資料庫
│   │   ├── data_feeds/          # Binance, Polymarket, Chainlink
│   │   ├── indicators/          # 9 種技術指標
│   │   ├── strategy/
│   │   │   ├── signal_generator.py  # 信號生成引擎
│   │   │   └── fees.py          # ✨ Phase 2 新增：手續費模組
│   │   ├── trading/
│   │   │   └── simulator.py    # 模擬交易引擎 (已整合新手續費)
│   │   ├── security/
│   │   │   └── password_manager.py  # 隨機密碼驗證
│   │   └── api/                # API 路由
│   ├── tests/
│   │   ├── test_data_feeds.py  # 數據源驗證腳本
│   │   └── check_status.py     # 系統狀態檢查腳本
│   └── requirements.txt
├── frontend/
│   ├── index.html              # Dashboard UI
│   ├── css/style.css           # 雙主題樣式
│   └── js/app.js               # WebSocket + 渲染邏輯 (已修復路徑問題)
├── data/
│   └── cheesedog.db            # SQLite 數據庫
├── .env.example
├── IMPLEMENTATION_PLAN.md      # 完整實施計畫 (Phase 1-3)
└── README.md
```

---

## 🔧 技術架構要點

### 數據流
1. **WebSocket 實時推播** (每 5 秒)
   - Binance 交易流 + K 線
   - Polymarket UP/DOWN 合約價格
   - 訂單簿輪詢 (REST, 每 5 秒)

2. **信號生成** (每 10 秒輪詢 — Phase 2 步驟 11 將改為事件驅動)
   - 計算 9 種指標
   - 綜合趨勢評分 (-100 ~ +100)
   - 根據模式閾值生成信號 (BUY_UP / SELL_DOWN / NEUTRAL)

3. **模擬交易**
   - 開倉: Buy 端手續費 (0.2%-1.6%)
   - 結算: Sell 端手續費 (0.8%-3.7%)
   - 15 分鐘自動結算

### 部署環境
- **VPS**: Tailscale 反向代理
- **路徑映射**: `/polycheese` → `localhost:8888`
- **前端**: 相對路徑 + 動態 base path 偵測
- **後端**: FastAPI + Uvicorn

---

## 📊 效能指標

| 項目 | Phase 1 | Phase 2 (優化後) |
|------|---------|-----------------|
| CPU 使用率 | ~50% | 預期 <30% |
| 訂單簿輪詢 | 2 秒 | 5 秒 |
| 交易緩衝 | 5000 筆 | 2000 筆 |
| 信號延遲 | 10 秒 (輪詢) | 計畫改為事件驅動 (ms 級) |

---

## 🛠️ 關鍵設定檔

### `.env` 環境變數 (重要)
```bash
# Polymarket 市場選擇
POLYMARKET_SERIES_SLUG=btc-up-or-down-15m
POLYMARKET_AUTO_SELECT_LATEST=true

# Polygon RPC (Chainlink 數據源)
POLYGON_RPC_URL=https://polygon-rpc.com

# 模擬帳戶初始資金
SIM_INITIAL_BALANCE=1000.0
```

### 手續費設定 (`config.py`)
```python
# Phase 2 浮動手續費
PM_FEE_BUY_RANGE = (0.002, 0.016)    # Buy: 0.2%-1.6%
PM_FEE_SELL_RANGE = (0.008, 0.037)   # Sell: 0.8%-3.7%
PM_FEE_BUY_DEFAULT = 0.005           # 預設 Buy: 0.5%
PM_FEE_SELL_DEFAULT = 0.015          # 預設 Sell: 1.5%
```

---

## 🐛 已知問題與解決

### ✅ 已解決
1. **反向代理樣式失效**
   - 問題: `/polycheese` 下 `/static/css/style.css` 404
   - 解決: 改為相對路徑 `static/css/style.css` + 動態 WebSocket URL

2. **BTC 卡片「連線中...」卡住**
   - 問題: `val-btc-change` 元素未更新
   - 解決: `renderMarket()` 加入更新邏輯

3. **交易記錄顯示「暫無交易記錄」**
   - 問題: 後端未推播 `recent_trades`
   - 解決: 新增 `get_recent_trades()` + 前端 `renderRecentTrades()`

### 🔍 待觀察
- CPU 使用率是否降至 <30%
- 手續費模型對 PnL 的影響

---

## 📋 下次繼續的起點

### 建議優先級
1. **步驟 11: MessageBus 事件驅動** ⭐⭐⭐
   - 取代 10 秒信號輪詢
   - 即時反應市場變化
   - 再次降低 CPU 使用率
   - 為回測引擎打基礎

2. **步驟 12: 回測引擎**
   - 驗證策略有效性
   - 手續費影響分析
   - 參數優化

3. **步驟 13-14: LLM 整合 + Dashboard 增強**
   - 較低優先級
   - 可在策略穩定後進行

### 快速啟動指令
```bash
# VPS 更新代碼
cd cheeseproject
git pull

# 本機開發
cd backend
python -m app.main

# 測試連通性
python tests/test_data_feeds.py

# 檢查系統狀態
python tests/check_status.py
```

---

## 🔗 重要參考資料

1. **NautilusTrader 架構**
   - Polymarket 整合文件: 15m 市場手續費結構
   - ComponentState 狀態機設計
   - MessageBus Pub/Sub 模式
   - 策略介面統一 (回測/實盤零修改)

2. **Repository**
   - GitHub: `a040900/Poly_Cheese_Project`
   - 分支: `main`

---

## 💬 對話摘要 (本次會話)

### 主要成就
1. 部署成功 → UI 樣式修復 → 交易記錄顯示修復
2. 正式啟動 Phase 2
3. 手續費精準化完成 (步驟 9)
4. CPU 優化調整

### 技術決策
- **手續費模型**: 採用動態計算，根據合約價格映射費率 (二次函數)
- **CPU 優化**: 不激進縮減功能，而是調整輪詢頻率平衡
- **下一步**: MessageBus 事件驅動優先於其他 Phase 2 步驟

### 使用者反饋
- VPS 運行穩定，但 CPU 50% 偏高 → 已優化
- UI 小問題 (連線中卡住) → 已修復

---

**下次對話時，請參考此文件快速回到進度！**
