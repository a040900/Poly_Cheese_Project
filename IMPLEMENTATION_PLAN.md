# 🧀 乳酪 Polymarket 智慧交易輔助系統 (CheeseDog)
# 完整實施計劃

## 專案結構

```
cheeseproject/
├── backend/                          # Python 後端
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI 應用程式入口
│   │   ├── config.py                 # 全域設定檔（常數、環境變數）
│   │   ├── database.py               # SQLite 資料庫管理
│   │   ├── models.py                 # 資料模型定義
│   │   │
│   │   ├── data_feeds/               # 數據獲取模組
│   │   │   ├── __init__.py
│   │   │   ├── binance_feed.py       # Binance WebSocket/REST 數據流
│   │   │   ├── polymarket_feed.py    # Polymarket REST + Web3 數據
│   │   │   └── chainlink_feed.py     # Chainlink 鏈上價格
│   │   │
│   │   ├── indicators/               # 指標計算模組
│   │   │   ├── __init__.py
│   │   │   ├── orderbook.py          # OBI、買賣牆、流動性深度
│   │   │   ├── volume.py             # CVD、Delta、成交量分佈
│   │   │   └── technical.py          # RSI、MACD、VWAP、EMA、Heikin Ashi
│   │   │
│   │   ├── strategy/                 # 信號生成與策略模組
│   │   │   ├── __init__.py
│   │   │   ├── signal_generator.py   # 信號生成引擎
│   │   │   ├── risk_manager.py       # 風險評估
│   │   │   └── trading_modes.py      # 交易模式定義（積極/平衡/保守）
│   │   │
│   │   ├── trading/                  # 交易執行模組
│   │   │   ├── __init__.py
│   │   │   ├── simulator.py          # 模擬交易引擎
│   │   │   └── live_trader.py        # 實盤交易（第三階段）
│   │   │
│   │   ├── performance/              # 績效追蹤模組
│   │   │   ├── __init__.py
│   │   │   ├── tracker.py            # 績效記錄與統計
│   │   │   └── backtester.py         # 回測引擎（第二階段）
│   │   │
│   │   ├── llm/                      # LLM 智能模組
│   │   │   ├── __init__.py
│   │   │   ├── mode_advisor.py       # LLM 模式建議（第二階段）
│   │   │   └── param_optimizer.py    # LLM 參數優化（第二階段）
│   │   │
│   │   ├── security/                 # 安全模組
│   │   │   ├── __init__.py
│   │   │   └── password_manager.py   # 隨機密碼驗證機制
│   │   │
│   │   └── api/                      # API 路由
│   │       ├── __init__.py
│   │       ├── routes_market.py      # 市場數據 API
│   │       ├── routes_trading.py     # 交易操作 API
│   │       ├── routes_system.py      # 系統狀態 API
│   │       └── routes_security.py    # 安全驗證 API
│   │
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/                         # Web UI 前端
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js                    # 主應用程式
│       ├── dashboard.js              # Dashboard 元件
│       ├── charts.js                 # 圖表繪製
│       └── api.js                    # API 呼叫層
│
├── data/                             # 資料目錄
│   └── cheesedog.db                  # SQLite 資料庫
│
├── logs/                             # 日誌目錄
│
├── .env.example                      # 環境變數範本
├── .gitignore
├── IMPLEMENTATION_PLAN.md
└── README.md
```

## 第一階段：基礎數據與模擬 ✅ 已完成

### 步驟 1：專案基礎設置 ✅
- [x] 建立專案目錄結構
- [x] 設定 Python 虛擬環境
- [x] 安裝相依套件
- [x] 建立配置檔案系統
- [x] 建立資料庫 Schema

### 步驟 2：數據獲取模組 ✅
- [x] Binance WebSocket 數據流（交易、訂單簿、K線）
- [x] Binance REST API（歷史 K 線啟動載入）
- [x] Polymarket REST API（市場列表、價格、流動性）
- [x] Polymarket WebSocket（UP/DOWN 合約價格）
- [x] Chainlink 鏈上價格（備用參考）

### 步驟 3：指標計算模組 ✅
- [x] 訂單簿指標 (OBI, 買賣牆, 流動性深度)
- [x] 成交量指標 (CVD, Delta, Volume Profile)
- [x] 技術指標 (RSI, MACD, VWAP, EMA, Heikin Ashi)

### 步驟 4：信號生成模組 ✅
- [x] 交易模式定義（積極/平衡/保守）
- [x] 綜合趨勢評分引擎
- [x] 風險評估機制

### 步驟 5：模擬交易模組 ✅
- [x] 虛擬資金帳戶
- [x] 模擬下單與結算
- [x] PnL 統計計算

### 步驟 6：後端 API ✅
- [x] FastAPI 應用程式架構
- [x] WebSocket 實時推播
- [x] RESTful API 端點

### 步驟 7：Web UI Dashboard ✅
- [x] 系統狀態面板
- [x] 市場數據與指標顯示
- [x] 模擬交易 PnL 曲線
- [x] 模式切換控制
- [x] 明暗主題切換

### 步驟 8：測試驗證 ✅
- [x] 獨立數據獲取驗證腳本 (`tests/test_data_feeds.py`)
- [x] Binance REST/WebSocket 連通性驗證 (18/18 通過)
- [x] Polymarket REST/WebSocket 連通性驗證
- [x] Chainlink / Polygon RPC 連通性驗證
- [x] 可在 VPS 部署後獨立執行確認連通性

---

## 第二階段：智能學習與架構優化

> 📌 **前置條件**: 第一階段已在 VPS 上穩定運行
> 📚 **參考來源**: NautilusTrader 架構設計 (github.com/nautechsystems/nautilus_trader)

### 步驟 9：手續費模型精準化 ✅
> 💡 借鏡 NautilusTrader Polymarket 整合文件：15 分鐘加密貨幣市場有特殊手續費結構

- [x] 更新模擬器手續費為浮動費率模型
  - Buy 端手續費：0.2% - 1.6%（從 Token 扣除）
  - Sell 端手續費：0.8% - 3.7%（從 USDC 扣除）
- [x] 手續費計算邏輯獨立為 `strategy/fees.py` 模組
- [x] 模擬器中正確區分 Buy/Sell 的手續費差異
- [ ] 回測結果加入手續費影響分析（等回測引擎完成後）

### 步驟 10：元件狀態機
> 💡 借鏡 NautilusTrader `ComponentState` 設計：細緻的元件生命週期管理

- [ ] 建立統一的 `ComponentState` 枚舉
  - `INITIALIZING → READY → RUNNING → STOPPED`
  - 額外狀態：`DEGRADED`（降級，如延遲過高）、`FAULTED`（故障）
- [ ] 所有 DataFeed 元件套用狀態機
- [ ] Dashboard 顯示元件健康度而非單純的連線/斷線

### 步驟 11：事件驅動架構（MessageBus）
> 💡 借鏡 NautilusTrader `MessageBus` Pub/Sub 模式

- [ ] 建立輕量級 `MessageBus` 事件系統
  - 支援 Publish/Subscribe 模式
  - 支援 `on_trade_tick`、`on_bar`、`on_orderbook` 等事件
- [ ] 修改 Data Feeds 為事件發布者
- [ ] 信號生成改為事件驅動（收到新數據立即計算，而非定時 10 秒輪詢）
- [ ] 提升信號反應速度至毫秒級

### 步驟 12：績效追蹤與回測引擎
- [ ] `performance/tracker.py` — 即時績效追蹤
  - 勝率、最大回撤 (Max Drawdown)、夏普比率 (Sharpe Ratio)
  - 每日/每週/每月統計
  - 各交易模式的獨立績效比較
- [ ] `performance/backtester.py` — 歷史回測引擎
  - 載入歷史 K 線和市場快照
  - 重播歷史事件模擬策略表現
  - 產出回測報告（含手續費、滑點）

### 步驟 13：LLM 智能整合（宿主 AI 代理模式）
> 📌 LLM 功能透過宿主 AI 代理（OpenClaw/Antigravity）處理，不設獨立 API Key

- [ ] `llm/prompt_builder.py` — 結構化提示生成器
  - 將當前市場狀態、指標數據、績效統計格式化為結構化 prompt
  - 標準化的數據摘要供 AI 代理快速理解
- [ ] `/api/llm/context` — 暴露結構化數據端點
  - AI 代理可透過 API 讀取完整的系統上下文
- [ ] `/api/llm/advice` — 接收 AI 建議端點
  - AI 代理分析後回傳模式建議、參數調整建議
  - 建議存入 `llm_advices` 資料表
- [ ] `llm/param_optimizer.py` — 參數優化建議
  - 基於歷史績效數據，請求 AI 代理建議最佳指標權重
  - A/B 測試機制驗證優化效果

### 步驟 14：Dashboard 增強
- [ ] 績效圖表（回撤曲線、勝率趨勢）
- [ ] 指標貢獻度視覺化（哪些指標最準確）
- [ ] AI 建議歷史記錄面板
- [ ] 回測結果展示面板

---

## 第三階段：實戰準備

> 📌 **前置條件**: 第二階段回測驗證策略有效性
> ⚠️ **重要**: 此階段涉及真實資金操作，需嚴格測試

### 步驟 15：策略介面統一 ✅
> 💡 借鏡 NautilusTrader 核心理念：回測和實盤使用相同的策略代碼

- [x] 抽象出統一的 `TradingEngine` 介面 (`trading/engine.py`)
  - `execute_trade(signal, amount)` → 統一交易執行介面
  - `auto_settle_expired(btc_start, btc_end)` → 統一結算介面
  - `get_balance()` → 統一餘額查詢介面
  - `get_open_trades()` → 統一持倉查詢
  - `emergency_stop(reason)` → 緊急停止
- [x] `SimulationEngine` 實作 `TradingEngine` 介面（已重構）
- [x] `LiveTradingEngine` 實作相同介面（骨架已建立）
- [x] 切換模擬/實盤只需更換引擎實例，策略邏輯零修改

### 步驟 16：Polymarket CLOB API 實盤整合 ✅
> ⚠️ 注意 Quote Quantity vs Base Quantity 區別（借鏡 NautilusTrader 文件警告）

- [x] `trading/live_trader.py` — 實盤交易引擎
  - Polymarket CLOB API 認證（Private Key → L1 Auth → L2 API Creds）
  - 使用 `py-clob-client` 官方 SDK
  - **Market BUY = Quote Quantity (USDC 面值)**
  - **Market SELL = Base Quantity (Token 數量)**
  - FOK (Fill or Kill) 訂單確保完全成交
- [x] 多層安全防護
  - `PM_LIVE_ENABLED` 環境變數開關（預設 false）
  - 單筆金額硬上限 (預設 $10)
  - 累計金額硬上限 (預設 $100)
  - 緊急鎖定機制 (emergency_stop + cancel_all)
  - RiskManager 熔斷器整合
  - 利潤過濾器整合
- [x] 訂單生命週期追蹤
  - 記錄 order_id、簽名耗時、提交耗時
  - 存入 DB（trade_type="live" 區分實盤）
- [ ] 倉位核對 (Reconciliation)
  - 定期核對鏈上倉位與系統記錄
  - 偵測並修正不一致

### 步驟 17：進階風險管理 🟡 部分完成
> 💡 借鏡 NautilusTrader `RiskEngine` 獨立風險引擎設計

- [x] 獨立 `RiskManager` 模組 (`trading/risk_manager.py`)
  - 交易前驗證（餘額、持倉上限、頻率限制）
  - 單日最大虧損限制 → 自動停止交易
  - 連續虧損熔斷機制
  - Kelly Criterion 倉位管理
- [ ] 緊急停止功能
  - 一鍵取消所有掛單（待 Step 16 實盤 API）
  - 停止接收新信號
  - 記錄緊急停止原因

### 步驟 18：安全機制強化
- [ ] 多重驗證切換實盤
  - 隨機密碼驗證（已完成密碼管理器）
  - 交易金額上限確認
  - 首次實盤強制小額測試
- [ ] 私鑰安全管理
  - 環境變數 + 加密儲存
  - 定期提醒更換 API Key

### 步驟 19：監控與告警
- [ ] WebSocket 推播重要事件到 Dashboard
- [ ] 連線中斷自動告警
- [ ] 異常交易偵測（價格偏離、滑點過大）

## 第四階段：混合智能與協作架構 (Hybrid Intelligence)

> 📌 **核心理念**: 將純自動化升級為「AI 導航 + 人類監督」的雙層決策系統，透過權限管控確保資金安全。

### 步驟 20：基礎設施與權限守門員 ✅ 已完成
- [x] 更新 `config.py`，加入 Phase 4 設定 (Navigator, AuthMode, ProposalQueue)
- [x] 建立 `supervisor` 模組處理控制平面權限
- [x] 實作 `proposal_queue.py` (提案狀態機、生命週期、緊急安全閥)
- [x] 實作 `authorization.py` (權限攔截，路由至 AUTO/HITL/MONITOR)
- [x] 整合 `main.py` 與 `AIEngine`，讓所有 AI 建議都先經過守門員過濾

### 步驟 21：Dashboard 唯讀監控面板 (Web UI) ✅ 已完成
> 💡 控制平面由 Telegram 負責，Dashboard 專注於資料平面（唯讀顯示）
- [x] 新增「🛡️ 監控台」Tab 到 Dashboard
- [x] Supervisor 狀態卡片列（Navigator / AuthMode / Telegram / 待審提案）
- [x] 六項統計看板（已建立/核准/拒絕/過期/自動放行/阻擋）
- [x] 提案歷史表格（含狀態標籤色彩、優先級標記、來源）
- [x] Telegram Bot 連線狀態指示燈（運行中/已啟用/未安裝/未啟用）
- [x] 每 30 秒自動刷新 + 手動刷新按鈕
- [x] 響應式設計支援手機瀏覽

### 步驟 22：Telegram 遠端審核 (HITL 增強) ✅ 已完成
> 🤖 包含 Skill 指引，AI Agent 可自行完成配置
- [x] 實作 `notifications/telegram_bot.py` (完整的推播 + 指令 + Inline Button)
- [x] 整合 MessageBus 事件驅動推播 (proposal_created / resolved / auto_executed)
- [x] 提供 8 個 TG 指令 (/status, /proposals, /mode, /setnavigator, /setauth 等)
- [x] Inline Button 一鍵核准/拒絕 + 緊急安全閥強提醒
- [x] 動態配置 API (`POST /api/telegram/configure`) — 無需重啟
- [x] 建立 Skill 檔案 (`.agents/skills/cheesedog-telegram-setup/SKILL.md`)
- [x] 整合到 `main.py` 生命週期（自動啟動 / 安全關閉）

### 步驟 23：混合決策引擎 (Hybrid Decision Engine) ✅ 已完成
- [x] 將 Polymarket 價格乖離轉化為量化的 **情緒因子 (Sentiment Factor)**
- [x] 修改 `signal_generator.py`，將情緒因子作為乘數，與技術指標 (TA) 得分融合
- [x] 新增漸進式情緒敏感度 (Sentiment Sensitivity)
   - `ultra_aggressive`: 不受情緒干擾
   - `conservative`: 嚴格攔截 FOMO / 逆勢恐慌放大
- [x] 前端 UI 大改版：新增情緒狀態條、漸變色橫條、以及調整前後分數差異顯示

---

## 架構參考來源

| 來源 | 借鏡內容 | 適用階段 |
|------|---------|---------|
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | 元件狀態機、MessageBus、策略介面統一 | 第二、三階段 |
| NautilusTrader Polymarket 整合 | 15m 市場手續費結構、Quote/Base Quantity 區別、訂單生命週期 | 第二、三階段 |
| NautilusTrader RiskEngine | 獨立風險引擎、交易前驗證 | 第三階段 |
| NautilusTrader Reconciliation | 倉位核對機制 | 第三階段 |

## 風險提醒

> ⚠️ **Polymarket 15 分鐘加密貨幣市場特殊注意事項**
>
> 1. **手續費不為零** — 15m 市場是 Polymarket 少數收費的市場類型
>    - Buy: 0.2% - 1.6% | Sell: 0.8% - 3.7%
> 2. **Market BUY 用 USDC 面值 (Quote)** — 不是 Token 數量
> 3. **訂單簽名延遲** — Python 端簽名約需 1 秒
> 4. **市場結果判定** — 依賴 Polymarket 官方結算，非自行判斷
