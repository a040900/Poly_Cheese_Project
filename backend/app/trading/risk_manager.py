"""
🧀 乳酪のBTC預測室 — 風險管理模組 (Phase 3 P2)
=====================================================

實現三層風險管理機制：
    1. Kelly Criterion — 最優倉位比例計算
    2. Circuit Breakers — 熔斷保護機制
    3. Dynamic Position Sizing — 動態倉位調整

設計原則：
    - 所有功能皆可獨立啟用/停用（透過 config.py）
    - 不修改現有交易邏輯，僅作為「建議層」嵌入
    - 提供詳細的決策日誌，供 AI Agent 分析
"""

import time
import math
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

from app import config

logger = logging.getLogger("cheesedog.risk_manager")


# ═══════════════════════════════════════════════════════════════
# 資料結構
# ═══════════════════════════════════════════════════════════════

@dataclass
class PositionSizeResult:
    """倉位大小計算結果"""
    recommended_amount: float       # 建議交易金額
    kelly_fraction: float           # Kelly 公式建議的最大倉位比例
    position_pct: float             # 推薦倉位 % (佔總資金)
    confidence_multiplier: float    # 信心度調整因子
    volatility_multiplier: float    # 波動率調整因子
    circuit_breaker_active: bool    # 是否觸發熔斷
    circuit_breaker_reason: str     # 熔斷原因
    risk_score: float               # 綜合風險評分 (0~100)
    details: Dict                   # 詳細計算過程


@dataclass
class CircuitBreakerState:
    """熔斷器狀態"""
    triggered: bool = False
    reason: str = ""
    triggered_at: float = 0.0
    cooldown_until: float = 0.0

    # 統計追蹤
    daily_pnl: float = 0.0
    daily_trade_count: int = 0
    consecutive_losses: int = 0
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0

    # 日期追蹤
    _last_reset_day: str = ""


# ═══════════════════════════════════════════════════════════════
# Kelly Criterion 計算
# ═══════════════════════════════════════════════════════════════

def kelly_criterion(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = 0.5,  # Half-Kelly (更保守)
) -> float:
    """
    計算 Kelly Criterion 最優倉位比例

    Kelly 公式:
        f* = (p * b - q) / b

    其中:
        p = 勝率
        q = 1 - p (敗率)
        b = 平均獲利 / 平均虧損 (賠率)
        f* = 最優倉位比例

    Args:
        win_rate: 勝率 (0~1)
        avg_win: 平均獲利金額
        avg_loss: 平均虧損金額 (正數)
        fraction: Kelly 分數 (0.5 = Half-Kelly，更安全)

    Returns:
        建議倉位比例 (0~1)
    """
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0

    p = min(1.0, max(0.0, win_rate))
    q = 1.0 - p
    b = avg_win / avg_loss  # 賠率

    # Kelly 公式
    kelly_f = (p * b - q) / b

    # 限制範圍
    kelly_f = max(0.0, kelly_f)

    # 使用 fractional Kelly（更保守）
    kelly_f *= fraction

    # 上限 (永遠不超過 40%)
    kelly_f = min(kelly_f, 0.40)

    return kelly_f


# ═══════════════════════════════════════════════════════════════
# 風險管理器
# ═══════════════════════════════════════════════════════════════

class RiskManager:
    """
    綜合風險管理器

    嵌入交易流程前，提供倉位大小建議和熔斷保護。
    """

    def __init__(self):
        self._cb_state = CircuitBreakerState()
        self._trade_log: List[Dict] = []  # 最近交易記錄
        self._enabled = True

        logger.info("🛡️ 風險管理器已初始化")

    # ── 主要介面 ──────────────────────────────────────────────

    def calculate_position_size(
        self,
        balance: float,
        signal_confidence: float,
        trading_mode: str,
        volatility_pct: float = 0.5,
        contract_price: float = 0.5,
    ) -> PositionSizeResult:
        """
        計算建議倉位大小

        整合三層風險管理:
            1. Kelly Criterion → 最優比例上限
            2. Circuit Breakers → 熔斷攔截
            3. 動態調整 → 信心度 × 波動率 × 近期表現

        Args:
            balance: 當前可用資金
            signal_confidence: 信號信心度 (0~100)
            trading_mode: 交易模式名稱
            volatility_pct: 近期波動率百分比
            contract_price: Polymarket 合約價格

        Returns:
            PositionSizeResult
        """
        risk_cfg = config.RISK_MANAGEMENT
        mode_cfg = config.TRADING_MODES.get(trading_mode, config.TRADING_MODES["balanced"])

        # ── Step 0: 檢查熔斷 ──────────────────────────────────
        cb_active, cb_reason = self._check_circuit_breakers(balance)
        if cb_active:
            return PositionSizeResult(
                recommended_amount=0.0,
                kelly_fraction=0.0,
                position_pct=0.0,
                confidence_multiplier=0.0,
                volatility_multiplier=0.0,
                circuit_breaker_active=True,
                circuit_breaker_reason=cb_reason,
                risk_score=100.0,
                details={"circuit_breaker": cb_reason},
            )

        # ── Step 1: Kelly Criterion 計算 ──────────────────────
        win_rate, avg_win, avg_loss = self._get_recent_stats()
        kelly_f = kelly_criterion(
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            fraction=risk_cfg["kelly_fraction"],
        )

        # ── Step 2: 模式上限 ──────────────────────────────────
        mode_max_pct = mode_cfg["max_position_pct"]

        # ── Step 3: 信心度調整 ────────────────────────────────
        # 信心度 50 = 1.0x，100 = 1.5x，25 = 0.625x
        confidence_mult = 0.5 + (signal_confidence / 100) * 0.5
        confidence_mult = max(0.25, min(1.5, confidence_mult))

        # ── Step 4: 波動率調整 ────────────────────────────────
        # 高波動 → 降倉，低波動 → 正常
        vol_low = config.MARKET_REGIME_CONFIG["volatility_low"]
        vol_high = config.MARKET_REGIME_CONFIG["volatility_high"]
        if volatility_pct > vol_high:
            vol_mult = 0.5  # 高波動時降 50%
        elif volatility_pct > vol_low:
            # 線性插值
            vol_mult = 1.0 - 0.5 * (volatility_pct - vol_low) / (vol_high - vol_low)
        else:
            vol_mult = 1.0  # 低波動不調整

        # ── Step 5: 連敗調整 ──────────────────────────────────
        streak_penalty = 1.0
        if self._cb_state.consecutive_losses >= 2:
            # 每多一次連敗，降 15% 倉位
            streak_penalty = max(0.3, 1.0 - (self._cb_state.consecutive_losses - 1) * 0.15)

        # ── Step 6: 合併計算 ──────────────────────────────────
        # Kelly 建議值和模式上限取較小值
        kelly_limited = min(kelly_f, mode_max_pct) if kelly_f > 0 else mode_max_pct

        # 動態倉位 = kelly限制 × 信心度 × 波動率 × 連敗調整
        final_pct = kelly_limited * confidence_mult * vol_mult * streak_penalty

        # 全局下限和上限
        final_pct = max(risk_cfg["min_position_pct"], final_pct)
        final_pct = min(risk_cfg["max_position_pct"], final_pct)

        # 計算實際金額
        recommended_amount = balance * final_pct

        # 最低交易金額
        if recommended_amount < config.PROFIT_FILTER_MIN_TRADE_AMOUNT:
            recommended_amount = 0.0

        # ── Step 7: 風險評分 ──────────────────────────────────
        # 0 = 低風險, 100 = 高風險
        risk_score = self._calculate_risk_score(
            final_pct, volatility_pct, self._cb_state.consecutive_losses,
            self._cb_state.current_drawdown_pct
        )

        details = {
            "kelly_raw": round(kelly_f, 4),
            "mode_max_pct": mode_max_pct,
            "kelly_limited": round(kelly_limited, 4),
            "confidence_mult": round(confidence_mult, 3),
            "volatility_mult": round(vol_mult, 3),
            "streak_penalty": round(streak_penalty, 3),
            "final_pct": round(final_pct, 4),
            "win_rate": round(win_rate, 3),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "consecutive_losses": self._cb_state.consecutive_losses,
            "daily_pnl": round(self._cb_state.daily_pnl, 2),
            "current_drawdown_pct": round(self._cb_state.current_drawdown_pct, 2),
        }

        logger.debug(
            f"📐 倉位計算 | Kelly={kelly_f:.3f} | Mode上限={mode_max_pct:.2f} | "
            f"信心={confidence_mult:.2f} | 波動={vol_mult:.2f} | 連敗={streak_penalty:.2f} | "
            f"最終={final_pct:.4f} → ${recommended_amount:.2f}"
        )

        return PositionSizeResult(
            recommended_amount=round(recommended_amount, 2),
            kelly_fraction=round(kelly_f, 4),
            position_pct=round(final_pct, 4),
            confidence_multiplier=round(confidence_mult, 3),
            volatility_multiplier=round(vol_mult, 3),
            circuit_breaker_active=False,
            circuit_breaker_reason="",
            risk_score=round(risk_score, 1),
            details=details,
        )

    # ── 交易事件回報 ──────────────────────────────────────────

    def on_trade_opened(self, amount: float, balance: float):
        """通知風險管理器：已開倉"""
        self._cb_state.daily_trade_count += 1
        self._maybe_reset_daily()

    def on_trade_closed(self, pnl: float, balance: float, won: bool):
        """
        通知風險管理器：已平倉

        更新連敗計數、日 PnL、最大回撤等。
        """
        self._maybe_reset_daily()

        # 記錄交易
        self._trade_log.append({
            "pnl": pnl,
            "won": won,
            "balance_after": balance,
            "timestamp": time.time(),
        })

        # 只保留最近 100 筆
        if len(self._trade_log) > 100:
            self._trade_log = self._trade_log[-100:]

        # 更新日 PnL
        self._cb_state.daily_pnl += pnl

        # 更新連敗
        if won:
            self._cb_state.consecutive_losses = 0
        else:
            self._cb_state.consecutive_losses += 1

        # 更新最大回撤
        if balance > self._cb_state.peak_equity:
            self._cb_state.peak_equity = balance
        if self._cb_state.peak_equity > 0:
            self._cb_state.current_drawdown_pct = (
                (self._cb_state.peak_equity - balance) / self._cb_state.peak_equity * 100
            )
        else:
            self._cb_state.current_drawdown_pct = 0.0

        # 檢查是否觸發熔斷
        self._check_circuit_breakers(balance)

    # ── 熔斷保護 ──────────────────────────────────────────────

    def _check_circuit_breakers(self, balance: float) -> Tuple[bool, str]:
        """
        檢查所有熔斷條件

        Returns:
            (是否觸發, 原因)
        """
        risk_cfg = config.RISK_MANAGEMENT

        # 如果已經在冷卻期
        if self._cb_state.triggered:
            if time.time() < self._cb_state.cooldown_until:
                remaining = int(self._cb_state.cooldown_until - time.time())
                return True, f"{self._cb_state.reason} (冷卻剩餘 {remaining}s)"
            else:
                # 冷卻結束，重置熔斷
                logger.info("🔄 熔斷冷卻結束，恢復交易")
                self._cb_state.triggered = False
                self._cb_state.reason = ""

        # ── 檢查 1: 日虧損上限 ────────────────────────────────
        if risk_cfg["daily_loss_limit_enabled"]:
            daily_limit = risk_cfg["daily_loss_limit_pct"]
            if balance > 0:
                daily_loss_pct = abs(min(0, self._cb_state.daily_pnl)) / balance * 100
                if daily_loss_pct >= daily_limit:
                    reason = f"日虧損觸發 ({daily_loss_pct:.1f}% ≥ {daily_limit}%)"
                    self._trigger_circuit_breaker(reason, risk_cfg["circuit_breaker_cooldown"])
                    return True, reason

        # ── 檢查 2: 連敗上限 ──────────────────────────────────
        if risk_cfg["consecutive_loss_limit_enabled"]:
            max_streak = risk_cfg["consecutive_loss_limit"]
            if self._cb_state.consecutive_losses >= max_streak:
                reason = f"連敗觸發 ({self._cb_state.consecutive_losses} ≥ {max_streak})"
                self._trigger_circuit_breaker(reason, risk_cfg["circuit_breaker_cooldown"])
                return True, reason

        # ── 檢查 3: 最大回撤 ──────────────────────────────────
        if risk_cfg["max_drawdown_limit_enabled"]:
            dd_limit = risk_cfg["max_drawdown_limit_pct"]
            if self._cb_state.current_drawdown_pct >= dd_limit:
                reason = f"最大回撤觸發 ({self._cb_state.current_drawdown_pct:.1f}% ≥ {dd_limit}%)"
                self._trigger_circuit_breaker(reason, risk_cfg["circuit_breaker_cooldown"] * 2)  # 回撤熔斷時間 2 倍
                return True, reason

        # ── 檢查 4: 日交易次數上限 ────────────────────────────
        if risk_cfg["daily_trade_limit_enabled"]:
            max_trades = risk_cfg["daily_trade_limit"]
            if self._cb_state.daily_trade_count >= max_trades:
                reason = f"日交易次數觸發 ({self._cb_state.daily_trade_count} ≥ {max_trades})"
                self._trigger_circuit_breaker(reason, 3600)  # 冷卻 1 小時
                return True, reason

        return False, ""

    def _trigger_circuit_breaker(self, reason: str, cooldown_seconds: int):
        """觸發熔斷"""
        self._cb_state.triggered = True
        self._cb_state.reason = reason
        self._cb_state.triggered_at = time.time()
        self._cb_state.cooldown_until = time.time() + cooldown_seconds
        logger.warning(
            f"🔴 熔斷觸發！ | 原因: {reason} | "
            f"冷卻: {cooldown_seconds}s"
        )

    # ── 統計計算 ──────────────────────────────────────────────

    def _get_recent_stats(self, lookback: int = 20) -> Tuple[float, float, float]:
        """
        計算最近 N 筆交易的勝率和平均盈虧

        Returns:
            (win_rate, avg_win, avg_loss)
        """
        if not self._trade_log:
            # 無歷史數據，使用保守預設值
            return 0.50, 1.0, 1.0

        recent = self._trade_log[-lookback:]
        wins = [t for t in recent if t["won"]]
        losses = [t for t in recent if not t["won"]]

        win_rate = len(wins) / len(recent) if recent else 0.5

        avg_win = (
            sum(abs(t["pnl"]) for t in wins) / len(wins)
            if wins else 1.0
        )

        avg_loss = (
            sum(abs(t["pnl"]) for t in losses) / len(losses)
            if losses else 1.0
        )

        return win_rate, avg_win, avg_loss

    def _calculate_risk_score(
        self,
        position_pct: float,
        volatility_pct: float,
        consecutive_losses: int,
        drawdown_pct: float,
    ) -> float:
        """
        計算綜合風險評分 (0~100)

        0 = 風險極低, 100 = 風險極高
        """
        score = 0.0

        # 倉位比例風險 (0~30)
        score += min(30, position_pct * 100)

        # 波動率風險 (0~25)
        score += min(25, volatility_pct * 15)

        # 連敗風險 (0~25)
        score += min(25, consecutive_losses * 6)

        # 回撤風險 (0~20)
        score += min(20, drawdown_pct * 2)

        return min(100, score)

    def _maybe_reset_daily(self):
        """每日重置計數器"""
        today = time.strftime("%Y-%m-%d")
        if self._cb_state._last_reset_day != today:
            self._cb_state._last_reset_day = today
            self._cb_state.daily_pnl = 0.0
            self._cb_state.daily_trade_count = 0
            logger.debug(f"📅 日計數器已重置 ({today})")

    # ── 狀態查詢 ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """取得完整風險管理狀態（供 Dashboard / API 使用）"""
        win_rate, avg_win, avg_loss = self._get_recent_stats()
        kelly_f = kelly_criterion(
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            fraction=config.RISK_MANAGEMENT.get("kelly_fraction", 0.5),
        )

        return {
            "enabled": self._enabled,
            "circuit_breaker": {
                "triggered": self._cb_state.triggered,
                "reason": self._cb_state.reason,
                "cooldown_until": self._cb_state.cooldown_until,
                "remaining_seconds": max(0, int(
                    self._cb_state.cooldown_until - time.time()
                )) if self._cb_state.triggered else 0,
            },
            "kelly": {
                "fraction": round(kelly_f, 4),
                "win_rate": round(win_rate, 3),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "payoff_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
            },
            "daily": {
                "pnl": round(self._cb_state.daily_pnl, 2),
                "trade_count": self._cb_state.daily_trade_count,
            },
            "drawdown": {
                "current_pct": round(self._cb_state.current_drawdown_pct, 2),
                "peak_equity": round(self._cb_state.peak_equity, 2),
            },
            "consecutive_losses": self._cb_state.consecutive_losses,
            "total_logged_trades": len(self._trade_log),
        }

    def reset(self, initial_balance: float = 1000.0):
        """重置風險管理器"""
        self._cb_state = CircuitBreakerState()
        self._cb_state.peak_equity = initial_balance
        self._trade_log.clear()
        logger.info("🔄 風險管理器已重置")


# ── 全局實例 ──────────────────────────────────────────────────
risk_manager = RiskManager()
