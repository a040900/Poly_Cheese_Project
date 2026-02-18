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
VERSION = "3.2.0"
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
# 趨勢偏差評分權重（Phase 3 P1: 真實數據校準 2026-02-18）
# ═══════════════════════════════════════════════════════════════
# 每個指標對最終綜合趨勢分數的最大貢獻度
# 校準方法: Random Search (200) + Hill Climbing (100)
# 校準數據: Binance BTCUSDT 1m K 線 16h (931 筆真實快照)
# 校準結果: Composite=0.725 | Sharpe=103.18 | 勝率=70.6% | 17 筆交易
BIAS_WEIGHTS = {
    "ema":    6,   # EMA 交叉（連續函數）
    "obi":    4,   # 訂單簿失衡
    "macd":   3,   # MACD Histogram（幅度化）
    "cvd":    5,   # CVD 5 分鐘方向
    "ha":    12,   # Heikin-Ashi 連續方向 ★ 校準 MVP
    "vwap":   7,   # 價格 vs VWAP
    "rsi":    5,   # RSI 超買/超賣（極端加強）
    "bb":     8,   # Bollinger Band %B（波動率維度）★ 校準重要
    "poc":    3,   # 價格 vs POC（成交量集中點）
    "walls":  1,   # 買牆 − 賣牆
}
# 權重總和 = 54；偏差分數 = (原始總和 / 54) * 100，夾緊在 ±100

# ═══════════════════════════════════════════════════════════════
# 交易模式定義（Phase 3 P1: 5 級連續光譜）
# ═══════════════════════════════════════════════════════════════
# 等級排列: defensive < conservative < balanced < aggressive < ultra_aggressive
# Agent 可根據市場狀態（MARKET_REGIME）自動選擇最適合的模式
TRADING_MODES = {
    "ultra_aggressive": {
        "name": "超激進 (Ultra Aggressive)",
        "description": "極短線趨勢追蹤，高頻交易，需要極強趨勢才有利",
        "signal_threshold": 15,      # 極低門檻，幾乎見信號就進
        "max_position_pct": 0.40,    # 單筆最大倉位 40%
        "stop_loss_pct": 0.20,       # 寬止損
        "take_profit_pct": 0.25,     # 高止盈
        "indicator_weights_multiplier": {
            "ema": 1.5, "obi": 0.8, "macd": 0.6,
            "cvd": 1.5, "ha": 0.4, "vwap": 0.5,
            "rsi": 0.3, "bb": 0.4, "poc": 0.3, "walls": 1.2,
        },
        "regime_affinity": ["strong_trend"],  # 適合的市場狀態
    },
    "aggressive": {
        "name": "積極 (Aggressive)",
        "description": "高風險高回報，快速進場，適合趨勢市",
        "signal_threshold": 25,
        "max_position_pct": 0.30,
        "stop_loss_pct": 0.15,
        "take_profit_pct": 0.20,
        "indicator_weights_multiplier": {
            "ema": 1.2, "obi": 0.9, "macd": 0.8,
            "cvd": 1.2, "ha": 0.7, "vwap": 0.8,
            "rsi": 0.5, "bb": 0.6, "poc": 0.5, "walls": 1.0,
        },
        "regime_affinity": ["strong_trend", "mild_trend"],
    },
    "balanced": {
        "name": "平衡 (Balanced)",
        "description": "風險與回報平衡，全指標綜合判斷，適合多數行情",
        "signal_threshold": 40,
        "max_position_pct": 0.20,
        "stop_loss_pct": 0.10,
        "take_profit_pct": 0.15,
        "indicator_weights_multiplier": {
            "ema": 1.0, "obi": 1.0, "macd": 1.0,
            "cvd": 1.0, "ha": 1.0, "vwap": 1.0,
            "rsi": 1.0, "bb": 1.0, "poc": 1.0, "walls": 1.0,
        },
        "regime_affinity": ["mild_trend", "ranging"],
    },
    "conservative": {
        "name": "保守 (Conservative)",
        "description": "低風險穩健策略，需更多確認，適合震盪市",
        "signal_threshold": 55,
        "max_position_pct": 0.12,
        "stop_loss_pct": 0.07,
        "take_profit_pct": 0.12,
        "indicator_weights_multiplier": {
            "ema": 0.8, "obi": 1.2, "macd": 1.2,
            "cvd": 0.8, "ha": 1.2, "vwap": 1.2,
            "rsi": 1.4, "bb": 1.3, "poc": 1.0, "walls": 1.2,
        },
        "regime_affinity": ["ranging", "choppy"],
    },
    "defensive": {
        "name": "防禦 (Defensive)",
        "description": "極保守策略，僅在極強信號進場，適合高波動/不確定市場",
        "signal_threshold": 70,
        "max_position_pct": 0.08,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.08,
        "indicator_weights_multiplier": {
            "ema": 0.6, "obi": 1.5, "macd": 1.5,
            "cvd": 0.6, "ha": 1.5, "vwap": 1.5,
            "rsi": 1.8, "bb": 1.6, "poc": 1.2, "walls": 1.5,
        },
        "regime_affinity": ["choppy", "crash"],
    },
}

# ═══════════════════════════════════════════════════════════════
# 市場狀態自動偵測（Market Regime Detection）
# ═══════════════════════════════════════════════════════════════
# Agent 使用這些參數判斷當前市場狀態，自動選擇最適合的交易模式
MARKET_REGIME_CONFIG = {
    # 波動率閾值（基於 ATR 或 BB 寬度的百分比）
    "volatility_low": 0.3,     # < 0.3% → 低波動（盤整）
    "volatility_mid": 0.8,     # 0.3~0.8% → 中波動（正常）
    "volatility_high": 1.5,    # 0.8~1.5% → 高波動（趨勢）
    # > 1.5% → 極高波動（崩盤/暴漲）

    # 趨勢強度閾值（基於 ADX 或 EMA 斜率）
    "trend_weak": 15,          # ADX < 15 → 無趨勢
    "trend_mild": 25,          # 15~25 → 溫和趨勢
    "trend_strong": 40,        # > 25 → 強趨勢

    # 市場狀態 → 推薦模式映射
    "regime_mode_map": {
        "strong_trend": "aggressive",
        "mild_trend":   "balanced",
        "ranging":      "conservative",
        "choppy":       "defensive",
        "crash":        "defensive",
    },

    # 自動切換冷卻期（秒）— 避免頻繁切換模式
    "mode_switch_cooldown": 300,  # 5 分鐘
}

# ═══════════════════════════════════════════════════════════════
# Phase 3 P2: 風險管理設定 (Risk Management)
# ═══════════════════════════════════════════════════════════════
RISK_MANAGEMENT = {
    # ── Kelly Criterion 設定 ──────────────────────────────────
    "kelly_fraction": 0.5,         # Half-Kelly（更保守，降低破產風險）
    # Full-Kelly = 1.0（理論最優但波動極大）
    # Quarter-Kelly = 0.25（極保守）

    # ── 倉位比例限制 ──────────────────────────────────────────
    "min_position_pct": 0.02,      # 最小倉位 2%（避免交易太小沒意義）
    "max_position_pct": 0.35,      # 最大倉位 35%（全局硬上限）

    # ── Circuit Breaker 1: 日虧損上限 ─────────────────────────
    "daily_loss_limit_enabled": True,
    "daily_loss_limit_pct": 10.0,  # 日虧損超過 10% 觸發熔斷

    # ── Circuit Breaker 2: 連敗上限 ───────────────────────────
    "consecutive_loss_limit_enabled": True,
    "consecutive_loss_limit": 5,   # 連續虧損 5 筆觸發熔斷

    # ── Circuit Breaker 3: 最大回撤 ───────────────────────────
    "max_drawdown_limit_enabled": True,
    "max_drawdown_limit_pct": 20.0,  # 回撤超過 20% 觸發熔斷

    # ── Circuit Breaker 4: 日交易次數上限 ─────────────────────
    "daily_trade_limit_enabled": True,
    "daily_trade_limit": 30,       # 每日最多 30 筆交易

    # ── 熔斷冷卻時間 ──────────────────────────────────────────
    "circuit_breaker_cooldown": 1800,  # 熔斷後冷卻 30 分鐘
}

# ═══════════════════════════════════════════════════════════════
# 模擬交易設定
# ═══════════════════════════════════════════════════════════════
SIM_INITIAL_BALANCE = float(os.getenv("SIM_INITIAL_BALANCE", "1000.0"))

# ── Polygon / Chainlink (Phase 2 & 3) ─────────────────────────
# 公用節點可能不穩定，建議換成 Alchemy/Infura
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon.drpc.org")
CHAINLINK_BTC_USD_AGGREGATOR = "0xc907E116054Ad103354f2D350FD2514433D57F6f"
CHAINLINK_POLL_INTERVAL = 30  # 秒

SIM_FEE_PCT = 0.001         # 模擬手續費 0.1%（Phase 1 簡化值）

# Phase 3: 信號冷卻期（同方向信號在 N 秒內不重複觸發）
SIGNAL_COOLDOWN_SECONDS = 120  # 2 分鐘冷卻

# Phase 3 Step 16: 實盤交易開關與安全設定
PM_LIVE_ENABLED = os.getenv("PM_LIVE_ENABLED", "false").lower() == "true"
PM_LIVE_MAX_SINGLE_TRADE = float(os.getenv("PM_LIVE_MAX_SINGLE_TRADE", "10.0"))
PM_LIVE_MAX_TOTAL_TRADED = float(os.getenv("PM_LIVE_MAX_TOTAL_TRADED", "100.0"))

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
PROFIT_FILTER_MAX_SPREAD_PCT = 0.05         # 最大允許 Spread 放寬至 5%（校準後調整）
PROFIT_FILTER_MIN_PROFIT_RATIO = 1.1        # 預期毛利需為來回手續費的 1.1 倍即可（校準後調整）
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
