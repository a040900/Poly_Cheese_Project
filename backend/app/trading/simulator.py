"""
🧀 CheeseDog - 模擬交易引擎
維護虛擬資金帳戶，模擬在 Polymarket 上的交易行為。
"""

import time
import logging
from typing import Optional, Dict, List

from app import config
from app.database import db
from app.strategy.fees import fee_model

logger = logging.getLogger("cheesedog.trading.simulator")


class SimulationTrade:
    """單筆模擬交易"""

    def __init__(
        self,
        trade_id: int,
        direction: str,
        entry_price: float,
        quantity: float,
        signal_score: float,
        trading_mode: str,
    ):
        self.trade_id = trade_id
        self.direction = direction       # "BUY_UP" 或 "SELL_DOWN"
        self.entry_price = entry_price
        self.quantity = quantity          # USDC 金額
        self.signal_score = signal_score
        self.trading_mode = trading_mode
        self.entry_time = time.time()
        self.exit_price: Optional[float] = None
        self.exit_time: Optional[float] = None
        self.pnl: float = 0.0
        self.status: str = "open"


class SimulationEngine:
    """模擬交易引擎"""

    def __init__(self, initial_balance: float = config.SIM_INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.open_trades: List[SimulationTrade] = []
        self.trade_history: List[Dict] = []
        self.total_trades = 0
        self.total_pnl = 0.0
        self._running = False

        logger.info(f"💰 模擬交易引擎已初始化 | 初始資金: ${initial_balance:.2f} USDC")

    def start(self):
        """啟動模擬交易"""
        self._running = True
        logger.info("🟢 模擬交易引擎已啟動")

    def stop(self):
        """停止模擬交易"""
        self._running = False
        logger.info("🔴 模擬交易引擎已停止")

    def is_running(self) -> bool:
        return self._running

    def execute_trade(
        self,
        signal: dict,
        amount: Optional[float] = None,
    ) -> Optional[SimulationTrade]:
        """
        執行模擬交易

        Args:
            signal: 交易信號
            amount: 交易金額（None 則使用風險評估建議金額）

        Returns:
            SimulationTrade 物件或 None
        """
        if not self._running:
            logger.warning("模擬交易引擎未啟動")
            return None

        direction = signal.get("direction")
        if direction == "NEUTRAL":
            return None

        # 確定交易金額
        if amount is None:
            mode_config = config.TRADING_MODES.get(
                signal.get("mode", "balanced"),
                config.TRADING_MODES["balanced"]
            )
            confidence = signal.get("confidence", 50)
            amount = self.balance * mode_config["max_position_pct"] * (confidence / 100)

        # 檢查餘額
        if amount <= 0 or amount > self.balance:
            logger.warning(f"資金不足: 需要 ${amount:.2f}, 可用 ${self.balance:.2f}")
            return None

        # 計算手續費（Phase 2: 使用 Polymarket 浮動費率）
        # BUY_UP 方向 = 買入 UP 合約，SELL_DOWN 方向 = 買入 DOWN 合約
        # 兩者在開倉時都是 "buy" 操作
        fee_result = fee_model.calculate_buy_fee(amount, contract_price=0.5)
        fee = fee_result.fee_amount

        # 記錄到資料庫
        trade_data = {
            "trade_type": "simulation",
            "direction": direction,
            "entry_time": time.time(),
            "entry_price": signal.get("score", 0),
            "quantity": amount,
            "fee": fee,
            "fee_rate": fee_result.fee_rate,
            "signal_score": signal.get("score", 0),
            "trading_mode": signal.get("mode", "balanced"),
            "status": "open",
            "metadata": {
                "confidence": signal.get("confidence"),
                "indicators": signal.get("indicators", {}),
                "fee_model": "polymarket_15m",
                "fee_side": "buy",
                "fee_deducted_in": fee_result.fee_deducted_in,
            },
        }
        trade_id = db.save_trade(trade_data)

        # 建立交易物件
        trade = SimulationTrade(
            trade_id=trade_id,
            direction=direction,
            entry_price=signal.get("score", 0),
            quantity=amount,
            signal_score=signal.get("score", 0),
            trading_mode=signal.get("mode", "balanced"),
        )

        # 扣除資金和手續費
        self.balance -= (amount + fee)
        self.open_trades.append(trade)
        self.total_trades += 1

        logger.info(
            f"📈 模擬交易開倉 | 方向: {direction} | "
            f"金額: ${amount:.2f} | 手續費: ${fee:.4f} | "
            f"剩餘: ${self.balance:.2f}"
        )

        return trade

    def settle_trade(
        self,
        trade: SimulationTrade,
        market_result: str,
        settlement_price: float = 1.0,
    ) -> float:
        """
        結算模擬交易

        Args:
            trade: 要結算的交易
            market_result: 市場結果 "UP" 或 "DOWN"
            settlement_price: 結算價格

        Returns:
            盈虧金額
        """
        trade.exit_time = time.time()
        trade.exit_price = settlement_price

        # 判斷勝負
        if trade.direction == "BUY_UP":
            won = market_result == "UP"
        else:  # SELL_DOWN
            won = market_result == "DOWN"

        # 計算盈虧（Phase 2: 含 Sell 端手續費）
        # Polymarket: 勝利 = 獲得約 (1/price - 1) * quantity 的利潤
        # 結算時賣出（或贖回），需扣除 Sell 端手續費
        if won:
            gross_profit = trade.quantity * 0.85  # 模擬回報率約 85%
            sell_fee = fee_model.calculate_sell_fee(
                trade.quantity + gross_profit, contract_price=0.5
            )
            trade.pnl = gross_profit - sell_fee.fee_amount
            self.balance += trade.quantity + trade.pnl
        else:
            trade.pnl = -trade.quantity
            # 資金已扣除，無需額外操作

        trade.status = "closed"
        self.total_pnl += trade.pnl

        # 更新資料庫
        db.update_trade(trade.trade_id, {
            "exit_time": trade.exit_time,
            "exit_price": trade.exit_price,
            "pnl": trade.pnl,
            "status": "closed",
        })

        # 從未平倉列表移除
        self.open_trades = [t for t in self.open_trades if t.trade_id != trade.trade_id]

        # 記錄到歷史
        self.trade_history.append({
            "trade_id": trade.trade_id,
            "direction": trade.direction,
            "quantity": trade.quantity,
            "pnl": trade.pnl,
            "won": won,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
        })

        result_emoji = "✅" if won else "❌"
        logger.info(
            f"{result_emoji} 模擬交易結算 | 方向: {trade.direction} | "
            f"金額: ${trade.quantity:.2f} | 盈虧: ${trade.pnl:+.2f} | "
            f"餘額: ${self.balance:.2f}"
        )

        return trade.pnl

    def auto_settle_expired(self, btc_price_start: float, btc_price_end: float):
        """
        自動結算 15 分鐘到期的交易

        Args:
            btc_price_start: 15 分鐘開始時的 BTC 價格
            btc_price_end: 15 分鐘結束時的 BTC 價格
        """
        if not self.open_trades:
            return

        market_result = "UP" if btc_price_end > btc_price_start else "DOWN"

        for trade in list(self.open_trades):
            # 檢查是否已超過 15 分鐘
            elapsed = time.time() - trade.entry_time
            if elapsed >= 900:  # 15 分鐘
                self.settle_trade(trade, market_result)

    def reset(self, new_balance: Optional[float] = None):
        """重置模擬帳戶"""
        self.balance = new_balance or self.initial_balance
        self.open_trades.clear()
        self.trade_history.clear()
        self.total_trades = 0
        self.total_pnl = 0.0
        logger.info(f"🔄 模擬帳戶已重置 | 初始資金: ${self.balance:.2f}")

    def get_stats(self) -> dict:
        """取得模擬交易統計"""
        wins = sum(1 for t in self.trade_history if t.get("won"))
        losses = len(self.trade_history) - wins
        total_closed = len(self.trade_history)

        return {
            "balance": round(self.balance, 2),
            "initial_balance": self.initial_balance,
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(
                (self.total_pnl / self.initial_balance * 100)
                if self.initial_balance > 0 else 0, 2
            ),
            "total_trades": self.total_trades,
            "closed_trades": total_closed,
            "open_trades": len(self.open_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total_closed * 100, 2) if total_closed > 0 else 0,
            "is_running": self._running,
        }

    def get_recent_trades(self, limit: int = 10) -> List[dict]:
        """取得最近的交易記錄（含未平倉）"""
        trades = []

        # 未平倉交易
        for t in self.open_trades:
            elapsed = time.time() - t.entry_time
            trades.append({
                "trade_id": t.trade_id,
                "direction": t.direction,
                "quantity": round(t.quantity, 2),
                "pnl": 0,
                "status": "open",
                "entry_time": t.entry_time,
                "elapsed_min": round(elapsed / 60, 1),
                "trading_mode": t.trading_mode,
            })

        # 最近已結算交易（倒序，最新的在前）
        for t in reversed(self.trade_history[-limit:]):
            trades.append({
                "trade_id": t["trade_id"],
                "direction": t["direction"],
                "quantity": round(t["quantity"], 2),
                "pnl": round(t.get("pnl", 0), 2),
                "status": "closed",
                "won": t.get("won", False),
                "entry_time": t.get("entry_time", 0),
                "exit_time": t.get("exit_time", 0),
            })

        return trades

    def get_pnl_curve(self) -> List[dict]:
        """取得 PnL 曲線數據"""
        curve = []
        cumulative_pnl = 0.0
        for trade in self.trade_history:
            cumulative_pnl += trade.get("pnl", 0)
            curve.append({
                "trade_id": trade["trade_id"],
                "time": trade["exit_time"],
                "pnl": round(trade["pnl"], 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "balance": round(self.initial_balance + cumulative_pnl, 2),
            })
        return curve
