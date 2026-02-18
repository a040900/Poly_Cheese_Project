"""
🧀 CheeseDog - 全域設定檔
所有系統常數、環境變數、指標參數皆在此集中管理。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── 載入環境變數 ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# ═══════════════════════════════════════════════════════════════
# 系統設定
# ═══════════════════════════════════════════════════════════════
APP_NAME = "乳酪のBTC預測室 — Polymarket Intelligent Trading Assistant"
VERSION = "2.0.0"
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8888"))
# 反向代理子路徑（如 "/polycheese"），末尾不含 /，直接部署時留空
# VPS Tailscale Serve 部署時設為 "/polycheese"
ROOT_PATH = os.getenv("ROOT_PATH", "/polycheese").rstrip("/")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "cheesedog.db"

# 確保目錄存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# Binance 設定
# ═══════════════════════════════════════════════════════════════
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_WS = "wss://stream.binance.com/stream"
BINANCE_REST = "https://api.binance.com/api/v3"
BINANCE_SYMBOL = "BTCUSDT"

# 訂單簿設定
OB_LEVELS = 20              # 訂單簿深度層級
OB_POLL_INTERVAL = 5        # 輪詢間隔（秒）— 原為 2 秒，降低 CPU 負載

# 交易數據保留
TRADE_TTL = 600             # 保留最近 10 分鐘交易數據
TRADE_MAX_BUFFER = 2000     # 交易數據最大緩衝（降低以減少 CPU 用量）

# K 線設定
KLINE_INTERVAL = "1m"       # K 線時間間隔
KLINE_MAX = 150             # 記憶體中最大 K 線數量
KLINE_BOOT = 100            # 啟動時載入的歷史 K 線數

# ═══════════════════════════════════════════════════════════════
# Polymarket 設定
# ═══════════════════════════════════════════════════════════════
PM_GAMMA_API = "https://gamma-api.polymarket.com/events"
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PM_SERIES_SLUG = os.getenv("POLYMARKET_SERIES_SLUG", "btc-up-or-down-15m")
PM_AUTO_SELECT = os.getenv("POLYMARKET_AUTO_SELECT_LATEST", "true").lower() == "true"
PM_POLL_INTERVAL = 5        # REST API 輪詢間隔（秒）

# ═══════════════════════════════════════════════════════════════
# Chainlink / Polygon 設定
# ═══════════════════════════════════════════════════════════════
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
CHAINLINK_BTC_USD_AGGREGATOR = os.getenv(
    "CHAINLINK_BTC_USD_AGGREGATOR",
    "0xc907E116054Ad103354f2D350FD2514433D57F6f"
)
CHAINLINK_POLL_INTERVAL = 30  # Chainlink 價格輪詢間隔（秒）

# Chainlink Aggregator V3 ABI（精簡版，僅需 latestRoundData）
CHAINLINK_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ═══════════════════════════════════════════════════════════════
# 訂單簿指標參數
# ═══════════════════════════════════════════════════════════════
OBI_BAND_PCT = 1.0          # OBI 計算時中價兩側帶寬百分比
OBI_THRESH = 0.10           # OBI 信號閾值（±10%）
WALL_MULT = 5               # 掛單牆判定倍數（大於均值 N 倍）
DEPTH_BANDS = [0.1, 0.5, 1.0]  # 流動性深度計算帶寬（%）

# ═══════════════════════════════════════════════════════════════
# 成交量指標參數
# ═══════════════════════════════════════════════════════════════
CVD_WINDOWS = [60, 180, 300]    # CVD 窗口（秒）: 1m/3m/5m
DELTA_WINDOW = 60               # 短線 Delta 窗口（秒）
VP_BINS = 30                    # 成交量分佈桶數
VP_SHOW = 9                     # 成交量分佈顯示行數

# ═══════════════════════════════════════════════════════════════
# 技術分析指標參數
# ═══════════════════════════════════════════════════════════════
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 5
EMA_LONG = 20
HA_COUNT = 8                # Heikin Ashi 顯示蠟燭數

# ═══════════════════════════════════════════════════════════════
# 趨勢偏差評分權重
# ═══════════════════════════════════════════════════════════════
# 每個指標對最終綜合趨勢分數的最大貢獻度
BIAS_WEIGHTS = {
    "ema":   10,   # EMA5/EMA20 交叉 - 最強趨勢代理
    "obi":    8,   # 訂單簿失衡
    "macd":   8,   # MACD 直方圖方向
    "cvd":    7,   # CVD 5 分鐘方向
    "ha":     6,   # Heikin-Ashi 連續方向（最多 3 根蠟燭）
    "vwap":   5,   # 價格 vs VWAP
    "rsi":    5,   # RSI 超買/超賣
    "bb":     5,   # Bollinger Band %B (Phase 3: 波動率維度)
    "poc":    3,   # 價格 vs POC (成交量集中點)
    "walls":  4,   # 買牆 − 賣牆（限制 ±4）
}
# 權重總和 = 61；偏差分數 = (原始總和 / 61) * 100，夾緊在 ±100

# ═══════════════════════════════════════════════════════════════
# 交易模式定義
# ═══════════════════════════════════════════════════════════════
TRADING_MODES = {
    "aggressive": {
        "name": "積極 (Aggressive)",
        "description": "高風險高回報，使用較少指標確認，快速進場",
        "signal_threshold": 25,      # 觸發交易的最低趨勢分數
        "max_position_pct": 0.30,    # 單筆最大倉位百分比（占總資金）
        "stop_loss_pct": 0.15,       # 止損百分比
        "take_profit_pct": 0.20,     # 止盈百分比
        "indicator_weights_multiplier": {
            "ema": 1.2, "obi": 1.0, "macd": 0.8,
            "cvd": 1.2, "ha": 0.6, "vwap": 0.8,
            "rsi": 0.6, "bb": 0.6, "poc": 0.5, "walls": 1.0,
        },
    },
    "balanced": {
        "name": "平衡 (Balanced)",
        "description": "風險與回報平衡，使用全部指標綜合判斷",
        "signal_threshold": 40,
        "max_position_pct": 0.20,
        "stop_loss_pct": 0.10,
        "take_profit_pct": 0.15,
        "indicator_weights_multiplier": {
            "ema": 1.0, "obi": 1.0, "macd": 1.0,
            "cvd": 1.0, "ha": 1.0, "vwap": 1.0,
            "rsi": 1.0, "bb": 1.0, "poc": 1.0, "walls": 1.0,
        },
    },
    "conservative": {
        "name": "保守 (Conservative)",
        "description": "低風險穩健策略，需要更多指標確認方進場",
        "signal_threshold": 60,
        "max_position_pct": 0.10,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
        "indicator_weights_multiplier": {
            "ema": 0.8, "obi": 1.2, "macd": 1.2,
            "cvd": 0.8, "ha": 1.2, "vwap": 1.2,
            "rsi": 1.5, "bb": 1.3, "poc": 1.0, "walls": 1.2,
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# 模擬交易設定
# ═══════════════════════════════════════════════════════════════
SIM_INITIAL_BALANCE = float(os.getenv("SIM_INITIAL_BALANCE", "1000.0"))
SIM_FEE_PCT = 0.001         # 模擬手續費 0.1%（Phase 1 簡化值）

# Phase 3: 信號冷卻期（同方向信號在 N 秒內不重複觸發）
SIGNAL_COOLDOWN_SECONDS = 120  # 2 分鐘冷卻

# Phase 2: Polymarket 15m 市場浮動手續費（借鏡 NautilusTrader 文件）
# Buy 端手續費: 0.2% - 1.6%（從 Token 扣除）
# Sell 端手續費: 0.8% - 3.7%（從 USDC 扣除）
PM_FEE_BUY_RANGE = (0.002, 0.016)    # Buy 手續費範圍
PM_FEE_SELL_RANGE = (0.008, 0.037)   # Sell 手續費範圍
PM_FEE_BUY_DEFAULT = 0.005           # 預設 Buy 手續費 0.5%
PM_FEE_SELL_DEFAULT = 0.015          # 預設 Sell 手續費 1.5%

# Phase 2.1: 利潤過濾器 (Profit Filter)
# 開倉前先估算「扣掉手續費+價差後還有沒有賺頭」
PROFIT_FILTER_ENABLED = True                # 是否啟用利潤過濾器
PROFIT_FILTER_MAX_SPREAD_PCT = 0.02         # 最大允許 Spread 比例（2%），超過代表流動性差
PROFIT_FILTER_MIN_PROFIT_RATIO = 1.5        # 預期毛利需為來回手續費的 N 倍才放行
PROFIT_FILTER_MIN_TRADE_AMOUNT = 1.0        # 最低交易金額 (USDC)，低於此不交易

# ═══════════════════════════════════════════════════════════════
# 安全設定
# ═══════════════════════════════════════════════════════════════
PASSWORD_LENGTH = 6          # 隨機密碼長度
PASSWORD_EXPIRY = 300        # 密碼有效期（秒）

# ═══════════════════════════════════════════════════════════════
# Dashboard 設定
# ═══════════════════════════════════════════════════════════════
REFRESH_INTERVAL = 5         # 前端刷新間隔（秒）
WS_HEARTBEAT = 30           # WebSocket 心跳間隔（秒）
