"""
🧀 乳酪のBTC預測室 — 統一交易引擎介面 (Step 15)
=================================================

定義 TradingEngine 抽象基類，讓模擬引擎 (SimulationEngine) 和
實盤引擎 (LiveTradingEngine) 共用相同介面。

核心理念（借鏡 NautilusTrader）：
    - 策略邏輯不關心「交易在哪裡執行」
    - 切換模擬 ↔ 實盤只需更換引擎實例
    - 所有引擎共用統一的 Trade 資料結構
"""

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any

logger = logging.getLogger("cheesedog.trading.engine")


# ═══════════════════════════════════════════════════════════════
# 共用資料結構
# ═══════════════════════════════════════════════════════════════

class TradeStatus(str, Enum):
    """交易狀態"""
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class EngineType(str, Enum):
    """引擎類型"""
    SIMULATION = "simulation"
    LIVE = "live"


@dataclass
class Trade:
    """
    統一交易資料結構

    不論模擬或實盤，所有交易都以此結構表示。
    """
    trade_id: int
    direction: str              # "BUY_UP" | "SELL_DOWN"
    entry_price: float          # 合約價格 (Polymarket)
    quantity: float             # USDC 金額
    signal_score: float         # 觸發時的信號分數
    trading_mode: str           # 交易模式 (aggressive / balanced / ...)
    market_title: str = "BTC 15m UP/DOWN"
    contract_price: float = 0.5 # Polymarket 合約價原始價格
    entry_time: float = 0.0     # 開倉時間 (Unix timestamp)
    exit_price: Optional[float] = None
    exit_time: Optional[float] = None
    pnl: float = 0.0
    fee: float = 0.0
    status: TradeStatus = TradeStatus.OPEN

    # 實盤專用欄位
    order_id: Optional[str] = None      # Polymarket 訂單 ID
    tx_hash: Optional[str] = None       # 鏈上交易 Hash
    token_amount: Optional[float] = None  # 實際取得的 Token 數量

    def __post_init__(self):
        if self.entry_time == 0.0:
            self.entry_time = time.time()

    @property
    def is_open(self) -> bool:
        return self.status == TradeStatus.OPEN

    @property
    def elapsed_seconds(self) -> float:
        """開倉至今的秒數"""
        return time.time() - self.entry_time

    @property
    def elapsed_minutes(self) -> float:
        return self.elapsed_seconds / 60

    def to_dict(self) -> dict:
        """轉換為字典（供 API / WebSocket 使用）"""
        return {
            "trade_id": self.trade_id,
            "direction": self.direction,
            "entry_price": round(self.entry_price, 4),
            "quantity": round(self.quantity, 2),
            "pnl": round(self.pnl, 2),
            "fee": round(self.fee, 4),
            "status": self.status.value,
            "signal_score": round(self.signal_score, 2),
            "trading_mode": self.trading_mode,
            "market_title": self.market_title,
            "contract_price": round(self.contract_price, 4),
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "exit_price": round(self.exit_price, 4) if self.exit_price else None,
            "elapsed_min": round(self.elapsed_minutes, 1),
            "order_id": self.order_id,
        }


# ═══════════════════════════════════════════════════════════════
# 抽象基類：TradingEngine
# ═══════════════════════════════════════════════════════════════

class TradingEngine(ABC):
    """
    交易引擎抽象基類

    所有交易引擎（模擬 / 實盤）都必須實作此介面。
    策略邏輯 (main.py, signal_generator) 只依賴此介面，
    不直接依賴具體的引擎實作。

    Usage:
        engine: TradingEngine = SimulationEngine()   # 模擬模式
        engine: TradingEngine = LiveTradingEngine()  # 實盤模式
        engine.start()
        trade = engine.execute_trade(signal, pm_state=pm)
        engine.auto_settle_expired(btc_start, btc_end)
    """

    @property
    @abstractmethod
    def engine_type(self) -> EngineType:
        """引擎類型（模擬 / 實盤）"""
        ...

    # ── 生命週期 ──────────────────────────────────────────────

    @abstractmethod
    def start(self) -> None:
        """啟動引擎"""
        ...

    @abstractmethod
    def stop(self) -> None:
        """停止引擎"""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """引擎是否正在運行"""
        ...

    @abstractmethod
    def reset(self, new_balance: Optional[float] = None) -> None:
        """重置引擎（清空持倉、還原餘額）"""
        ...

    # ── 交易執行 ──────────────────────────────────────────────

    @abstractmethod
    def execute_trade(
        self,
        signal: dict,
        amount: Optional[float] = None,
        pm_state: Optional[Any] = None,
    ) -> Optional[Trade]:
        """
        執行交易

        Args:
            signal: 交易信號（含 direction, score, confidence, mode）
            amount: 交易金額 (None = 依據風險管理自動計算)
            pm_state: Polymarket 市場狀態

        Returns:
            Trade 物件 (成功) 或 None (被攔截/失敗)
        """
        ...

    @abstractmethod
    def auto_settle_expired(
        self, btc_price_start: float, btc_price_end: float
    ) -> None:
        """
        自動結算到期交易

        Args:
            btc_price_start: 15 分鐘開始的 BTC 價格
            btc_price_end: 15 分鐘結束的 BTC 價格
        """
        ...

    # ── 查詢 ──────────────────────────────────────────────────

    @abstractmethod
    def get_balance(self) -> float:
        """取得當前餘額"""
        ...

    @abstractmethod
    def get_open_trades(self) -> List[Trade]:
        """取得所有未平倉交易"""
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        """取得交易統計摘要"""
        ...

    @abstractmethod
    def get_recent_trades(self, limit: int = 10) -> List[dict]:
        """取得最近交易記錄（含未平倉）"""
        ...

    @abstractmethod
    def get_pnl_curve(self) -> List[dict]:
        """取得 PnL 曲線數據"""
        ...

    # ── 緊急控制（Phase 3 Step 17）────────────────────────────

    def emergency_stop(self, reason: str = "手動觸發") -> dict:
        """
        緊急停止：停止引擎 + 記錄原因

        子類可覆寫以加入額外行為（如取消所有掛單）。
        """
        self.stop()
        logger.warning(f"🚨 緊急停止！原因: {reason} | 引擎: {self.engine_type.value}")
        return {
            "action": "emergency_stop",
            "engine": self.engine_type.value,
            "reason": reason,
            "timestamp": time.time(),
        }
