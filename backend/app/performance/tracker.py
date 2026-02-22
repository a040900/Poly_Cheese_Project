"""
🧀 CheeseDog - 績效追蹤模組 (步驟 12a)
即時追蹤交易績效，計算關鍵風險/報酬指標。

指標清單:
- 勝率 (Win Rate)
- 最大回撤 (Max Drawdown)
- 夏普比率 (Sharpe Ratio)
- 收益因子 (Profit Factor)
- 期望值 (Expectancy)
- 各交易模式獨立統計
"""

import math
import time
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("cheesedog.performance.tracker")


@dataclass
class ModeStats:
    """單一交易模式的績效統計"""
    mode: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_fees: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    pnl_list: List[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades * 100) if self.trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        """收益因子: 總盈利 / 總虧損（> 1 為正期望）"""
        return (self.gross_profit / abs(self.gross_loss)) if self.gross_loss != 0 else float("inf")

    @property
    def expectancy(self) -> float:
        """期望值: 每筆交易的平均盈虧"""
        return (self.total_pnl / self.trades) if self.trades > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 2),
            "total_pnl": round(self.total_pnl, 2),
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "total_fees": round(self.total_fees, 4),
            "best_trade": round(self.best_trade, 2),
            "worst_trade": round(self.worst_trade, 2),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "∞",
            "expectancy": round(self.expectancy, 4),
        }


class PerformanceTracker:
    """
    績效追蹤器

    接收已結算的交易記錄，持續更新績效指標。
    可用於即時監控，也可用於回測結果分析。
    """

    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self._equity_curve: List[float] = [initial_balance]
        self._trade_log: List[dict] = []
        self._mode_stats: Dict[str, ModeStats] = {}
        self._peak_equity = initial_balance

    def record_trade(self, trade: dict):
        """
        記錄一筆已結算的交易

        Args:
            trade: {
                "direction": str,
                "quantity": float,
                "pnl": float,
                "fee": float,
                "trading_mode": str,
                "entry_time": float,
                "exit_time": float,
                "won": bool,
            }
        """
        self._trade_log.append(trade)

        pnl = trade.get("pnl", 0.0)
        fee = trade.get("fee", 0.0)
        mode = trade.get("trading_mode", "balanced")
        won = trade.get("won", pnl > 0)

        # 更新權益曲線
        last_equity = self._equity_curve[-1]
        new_equity = last_equity + pnl
        self._equity_curve.append(new_equity)

        # 更新峰值
        if new_equity > self._peak_equity:
            self._peak_equity = new_equity

        # 分模式統計
        if mode not in self._mode_stats:
            self._mode_stats[mode] = ModeStats(mode=mode)

        ms = self._mode_stats[mode]
        ms.trades += 1
        ms.total_pnl += pnl
        ms.total_fees += fee
        ms.pnl_list.append(pnl)

        if won:
            ms.wins += 1
            ms.gross_profit += pnl
        else:
            ms.losses += 1
            ms.gross_loss += pnl  # pnl 為負數

        if pnl > ms.best_trade:
            ms.best_trade = pnl
        if pnl < ms.worst_trade:
            ms.worst_trade = pnl

    # ── 全局指標 ──────────────────────────────────────────────

    @property
    def total_trades(self) -> int:
        return len(self._trade_log)

    @property
    def total_pnl(self) -> float:
        return sum(t.get("pnl", 0) for t in self._trade_log)

    @property
    def current_equity(self) -> float:
        return self._equity_curve[-1] if self._equity_curve else self.initial_balance

    @property
    def total_return_pct(self) -> float:
        return ((self.current_equity - self.initial_balance) / self.initial_balance * 100) if self.initial_balance > 0 else 0

    def max_drawdown(self) -> dict:
        """
        計算最大回撤 (Max Drawdown)

        Returns:
            {
                "max_dd_pct": float,   # 最大回撤百分比
                "max_dd_amount": float, # 最大回撤金額
                "peak": float,         # 峰值
                "trough": float,       # 谷值
            }
        """
        if len(self._equity_curve) < 2:
            return {"max_dd_pct": 0, "max_dd_amount": 0, "peak": self.initial_balance, "trough": self.initial_balance}

        peak = self._equity_curve[0]
        max_dd = 0.0
        max_dd_peak = peak
        max_dd_trough = peak

        for equity in self._equity_curve:
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
                max_dd_peak = peak
                max_dd_trough = equity

        max_dd_pct = (max_dd / max_dd_peak * 100) if max_dd_peak > 0 else 0

        return {
            "max_dd_pct": round(max_dd_pct, 2),
            "max_dd_amount": round(max_dd, 2),
            "peak": round(max_dd_peak, 2),
            "trough": round(max_dd_trough, 2),
        }

    def sharpe_ratio(self, risk_free_rate: float = 0.0, annualize_factor: float = 96.0) -> float:
        """
        計算夏普比率

        Args:
            risk_free_rate: 無風險利率 (預設 0)
            annualize_factor: 年化因子（15 分鐘交易，一天 96 期）

        Returns:
            夏普比率（年化）
        """
        all_pnl = [t.get("pnl", 0) for t in self._trade_log]
        if len(all_pnl) < 2:
            return 0.0

        # 計算報酬率序列
        returns = []
        equity = self.initial_balance
        for pnl in all_pnl:
            ret = pnl / equity if equity > 0 else 0
            returns.append(ret)
            equity += pnl

        avg_return = sum(returns) / len(returns)
        std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns))

        if std_return == 0:
            return 0.0

        # 年化
        sharpe = ((avg_return - risk_free_rate) / std_return) * math.sqrt(annualize_factor * 365)
        return round(sharpe, 2)

    def win_rate(self) -> float:
        """全局勝率"""
        if not self._trade_log:
            return 0.0
        wins = sum(1 for t in self._trade_log if t.get("pnl", 0) > 0)
        return round(wins / len(self._trade_log) * 100, 2)

    def profit_factor(self) -> float:
        """全局收益因子"""
        gross_profit = sum(t["pnl"] for t in self._trade_log if t.get("pnl", 0) > 0)
        gross_loss = sum(t["pnl"] for t in self._trade_log if t.get("pnl", 0) < 0)
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return round(gross_profit / abs(gross_loss), 2)

    # ── 報告生成 ──────────────────────────────────────────────

    def get_report(self) -> dict:
        """生成完整績效報告"""
        dd = self.max_drawdown()
        total_fees = sum(t.get("fee", 0) for t in self._trade_log)

        return {
            "summary": {
                "initial_balance": self.initial_balance,
                "final_equity": round(self.current_equity, 2),
                "total_pnl": round(self.total_pnl, 2),
                "total_return_pct": round(self.total_return_pct, 2),
                "total_trades": self.total_trades,
                "win_rate": self.win_rate(),
                "profit_factor": self.profit_factor(),
                "sharpe_ratio": self.sharpe_ratio(),
                "total_fees": round(total_fees, 4),
                "net_pnl_after_fees": round(self.total_pnl, 2),
            },
            "drawdown": dd,
            "equity_curve": [round(e, 2) for e in self._equity_curve],
            "by_mode": {
                mode: stats.to_dict()
                for mode, stats in self._mode_stats.items()
            },
        }

    def get_snapshot(self) -> dict:
        """取得當前績效快照（供 AI Engine 使用）"""
        return {
            "initial_balance": self.initial_balance,
            "current_equity": round(self.current_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_trades": self.total_trades,
            "win_rate": self.win_rate(),
            "profit_factor": self.profit_factor(),
            "max_drawdown": self.max_drawdown(),
        }

    def reset(self, initial_balance: Optional[float] = None):
        """重置追蹤器"""
        if initial_balance is not None:
            self.initial_balance = initial_balance
        self._equity_curve = [self.initial_balance]
        self._trade_log = []
        self._mode_stats = {}
        self._peak_equity = self.initial_balance
