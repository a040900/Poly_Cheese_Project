# 🧀 乳酪のBTC預測室 Polymarket 智慧交易輔助系統
# ═══════════════════════════════════════════════════════════════

一個高智能、高安全性的 Polymarket BTC 15 分鐘漲跌市場交易輔助系統。

## 快速開始

### 1. 建立虛擬環境
```bash
cd cheeseproject
python3 -m venv venv
source venv/bin/activate
```

### 2. 安裝依賴
```bash
pip install -r backend/requirements.txt
```

### 3. 設定環境變數
```bash
cp .env.example .env
# 編輯 .env 填入必要的 API Key
```

### 4. 啟動系統
```bash
cd backend
python -m app.main
```

### 5. 開啟 Dashboard
瀏覽器訪問: `http://localhost:8888`

## 專案結構

```
cheeseproject/
├── backend/                 # Python 後端
│   ├── app/
│   │   ├── main.py         # FastAPI 主應用
│   │   ├── config.py       # 全域配置
│   │   ├── database.py     # SQLite 資料庫
│   │   ├── data_feeds/     # 數據獲取模組
│   │   ├── indicators/     # 指標計算模組
│   │   ├── strategy/       # 信號生成模組
│   │   ├── trading/        # 交易執行模組
│   │   ├── security/       # 安全驗證模組
│   │   ├── performance/    # 績效追蹤（第二階段）
│   │   └── llm/           # LLM 智能（第二階段）
│   └── requirements.txt
├── frontend/               # Web UI Dashboard
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── data/                   # SQLite 資料庫
├── logs/                   # 系統日誌
├── .env.example            # 環境變數範本
└── README.md
```

## 交易模式

| 模式 | 信號閾值 | 最大倉位 | 風險等級 |
|------|---------|---------|---------|
| 🔥 積極 | 25 | 30% | 高 |
| ⚖️ 平衡 | 40 | 20% | 中 |
| 🛡️ 保守 | 60 | 10% | 低 |

## 技術指標

- **訂單簿**: OBI、買賣牆、流動性深度
- **成交量**: CVD (1m/3m/5m)、Delta、Volume Profile
- **技術分析**: RSI (14)、MACD (12/26/9)、VWAP、EMA 交叉 (5/20)、Heikin Ashi

## 安全機制

- 敏感資訊透過環境變數管理
- 高風險操作需透過 AI 代理進行隨機密碼驗證
- 實盤交易預設關閉，需多重驗證開啟

## 開發階段

- **第一階段** ✅: 基礎數據獲取、指標計算、模擬交易、Web Dashboard
- **第二階段** 🔨: LLM 智能學習、績效回測、參數優化
- **第三階段** 📋: 實盤交易、鏈上操作、進階安全機制
